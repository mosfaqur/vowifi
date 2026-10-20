#!/bin/bash
# build_engine_fast.sh
# Quickly builds the vowifi/engine image by layering Python SWu dependencies
# on top of phcodercat/asterisk-vowifi:latest (avoiding 20-min Asterisk recompilation).

set -euo pipefail

REPO_DIR="${1:-/root/vowifi_gateway}"
FAST_DOCKERFILE="${2:-/root/vowifi/Dockerfile.fast}"

echo "==> Pulling base Asterisk image (phcodercat/asterisk-vowifi:latest)..."
docker pull phcodercat/asterisk-vowifi:latest

echo "==> Building vowifi/engine using fast-layer build..."
docker build -t vowifi/engine -f "$FAST_DOCKERFILE" "$REPO_DIR/engine"

echo "==> vowifi/engine built successfully!"
