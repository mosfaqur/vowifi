#!/bin/bash
# download_lxc_template.sh
# Downloads the pre-built VoWiFi Gateway LXC Master Template from GitHub Releases
# directly into Proxmox VE local template storage (/var/lib/vz/template/cache/).

set -euo pipefail

DEST_DIR="${1:-/var/lib/vz/template/cache}"
RELEASE_TAG="v1.0.0"
REPO="mosfaqur/vowifi"
BASE_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"
OUTPUT_FILE="${DEST_DIR}/vowifi-gateway-clean-ubuntu-24.04.tar.zst"
EXPECTED_SHA256="db917742fbbaf17506def222a3571874fff4f4c80c20327c54d48d8ccf613ccb"

echo "=========================================================="
echo " VoWiFi Gateway — Proxmox LXC Template Downloader"
echo "=========================================================="

mkdir -p "$DEST_DIR"
cd "$DEST_DIR"

echo "==> Downloading release parts from GitHub (${RELEASE_TAG})..."
for part in part-aa part-ab part-ac; do
    fname="vowifi-gateway-clean-ubuntu-24.04.tar.zst.${part}"
    if [ ! -f "$fname" ]; then
        echo "--> Downloading ${fname}..."
        curl -fSL --progress-bar "${BASE_URL}/${fname}" -o "${fname}"
    else
        echo "--> ${fname} already exists, skipping download."
    fi
done

echo "==> Reassembling master template..."
cat vowifi-gateway-clean-ubuntu-24.04.tar.zst.part-* > "${OUTPUT_FILE}.tmp"

echo "==> Verifying SHA256 checksum..."
ACTUAL_SHA256=$(sha256sum "${OUTPUT_FILE}.tmp" | awk '{print $1}')
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
    echo "ERROR: Checksum mismatch!"
    echo "Expected: $EXPECTED_SHA256"
    echo "Got:      $ACTUAL_SHA256"
    rm -f "${OUTPUT_FILE}.tmp"
    exit 1
fi

mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"
rm -f vowifi-gateway-clean-ubuntu-24.04.tar.zst.part-*

echo "==> Template installed successfully:"
echo "    File: $OUTPUT_FILE"
echo "    Size: $(du -h "$OUTPUT_FILE" | cut -f1)"
echo ""
if command -v pveam >/dev/null 2>&1; then
    echo "==> Proxmox VE Template List:"
    pveam list local | grep -E 'vowifi|NAME' || true
fi
echo "=========================================================="
echo " You can now create containers from this template in the"
echo " Proxmox Web GUI ('Create CT' -> Template: vowifi-gateway)!"
echo "=========================================================="
