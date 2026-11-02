# Reverse Proxy & Cloudflare WebRTC Softphone Integration Guide

## Symptom

When accessing the VoWiFi Gateway through an external domain behind a reverse proxy (e.g. Nginx, Caddy, Traefik, or Cloudflare CDN at `https://hi-vowifi.example.com/`):
* WebUI dashboard, REST API, and SMS inbox/outbox work properly.
* However, the **Softphone remains disconnected** (red indicator), unable to register or make/receive calls:
  ```text
  Status: disconnected
  ```

---

## Root Cause Analysis

WebRTC softphone operation consists of two distinct communication channels:

```mermaid
flowchart TD
    subgraph Client["Browser (WebUI Softphone)"]
        JsSIP["JsSIP Client"]
        MediaStream["WebRTC Audio Stream (SRTP)"]
    end

    subgraph Edge["Reverse Proxy / Cloudflare"]
        Proxy443["HTTPS :443 (Reverse Proxy)"]
    end

    subgraph Backend["VoWiFi Host (LXC / Server)"]
        ControlPlane["vowifi-control (:8443)\nFastAPI + WebSockets"]
        Asterisk["Asterisk 20.7.0 (res_pjsip)\nHTTP/WSS Server (:8089)\nRTP Engine (:10000-10059/udp)"]
    end

    JsSIP -->|"1. HTTPS / REST API & SMS"| Proxy443
    Proxy443 -->|"Forward to :8443"| ControlPlane

    JsSIP -.->|"2. OLD: Direct WSS to :8089 (BLOCKED by Cloudflare / Firewall)"| Asterisk
    JsSIP ==>|"3. NEW: Proxied WSS /api/instances/1/webrtc/ws over :443"| Proxy443
    Proxy443 ==>|"Forward to :8443"| ControlPlane
    ControlPlane <==|"Local WSS pipe"| Asterisk

    MediaStream -.->|"4. Direct UDP Audio (:10000-10059)"| Asterisk
```

### 1. Port 8089 Blocked by Cloudflare & Reverse Proxies
* By default, Asterisk exposes its SIP-over-WebSocket transport on port `8089` (`wss://<host>:8089/ws`).
* When accessing via an external reverse proxy (port 443), the browser attempted to connect to `wss://hi-vowifi.example.com:8089/ws`.
* **Cloudflare does not proxy port 8089** (Cloudflare HTTPS proxy only supports ports 443, 2053, 2083, 2087, 2096, and 8443). Consequently, connection attempts to port 8089 time out immediately.
* Furthermore, Asterisk uses an auto-generated self-signed TLS certificate on port 8089, which browsers reject unless manually navigated to and trusted.

---

## Resolution: Integrated WebSocket Proxy

The control plane (`vowifi-control`) now features a built-in SIP WebSocket reverse proxy:

1. **Proxy Endpoint on Standard HTTPS Port (443 / 8443):**
   * Endpoint: `GET /api/instances/{iid}/webrtc/ws` (WebSocket with `Sec-WebSocket-Protocol: sip`).
   * When a client connects, `vowifi-control` validates the instance, accepts the WebSocket, and establishes a local loopback TLS connection to Asterisk's `wss://127.0.0.1:{ws_port}/ws` inside the host.
   * SIP frames are forwarded bidirectionally with zero latency.

2. **Single-Port Domain Access:**
   * Both the WebUI and the WebRTC softphone signaling now communicate exclusively over the existing reverse proxy HTTPS port (**443**).
   * No additional firewall ports, NAT mappings, or separate TLS certificates are required for SIP signaling.

3. **Automatic URL Resolution in Softphone Client:**
   * `/api/instances/{iid}/softphone` returns `"ws_path": "/api/instances/{iid}/webrtc/ws"`.
   * `softphone.js` automatically connects to `location.host` + `ws_path`.

---

## Applying the Fix

The patch can be applied idempotently using the provided script:

```bash
python3 scripts/patch_webrtc_proxy.py /root/vowifi_gateway
systemctl restart vowifi-control
```

---

## WebRTC Voice Audio (RTP) & ICE Candidate Architecture

While SIP signaling (registration, dialing, call state) rides over the HTTPS/WSS proxy (TCP/443), **voice audio (RTP/SRTP) flows directly via UDP**:

```mermaid
flowchart LR
    subgraph LAN["Local LAN Client (e.g. 192.168.1.40 or 192.168.55.5)"]
        BrowserLAN["Browser Softphone\n(Host ICE Candidate)"]
    end

    subgraph Server["VoWiFi Server (192.168.1.105)"]
        Engine["Asterisk (vowifi-engine-1)\nHost Candidate: 192.168.1.105\nPorts: 10000-10059/udp"]
    end

    subgraph WAN["Remote WAN Client (e.g. 4G/LTE mobile)"]
        BrowserWAN["Browser Softphone\n(srflx Candidate)"]
    end

    subgraph Router["Office WAN Router (103.204.210.119)"]
        NAT["Port Forward / Relay"]
    end

    BrowserLAN <===>|"Direct LAN UDP RTP\n(No Hairpinning Needed)"| Engine
    BrowserWAN -.->|"UDP 10000-10059"| NAT
    NAT -.->|"Forward to 192.168.1.105"| Engine
```

### 1. Avoiding the STUN NAT-Loopback Trap on LAN Browsers
* When `stunaddr` is configured in Asterisk's `rtp.conf`, Asterisk gathers its reflexive WAN candidate (`103.204.210.119:100xx`).
* When a LAN browser (or a PC behind a secondary subnet like `192.168.55.0/24`) connects, ICE candidate pair prioritization ranks `srflx <-> srflx` pairs above host pairs.
* Because standard office routers do **not** support NAT loopback (hairpinning), UDP packets from the LAN directed to `103.204.210.119` are dropped by the router, resulting in total call setup failure or immediate silence.
* Furthermore, Asterisk's global `stunaddr` causes `res_rtp_asterisk` to send STUN queries on IPv6 sockets used for carrier VoLTE/VoWiFi IMS calls, throwing `Error sending STUN request: Invalid argument` and destabilizing the carrier audio leg.
* **Fix**: Asterisk `rtp.conf` relies exclusively on `[ice_host_candidates] 172.17.0.2 => 192.168.1.105,include_local_address`. The control plane provides **adaptive provisioning**:
  - **LAN requests** (`192.168.x.x`, `10.x.x.x`, `127.0.0.1`): Provision `ice_servers: []` for instant, direct LAN WebRTC.
  - **Domain/WAN requests** (`hi-vowifi.hprbd.com`): Provision STUN iceServers for public traversal.

### 2. Audio Playback Muting Race Condition (`unlockAudio`)
* In the WebUI softphone client, an autoplay unlock helper previously invoked `el.play()` on an empty audio element and registered a promise callback that executed `el.pause(); el.currentTime = 0;`.
* When an incoming or outgoing call answered and attached a live remote `MediaStream` to the audio element, the pending promise resolved and paused the audio element, silencing the call audio.
* **Fix**: `unlockAudio()` now primes an `AudioContext` without asynchronously calling `pause()` on the `<audio>` element.

### 3. Non-Blocking Audio Element Rendering
* An `<audio>` tag rendered with `style={{ display: 'none' }}` is excluded from the browser layout tree, which modern Chromium/WebKit engines can throttle or mute.
* **Fix**: The audio element is rendered with fixed off-screen CSS (`position: fixed; top: -9999px; left: -9999px; width: 1px; height: 1px; opacity: 0; pointer-events: none`).
