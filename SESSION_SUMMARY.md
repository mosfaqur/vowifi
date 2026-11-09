# VoWiFi Project — Session Summary & Handover Document

**Session Date:** November 9, 2026  
**Repository:** [https://github.com/mosfaqur/vowifi](https://github.com/mosfaqur/vowifi) (Branch: `main`)  
**Proxmox Host:** `192.168.1.3` (`hitesh-prox`)  
**Development Node:** `192.168.1.106` (`hi-kali-linux`)

---

## 1. Executive Summary

This session achieved major milestones across stability, calling/SMS reliability, multi-SIM provisioning, hardware templates, and automated distribution:

1. **Audio & SIP Signaling Resolution:** Solved inbound call one-way audio and 10-second carrier dropouts via RFC 3262 100rel/PRACK handling, session timer refresh, and SDP fmtp DTMF alignment.
2. **SMS Delivery Accuracy:** Fixed false-positive "SIP 405 Method Not Allowed" SMS delivery reports by handling 3GPP TS 24.011 2-byte RP-ACK submit reports.
3. **WebRTC Reverse Proxy Integration:** Enabled secure browser calling through external reverse proxies (e.g. `https://hi-vowifi.hprbd.com/`) with adaptive ICE candidate provisioning and automated WebSocket forwarding.
4. **Turnkey LXC Master Template:** Cloned CT 105 into a clean, sanitized template (CT 107, `vowifi-template`), exported the standalone `.tar.zst` archive to Proxmox local storage, and released it globally via GitHub Releases.
5. **eSIM / eUICC LPA Toolchain:** Built and integrated the standalone `lpac` v2.3.0 engine with PC/SC APDU and cURL HTTP drivers, enabling over-the-air eSIM profile downloads and profile switching directly from the WebUI.
6. **Hardware Re-enumeration & SIM Diagnosis:** Resolved USB re-enumeration shifts (`/dev/bus/usb/001/007`) and diagnosed the new Banglalink SIM rejection (`NO_APN_SUBSCRIPTION 9002`).

---

## 2. Infrastructure Inventory

| Node / VMID | IP Address | Hostname | Role / Status |
| :--- | :--- | :--- | :--- |
| **Proxmox Host** | `192.168.1.3` | `hitesh-prox` | Physical PVE 8.4 server hosting USB CCID reader (Realtek `0bda:0169`). |
| **CT 105** | `192.168.1.105` | `vowifi` | Primary live VoWiFi Gateway container. Configured with USB passthrough `dev0: /dev/bus/usb/001/007`. |
| **CT 107** | `192.168.1.107` | `vowifi-template` | Master Proxmox LXC Template (LVM-thin base image `base-107-disk-0`). Clean, unprovisioned, ready for instant linked clones. |
| **CT 106** | `192.168.1.106` | `hi-kali-linux` | Development and deployment environment holding the git repository `/root/vowifi`. |

---

## 3. Key Implementations & Resolved Issues

### 3.1. Inbound One-Way Audio & 10-Second Dropouts
* **Root Cause:**
  - Carrier sent early 183 Session Progress with `Require: 100rel`.
  - Asterisk answered with `180 Ringing` lacking `Require: 100rel` / PRACK support.
  - Carrier delayed sending `ACK` on `200 OK`, dialog remained unconfirmed, causing Asterisk to send `BYE` after 10-second transaction timeout.
  - Telephone-event payload in Asterisk 200 OK answered with `0-16`, triggering an RTP fmtp incompatibility.
* **Resolution:**
  - Applied C patch [`patches/asterisk/02_inbound_sip_dedup_and_dtmf_subset.patch`](patches/asterisk/02_inbound_sip_dedup_and_dtmf_subset.patch).
  - Deployed [`scripts/patch_inbound_audio.py`](scripts/patch_inbound_audio.py): enabled 100rel negotiation, session timers, and RTP keepalive pinholing.
  - Verified 2-way audio with zero packet loss (`rxcount=109, txcount=158, lost=0`).

### 3.2. False-Positive SMS Delivery Failures
* **Root Cause:** Carrier SMSC returned standard 3GPP TS 24.011 2-byte RP-ACK submit reports which Asterisk's SIP MESSAGE parser misclassified as invalid, triggering false-positive SIP 405 error toasts.
* **Resolution:**
  - Created [`patches/asterisk/01_rp_ack_submit_report.patch`](patches/asterisk/01_rp_ack_submit_report.patch).
  - Deployed [`scripts/patch_sms_delivery.py`](scripts/patch_sms_delivery.py) dialplan and control-plane filter.

### 3.3. WebRTC Softphone Reverse Proxy
* **Root Cause:** When accessed behind reverse proxy `https://hi-vowifi.hprbd.com/`, the browser could not connect to Asterisk's WebSocket on port 8089 because external firewalls/proxies blocked port 8089.
* **Resolution:**
  - Created [`scripts/patch_webrtc_proxy.py`](scripts/patch_webrtc_proxy.py) to multiplex both WebUI (HTTPS) and WebRTC (WSS) over the same port (8443 / 443).
  - Documented in [`docs/REVERSE_PROXY_WEBRTC_SETUP.md`](docs/REVERSE_PROXY_WEBRTC_SETUP.md).

### 3.4. Master LXC Template Creation & Distribution
* **Proxmox VM Template:** Created `vowifi-template` (VMID 107) with zero-downtime thin snapshot cloning from CT 105. Sanitized database, reset machine-id, added auto-generating SSH host keys, and removed pinned IP configurations.
* **Proxmox Appliance Archive:** Built `vowifi-gateway-clean-ubuntu-24.04.tar.zst` (2.97 GB) in `/var/lib/vz/template/cache/`.
* **GitHub Release v1.0.0:** Published at [https://github.com/mosfaqur/vowifi/releases/tag/v1.0.0](https://github.com/mosfaqur/vowifi/releases/tag/v1.0.0). Split into 3 parts (aa, ab, ac) with checksum manifest `SHA256SUMS`.
* **Turnkey Downloader:** Created [`scripts/download_lxc_template.sh`](scripts/download_lxc_template.sh) allowing 1-command template installation onto any Proxmox host.

### 3.5. eSIM / eUICC Support via `lpac`
* **Compilation:** Built `lpac` v2.3.0 standalone toolchain with PC/SC APDU driver and cURL HTTP driver.
* **Integration:** Deployed to `/root/vowifi_gateway/data/lpac/lpac`. Control plane endpoint `/api/esim/status` now reports `available: true`.
* **Installer & Documentation:** Created [`scripts/install_esim_lpac.sh`](scripts/install_esim_lpac.sh) and [`docs/ESIM_SETUP_AND_MANAGEMENT.md`](docs/ESIM_SETUP_AND_MANAGEMENT.md).

### 3.6. USB Re-enumeration & New SIM Status
* **USB Shift:** Physical unplugging re-enumerated the reader from device `004` to `007` (`/dev/bus/usb/001/007`). Updated `/etc/pve/lxc/105.conf` to match.
* **New SIM Verification:**
  - IMSI: `470039974433282`
  - ICCID: `8988039914744332821`
  - SMSC: `+88019900557`
  - PIN: Disabled (10 tries left)
  - ePDG DNS: Resolves to `116.58.207.151`
* **Carrier Rejection Cause:**
  - IKEv2 Phase 1 (`IKE_SA_INIT`) and EAP-AKA mutual authentication succeeded.
  - Carrier core network returned:  
    `[swu_ike] received ERROR Notify: NO_APN_SUBSCRIPTION (9002)`  
    `DIAMETER_ERROR_USER_NO_APN_SUBSCRIPTION`
  - **Action Required:** The user must activate VoLTE on this Banglalink line by inserting it into a phone and dialing `*121*8#` or calling customer care (121).

---

## 4. Useful Operations & Commands

### Start CT 105
```bash
# On Proxmox host (192.168.1.3):
pct start 105
```

### Check SIM Detection
```bash
# Inside CT 105:
curl -sk 'https://127.0.0.1:8443/api/sim/detect?reader_index=0'
```

### Check IMS Registration
```bash
# Inside CT 105:
docker exec vowifi-engine-1 asterisk -rx 'pjsip show registrations'
```

### Check IKEv2 Tunnel Logs
```bash
# Inside CT 105:
docker exec vowifi-engine-1 cat /run/vowifi/charon.log | tail -n 50
```

### Clone a New Instance from Template 107
```bash
# On Proxmox host (192.168.1.3):
pct clone 107 108 --hostname vowifi-sim2
pct set 108 -net0 name=eth0,bridge=vmbr0,firewall=1,gw=192.168.1.1,ip=192.168.1.108/24
pct set 108 -dev0 /dev/bus/usb/001/005,mode=0666
pct start 108
```

### Download & Install Template on Any Proxmox Server
```bash
curl -fsSL https://raw.githubusercontent.com/mosfaqur/vowifi/main/scripts/download_lxc_template.sh | bash
```

---

## 5. Pending / Next Steps for User

1. **Activate VoLTE on New SIM (`470039974433282`):**
   - Insert into a 4G handset.
   - Dial `*121*8#` to activate Banglalink VoLTE/VoWiFi.
   - Re-insert into USB reader, start CT 105 (`pct start 105`), and click **Start** in the WebUI.
2. **Multi-SIM Scaling:**
   - Plug additional USB smart card readers into host.
   - Clone CT 107 to new VMIDs (`108`, `109`, etc.) and map each reader.
