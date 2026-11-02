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

## WebRTC Voice Audio (RTP) Considerations

While SIP signaling (registration, dialing, call state) rides over the HTTPS/WSS proxy (TCP/443), **voice audio (RTP/SRTP) flows directly via UDP**:

1. **Accessing over Local LAN:**
   * If your browser is on the same local network as the VoWiFi gateway (e.g. laptop or smartphone on home/office Wi-Fi), Asterisk's built-in ICE host candidates automatically advertise the gateway's LAN IP (`192.168.1.x`).
   * Audio flows directly between browser and server without needing external port forwards.

2. **Accessing Remotely over Public Internet / Mobile Data:**
   * Standard reverse proxies and Cloudflare CDN do **not** proxy UDP traffic.
   * For remote voice calls to function outside the LAN:
     1. Forward UDP ports **10000–10059** on your WAN router to the VoWiFi host IP (`192.168.1.105`).
     2. In the WebUI, go to **Settings** → **Advertise address** and enter your router's public WAN IP or DDNS hostname.
     3. Asterisk will advertise this address in ICE candidates so external browsers can establish direct peer-to-peer SRTP audio streams.
