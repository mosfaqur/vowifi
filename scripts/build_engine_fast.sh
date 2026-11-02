#!/bin/bash
# build_engine_fast.sh
# Quickly builds the vowifi/engine image by layering Python SWu dependencies
# on top of phcodercat/asterisk-vowifi:latest (avoiding 20-min Asterisk recompilation).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REPO_DIR="${1:-/root/vowifi_gateway}"
FAST_DOCKERFILE="${2:-$REPO_ROOT/Dockerfile.fast}"

echo "==> Pulling base Asterisk image (phcodercat/asterisk-vowifi:latest)..."
docker pull phcodercat/asterisk-vowifi:latest

if [ -f "$REPO_DIR/engine/swu_ike.py" ]; then
    echo "==> Applying Python 3.14 & IPv6 compatibility patches to swu_ike.py..."
    python3 "$SCRIPT_DIR/patch_swu_ike.py" "$REPO_DIR/engine/swu_ike.py"
fi

echo "==> Building vowifi/engine using fast-layer build..."
docker build -t vowifi/engine -f "$FAST_DOCKERFILE" "$REPO_DIR/engine"

echo "==> vowifi/engine built successfully!"
