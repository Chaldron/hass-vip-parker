#!/usr/bin/env bash
#
# extract_api.sh — re-extract the VIP Parker (SMS Valet / TEZ) API from the
# currently-published Android APK, fully inside a podman container so nothing
# heavy is installed on the host.
#
# Usage:
#   ./extract_api.sh [OUTPUT_DIR]        # default: ./vipparker-extract
#
# Output: OUTPUT_DIR/report/*.txt  (provenance, base URL, pinning verdict,
#         firebase config, host list, raw endpoint pairs, verb-class freq, enums)
# plus the full jadx sources (jadx-out/) and apktool decode (smali-out/) for
# manual follow-up.
#
# After running, diff report/ against VIP_PARKER_API.md and fold in any new
# endpoints / fields / status codes. See the "Updating this doc" section there.
#
# Requires: podman (macOS or Linux). That's it.
set -euo pipefail

PKG="com.smsvalet.test"
OUT="${1:-$PWD/vipparker-extract}"
IMG="docker.io/library/eclipse-temurin:21-jdk"
export APKTOOL_URL="https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar"
export JADX_URL="https://github.com/skylot/jadx/releases/download/v1.5.0/jadx-1.5.0.zip"
export JAVA_OPTS="-Xmx2g"
export PKG

mkdir -p "$OUT"

# --- ensure the podman VM is up (macOS runs containers in a Linux VM) ---
if ! podman info >/dev/null 2>&1; then
  echo ">> starting podman machine..." >&2
  podman machine start
fi

# --- write the in-container analysis script (quoted heredoc: no host expansion) ---
cat > "$OUT/_analyze.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
cd /work
APK=vipparker.apk
SMALI=smali-out            # apktool full decode: smali/ + res/ + AndroidManifest.xml + apktool.yml
JADX=jadx-out
SRC="$JADX/sources"
REPORT=report
mkdir -p "$REPORT" tools

# 1. acquire APK (APKPure direct-download endpoint) ------------------------------
if [ ! -f "$APK" ]; then
  echo ">> downloading APK for $PKG ..." >&2
  curl -fL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
    -o "$APK" "https://d.apkpure.com/b/APK/${PKG}?version=latest"
fi

# 2. decode (fetching each tool lazily, only when its output is missing) --------
if [ ! -d "$SMALI/smali" ]; then
  [ -f tools/apktool.jar ] || curl -fsSL -o tools/apktool.jar "$APKTOOL_URL"
  java -jar tools/apktool.jar d -f -o "$SMALI" "$APK"
fi
if [ ! -d "$SRC" ]; then
  if [ ! -x jadx/bin/jadx ]; then
    [ -f tools/jadx.zip ] || curl -fsSL -o tools/jadx.zip "$JADX_URL"
    mkdir -p jadx && (cd jadx && jar xf ../tools/jadx.zip) && chmod +x jadx/bin/jadx
  fi
  jadx/bin/jadx -j 3 --no-res --no-debug-info -d "$JADX" "$APK" || true
fi

# 4. provenance -----------------------------------------------------------------
{ echo "package:    $PKG"
  grep -iE 'versionName|versionCode|minSdkVersion|targetSdkVersion' "$SMALI/apktool.yml" 2>/dev/null
  echo "apk_sha256: $(sha256sum "$APK" | awk '{print $1}')"
  echo "apk_bytes:  $(wc -c < "$APK")"
} > "$REPORT/00-provenance.txt"

# 5. config: base URL(s) + app API key ------------------------------------------
grep -rhoE '"https://[a-z0-9.]*smsvalet\.com/api/[a-z0-9/]*"' "$SRC" 2>/dev/null \
  | sort -u > "$REPORT/10-base-urls.txt" || true
grep -rhoE '"[A-Z0-9]{40,}"' "$SRC" 2>/dev/null | sort -u > "$REPORT/11-candidate-api-keys.txt" || true

# 6. TLS pinning verdict --------------------------------------------------------
{ echo "== network_security_config.xml =="
  find "$SMALI" -iname '*network*security*' -exec cat {} \; 2>/dev/null
  echo; echo "== code-level cert pins (sha256/...) =="
  grep -rnoE 'sha256/[A-Za-z0-9+/=]{20,}' "$SRC" 2>/dev/null || echo "NONE FOUND -> no active certificate pinning"
} > "$REPORT/12-pinning.txt"

