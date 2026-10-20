#!/bin/bash
# deploy_lxc.sh
# Automated turnkey deployment script executed inside the unprivileged LXC container.
# Clones the upstream gateway, pre-builds the optimized engine image, and starts the system.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_DIR="${1:-/root/vowifi_gateway}"

echo "======================================================"
echo " VoWiFi Software UE — Automated LXC Container Deploy"
echo "======================================================"

# 1. Check prerequisites inside LXC
echo "==> Step 1: Checking container devices and prerequisites..."
if [ ! -e /dev/net/tun ]; then
    echo "ERROR: /dev/net/tun is missing in this container."
    echo "Make sure your Proxmox container config has 'dev1: /dev/net/tun,mode=0666'"
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "--> Installing Docker engine inside container..."
    apt-get update -y && apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -y && apt-get install -y docker-ce docker-ce-cli containerd.io
fi

# 2. Clone upstream vowifi_gateway if not present
echo "==> Step 2: Fetching upstream vowifi_gateway repository..."
if [ ! -d "$GATEWAY_DIR" ]; then
    git clone https://github.com/pagecat/vowifi_gateway.git "$GATEWAY_DIR"
else
    echo "    Target directory $GATEWAY_DIR already exists; using existing files."
fi

# 3. Pre-build vowifi/engine using fast-layer build
echo "==> Step 3: Building vowifi/engine using fast-layer Dockerfile (takes ~30s)..."
"$SCRIPT_DIR/build_engine_fast.sh" "$GATEWAY_DIR" "$REPO_ROOT/Dockerfile.fast"

# 4. Run install.sh from vowifi_gateway
echo "==> Step 4: Installing control plane dependencies and systemd service..."
cd "$GATEWAY_DIR"
./install.sh install --mode local

IP_ADDR="$(hostname -I | awk '{print $1}')"
echo ""
echo "======================================================"
echo " VoWiFi Gateway Deployment Successful!"
echo " WebUI Dashboard: https://${IP_ADDR}:8443"
echo "======================================================"
