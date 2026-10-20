#!/bin/bash
# setup_lxc_host.sh
# Execute on the Proxmox VE host (e.g. 192.168.1.3) as root.

set -euo pipefail

echo "==> Loading required IPsec and TUN kernel modules on Proxmox host..."
modprobe tun esp4 esp6 xfrm_user af_key xfrm_interface

cat << 'EOF' > /etc/modules-load.d/vowifi-ipsec.conf
tun
esp4
esp6
xfrm_user
af_key
xfrm_interface
EOF

echo "==> Configuring udev rule for USB Smart Card Reader (Realtek 0bda:0169)..."
cat << 'EOF' > /etc/udev/rules.d/99-smartcard.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="0169", MODE="0666"
EOF

udevadm control --reload-rules
udevadm trigger

echo "==> Verifying host USB permissions..."
ls -l /dev/bus/usb/001/002 || true

echo "==> Proxmox host setup completed."
