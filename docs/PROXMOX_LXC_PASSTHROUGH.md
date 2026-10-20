# Proxmox VE & LXC Hardware Passthrough Guide

This guide details how to configure an unprivileged LXC container in Proxmox VE 8+ to support both a USB Smart Card Reader (CCID) and a TUN/TAP network device for IPsec/VPN tunneling.

---

## 1. Proxmox Host Preparation

### 1.1 IPsec & Tunnel Kernel Modules
Ensure the host kernel has loaded the required IPsec and TUN modules. On the Proxmox host (`192.168.1.3`):

```bash
# Load required modules
modprobe tun esp4 esp6 xfrm_user af_key xfrm_interface

# Ensure they load automatically on boot
cat << 'EOF' > /etc/modules-load.d/vowifi-ipsec.conf
tun
esp4
esp6
xfrm_user
af_key
xfrm_interface
EOF
```

### 1.2 Identify USB Reader
Run `lsusb` on the Proxmox host:
```bash
lsusb
```
Example output:
```text
Bus 001 Device 002: ID 0bda:0169 Realtek Semiconductor Corp. Mass Storage Device
```
Verify the device interface class:
```bash
lsusb -v -d 0bda:0169 | grep -E 'bInterfaceClass|iInterface'
```
Confirm `bInterfaceClass 11 Chip/SmartCard` is listed.

### 1.3 Persistent Host Udev Rules
By default, USB device nodes under `/dev/bus/usb/` are created with `0664` permissions owned by `root:root`. An unprivileged container root user (UID 100000 on the host) will only have read-only access.

Create `/etc/udev/rules.d/99-smartcard.rules` on the Proxmox host:
```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0bda", ATTR{idProduct}=="0169", MODE="0666"
```

Reload and apply rules:
```bash
udevadm control --reload-rules && udevadm trigger
```

Verify permissions:
```bash
ls -l /dev/bus/usb/001/002
# Output should show crw-rw-rw- (0666)
```

---

## 2. Container Configuration (`/etc/pve/lxc/<VMID>.conf`)

On the Proxmox host, edit `/etc/pve/lxc/105.conf` (replace `105` with your container ID):

```ini
arch: amd64
cores: 4
features: nesting=1,keyctl=1
hostname: vowifi
memory: 4096
net0: name=eth0,bridge=vmbr0,firewall=1,gw=192.168.1.1,hwaddr=BC:24:11:CD:DD:5B,ip=192.168.1.105/24,type=veth
onboot: 1
ostype: ubuntu
rootfs: local-lvm:vm-105-disk-0,size=20G
swap: 512
unprivileged: 1
dev0: /dev/bus/usb/001/002,mode=0666
dev1: /dev/net/tun,mode=0666
```

### Configuration Parameters Explained

| Directive | Purpose |
| :--- | :--- |
| `features: nesting=1,keyctl=1` | **Required for Docker in LXC.** `nesting=1` enables cgroup and namespace isolation; `keyctl=1` enables the kernel keyring syscalls required by Docker and systemd. |
| `dev0: /dev/bus/usb/001/002,mode=0666` | Proxmox VE 8+ native device passthrough for the USB smart card reader. Automatically creates the device node inside `/dev/bus/usb/001/002` with 0666 permissions. |
| `dev1: /dev/net/tun,mode=0666` | Passes `/dev/net/tun` into the container with full read/write permissions for user-space IPsec (XFRM / TUN). |

Reboot the container to apply changes:
```bash
pct reboot 105
```

---

## 3. Verification Inside the Container

Execute commands inside container 105 to verify both devices:

```bash
# Verify USB Smart Card Reader node exists
pct exec 105 -- ls -la /dev/bus/usb/001/002
# Expected: crw-rw-rw- 1 root root 189, 1 ... /dev/bus/usb/001/002

# Verify TUN device exists
pct exec 105 -- ls -la /dev/net/tun
# Expected: crw-rw-rw- 1 root root 10, 200 ... /dev/net/tun

# Verify smart card communication
pct exec 105 -- opensc-tool -l
# Expected: Generic USB2.0-CRW [Smart Card Reader Interface]
```
