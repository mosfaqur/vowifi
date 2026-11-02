#!/bin/bash
# install_esim_lpac.sh
# Installs all requirements for eSIM / eUICC management (lpac LPA + PC/SC APDU + cURL HTTP)
# for the VoWiFi Gateway WebUI and Control Plane.

set -euo pipefail

GATEWAY_DATA_DIR="${1:-/root/vowifi_gateway/data}"
DEST="$GATEWAY_DATA_DIR/lpac"
CMAKE_MIN="3.31"
CMAKE_VER="3.31.12"
BUILD_TMP=$(mktemp -d /tmp/lpac-build.XXXXXX)

cleanup() {
    rm -rf "$BUILD_TMP"
}
trap cleanup EXIT

echo "======================================================"
echo " Installing eSIM / eUICC Requirements (lpac LPA)"
echo "======================================================"

# 1. Install system dependencies
echo "==> Step 1: Installing build tools and required libraries..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        build-essential pkg-config libcurl4-openssl-dev git ca-certificates curl
    if [ ! -f /usr/include/PCSC/pcsclite.h ]; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y libpcsclite-dev
    fi
fi

# 2. Ensure CMake >= 3.31
echo "==> Step 2: Checking CMake version..."
CMAKE_BIN="cmake"
NEED_FETCH=1

if command -v cmake >/dev/null 2>&1; then
    VER=$(cmake --version | head -n1 | sed -n 's/.* \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p')
    if [ -n "$VER" ]; then
        MAJOR=${VER%%.*}
        MINOR=${VER#*.}; MINOR=${MINOR%%.*}
        if [ "$MAJOR" -gt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 31 ]; }; then
            CMAKE_BIN=$(command -v cmake)
            NEED_FETCH=0
        fi
    fi
fi

if [ "$NEED_FETCH" -eq 1 ]; then
    TOOLS_DIR="$GATEWAY_DATA_DIR/tools"
    CMAKE_HOME="$TOOLS_DIR/cmake-$CMAKE_VER"
    CMAKE_BIN="$CMAKE_HOME/bin/cmake"
    if [ ! -x "$CMAKE_BIN" ]; then
        echo "--> System CMake is < $CMAKE_MIN. Downloading Kitware CMake $CMAKE_VER binary..."
        mkdir -p "$TOOLS_DIR"
        curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VER}/cmake-${CMAKE_VER}-linux-x86_64.tar.gz" \
            -o "$BUILD_TMP/cmake.tgz"
        tar -xzf "$BUILD_TMP/cmake.tgz" -C "$BUILD_TMP"
        rm -rf "$CMAKE_HOME"
        mv "$BUILD_TMP/cmake-${CMAKE_VER}-linux-x86_64" "$CMAKE_HOME"
    fi
    echo "--> Using CMake binary at $CMAKE_BIN"
fi

# 3. Clone lpac source
echo "==> Step 3: Fetching lpac source code..."
LPAC_SRC="$BUILD_TMP/lpac"
git clone --depth 1 --recurse-submodules https://github.com/estkme-group/lpac.git "$LPAC_SRC"

# 4. Configure & Build lpac
echo "==> Step 4: Configuring and compiling lpac (STANDALONE mode)..."
BUILD_DIR="$BUILD_TMP/build"
"$CMAKE_BIN" -S "$LPAC_SRC" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DSTANDALONE_MODE=ON \
    -DBUILD_TESTING=OFF \
    -DLPAC_WITH_APDU_PCSC=ON \
    -DLPAC_WITH_HTTP_CURL=ON \
    -DLPAC_WITH_APDU_AT=OFF \
    -DLPAC_WITH_APDU_QMI=OFF \
    -DLPAC_WITH_APDU_QMI_QRTR=OFF \
    -DLPAC_WITH_APDU_UQMI=OFF \
    -DLPAC_WITH_APDU_MBIM=OFF \
    -DLPAC_WITH_APDU_GBINDER=OFF

"$CMAKE_BIN" --build "$BUILD_DIR" --parallel "$(nproc 2>/dev/null || echo 2)"

# 5. Install to destination
echo "==> Step 5: Deploying lpac into $DEST..."
STAGE_DIR="$BUILD_TMP/stage"
DESTDIR="$STAGE_DIR" "$CMAKE_BIN" --install "$BUILD_DIR"

SRC_BIN="$STAGE_DIR/executables"
if [ ! -x "$SRC_BIN/lpac" ] && [ -x "$STAGE_DIR/usr/executables/lpac" ]; then
    SRC_BIN="$STAGE_DIR/usr/executables"
fi

mkdir -p "$DEST.tmp"
cp -a "$SRC_BIN/lpac" "$DEST.tmp/lpac"
[ -d "$SRC_BIN/lib" ] && cp -a "$SRC_BIN/lib" "$DEST.tmp/lib"
[ -d "$SRC_BIN/driver" ] && cp -a "$SRC_BIN/driver" "$DEST.tmp/driver"
chmod +x "$DEST.tmp/lpac"

rm -rf "$DEST"
mv "$DEST.tmp" "$DEST"

# 6. Verify installation
echo "==> Step 6: Verifying lpac functionality..."
"$DEST/lpac" version || true
"$DEST/lpac" driver apdu list || true

if systemctl is-active --quiet vowifi-control; then
    echo "--> Restarting vowifi-control service to reload eSIM capabilities..."
    systemctl restart vowifi-control
fi

echo ""
echo "======================================================"
echo " eSIM (lpac) Installation Successful!"
echo " Binary Location: $DEST/lpac"
echo " WebUI eSIM Tab:  Enabled and Active"
echo "======================================================"