# 7. Firebase / Google Services client config -----------------------------------
grep -rhiE '<string name="(google_api_key|google_app_id|gcm_defaultSenderId|default_web_client_id|firebase_database_url|google_storage_bucket|project_id)"' \
  "$SMALI"/res/values/strings.xml 2>/dev/null | sed -E 's/^ *//' > "$REPORT/13-firebase.txt" || true

# 8. every host referenced in code ----------------------------------------------
grep -rhoE 'https?://[a-zA-Z0-9._-]+' "$SRC" 2>/dev/null \
  | sed -E 's#https?://##' | sort | uniq -c | sort -rn > "$REPORT/14-hosts.txt" || true

# 9. endpoints — find interface smali with path-like annotation values ----------
#    (Retrofit is repackaged by R8, so annotation classes are renamed per build;
#    we key on the string VALUES, which survive, not on class names.)
IFACES=$(grep -rlE 'value = "[A-Z][A-Za-z0-9]+(/[A-Za-z0-9{}._-]+)*"' "$SMALI/smali" 2>/dev/null \
         | xargs grep -lE '\.method public abstract' 2>/dev/null | sort -u || true)
: > "$REPORT/20-endpoints-raw.txt"
for f in $IFACES; do
  echo "## $f" >> "$REPORT/20-endpoints-raw.txt"
  #  NB: in smali, parameter (.param) annotations are emitted *before* the
  #  method-level verb annotation, so we must skip anything inside a .param block
  #  and read only the method-level runtime annotation that carries the path.
  awk '
    function looksPath(v){ return (v ~ /\//) || (v ~ /^[A-Z][A-Za-z0-9]+$/) }
    /^\.method /                { cls=""; path=""; inm=1; inparam=0 }
    /\.param /                   { inparam=1 }
    /\.end param/                { inparam=0 }
    /\.annotation runtime L/     { if(inm && !inparam){ c=$0; sub(/.*runtime L/,"",c); sub(/;.*/,"",c); pend=c } }
    /value = "/                  { if(inm && !inparam && path==""){ v=$0; sub(/.*value = "/,"",v); sub(/".*/,"",v);
                                     if(looksPath(v)){ path=v; cls=pend } } }
    /\.end method/               { if(path!="") printf "%s\t%s\n", cls, path; inm=0 }
  ' "$f" >> "$REPORT/20-endpoints-raw.txt"
done
grep -vE '^##' "$REPORT/20-endpoints-raw.txt" | awk -F'\t' 'NF==2{print $1}' \
  | sort | uniq -c | sort -rn > "$REPORT/21-verb-class-freq.txt"
echo "$IFACES" > "$REPORT/22-interface-smali-files.txt"

# 10. status-style enums (Gson @SerializedName-mapped constants) ----------------
: > "$REPORT/30-enums.txt"
for f in $(grep -rlE 'CAR_|_STATUS|Status' "$SRC" 2>/dev/null); do
  grep -qE '\$VALUES' "$f" 2>/dev/null || continue
  names=$(grep -oE 'new [A-Za-z0-9_]+\("[A-Z][A-Z_]+"' "$f" 2>/dev/null | grep -oE '"[A-Z_]+"' | tr '\n' ' ')
  [ -n "$names" ] && echo "$f: $names" >> "$REPORT/30-enums.txt"
done

# 11. summary to stdout ---------------------------------------------------------
echo "================ SUMMARY ================"
cat "$REPORT/00-provenance.txt"
echo "-- base URLs --";        cat "$REPORT/10-base-urls.txt"
echo "-- pinning --";          tail -1 "$REPORT/12-pinning.txt"
echo "-- firebase project --"; grep -i project_id "$REPORT/13-firebase.txt" || true
echo "-- endpoint pairs --";   grep -cvE '^##|^$' "$REPORT/20-endpoints-raw.txt"
echo "-- verb-class freq (map these to GET/POST/PUT/DELETE, see doc) --"; cat "$REPORT/21-verb-class-freq.txt"
echo "-- status enums --";     cat "$REPORT/30-enums.txt"
echo "========================================="
echo "Full report in: $(pwd)/$REPORT   |   jadx sources: $(pwd)/$SRC"
EOS

# --- run it in the container with the work dir mounted ---
podman run --rm \
  -e PKG -e APKTOOL_URL -e JADX_URL -e JAVA_OPTS \
  -v "$OUT":/work "$IMG" bash /work/_analyze.sh

echo
echo ">> done. Report: $OUT/report/   Sources: $OUT/jadx-out/sources/"
