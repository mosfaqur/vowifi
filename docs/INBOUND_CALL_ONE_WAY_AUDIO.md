# Inbound Call One-Way Audio & 10-Second Dropped Call Resolution

## Symptom

When receiving an inbound call to the VoWiFi Gateway instance:
* The mobile caller hears the WebUI user's microphone loud and clear.
* The WebUI user in the browser hears **complete silence** (0 audio received from the caller).
* Exactly 10 seconds after answering, the call abruptly disconnects with the carrier sending a `BYE` request containing:
  ```text
  X-ZTE-Cause: "PSS-10.4.0x8E000214"
  ```
* In contrast, outbound calls placed from the WebUI softphone operate with full bidirectional audio.

---

## Root Cause Analysis

Diagnostic log traces comparing outbound vs inbound call handling revealed two distinct issues interacting simultaneously:

1. **RFC 3262 §3 Violation (Provisional Response Glare / Missing SIP ACK)**
2. **Missing Endpoint RTP IPv6 Latching & Keepalive Pinholing (Media Inactivity Dropped Call)**

---

### 1. Inbound SIP Signaling Glare (RFC 3262 §3 Violation)

In outbound calls, the carrier requires preconditions (`Require: 100rel,precondition`), where Asterisk initiates `PRACK` and `UPDATE` cycles cleanly.

In inbound calls, the carrier's ZTE IMS core sends an INVITE with full SDP without preconditions. However, the default dialplan template executed:

```ini
[volte_ims]
exten => _.,1,NoOp(Incoming call from ${CALLERID(num)})
same => n,Set(CALLPEER=${CALLERID(num)})
same => n,Progress()                 ; <-- Premature early media provisional response
same => n,Set(...)
same => n,TrySystem(...)
same => n,WaitForPrecondition(10,2000); <-- Waits for non-existent preconditions
same => n,Ringing()                  ; <-- Second provisional response sent immediately!
same => n,Dial(PJSIP/webrtc,60)
```

#### What Happened on the Wire:
```mermaid
sequenceDiagram
    autonumber
    participant Carrier as Carrier ZTE IMS SBC
    participant Ast as Asterisk (volte_ims)
    participant Browser as WebRTC Softphone (webrtc)

    Carrier->>Ast: SIP INVITE (with SDP, Supported: 100rel)
    Ast-->>Carrier: SIP 180 Ringing (RSeq: 28711, Require: 100rel) [from Progress()]
    Ast-->>Carrier: SIP 180 Ringing (RSeq: 28712, Require: 100rel) [from Ringing()]
    Note over Ast,Carrier: RFC 3262 §3 VIOLATION:<br/>Asterisk sent 2nd provisional response<br/>before receiving 200 OK for 1st PRACK!
    Carrier->>Ast: PRACK (RSeq: 28711)
    Ast-->>Carrier: 200 OK (to PRACK 28711)
    Note over Browser: User answers in WebUI
    Browser->>Ast: 200 OK (answer)
    Ast-->>Carrier: SIP 200 OK (with SDP)
    Note over Carrier: Carrier IMS SBC dialog state is broken;<br/>never transmits CSeq: 1000 ACK!
    Ast-->>Carrier: Retransmit 200 OK (T=2s, 6s, 10s...)
    Note over Carrier: Media Inactivity Timer (10s) expires
    Carrier->>Ast: SIP BYE (X-ZTE-Cause: "PSS-10.4.0x8E000214")
```

Because Asterisk sent the second `180 Ringing` (RSeq 28712) while the carrier's `PRACK` for RSeq 28711 was in flight, the carrier SBC's dialog state machine became desynchronized. As a result, the carrier **never acknowledged the final `200 OK` answer**.

---

### 2. Missing RTP IPv6 Sockets & Keepalive Pinholing

Even while SIP retransmissions occurred, Asterisk was completely unable to receive or establish media with the carrier's Media Gateway (MGW):

* The Asterisk endpoint `[volte_ims]` was configured with:
  ```ini
  rtp_ipv6 = false
  rtp_symmetric = false
  rtp_keepalive = 0
  ```
* For VoWiFi traffic running through an IPv6 IPsec tunnel, the carrier's MGW (e.g., `2403:b400:10:4:0:8000:3:xxxx`) is located behind stateful NAT and telecom carrier firewalls.
* The carrier's MGW requires the User Equipment (UE) to stream RTP first or send periodic RTP keepalive packets to pinhole the firewall and symmetrically latch the UE port.
* Because `rtp_keepalive` was `0` and `rtp_ipv6` was disabled on the endpoint, Asterisk sent 0 initial packets towards the carrier MGW.
* Asterisk logged `lost: 1.000000000` (100% packet loss / 0 incoming packets received from carrier), while WebRTC sent 379+ packets to Asterisk.
* After exactly 10 seconds of media silence, the carrier ZTE PSS Media Inactivity Detector triggered and forcefully tore down the session (`PSS-10.4.0x8E000214`).

---

## Solution & Implementation

### 1. Dialplan Optimization (`extensions.conf.j2`)

Eliminated `Progress()`, `WaitForPrecondition()`, and `Ringing()` before `Dial()`. Asterisk cleanly invokes `Dial(PJSIP/webrtc,60)`:
* When the WebRTC client begins alerting, Asterisk issues **exactly one** `180 Ringing` with `Require: 100rel`.
* When the PRACK arrives, Asterisk replies `200 OK`.
* When the user clicks Answer, Asterisk sends `200 OK` with SDP, and the carrier responds with `ACK`.

```ini
[volte_ims]
exten => _.,1,NoOp(Incoming call from ${CALLERID(num)})
same => n,Set(CALLPEER=${CALLERID(num)})
same => n,Set(FILE(/logs/calls.txt,,,a)=IN call from ${CALLERID(num)} at ${STRFTIME(${EPOCH},,%Y-%m-%d %H:%M:%S)})
same => n,TrySystem(/usr/local/bin/notify.py call_in "${CALLERID(num)}" &)
{% if dialstr %}
same => n,Dial({{ dialstr }},60)
{% else %}
same => n,Answer()
same => n,Wait(30)
{% endif %}
same => n,Hangup()
```

### 2. PJSIP Endpoint Symmetric RTP & Keepalive (`pjsip.conf.j2`)

Configured symmetric RTP, IPv6 media socket binding, and aggressive RTP keepalives on `[volte_ims]`:

```jinja2
[volte_ims]
type=endpoint
...
rtp_symmetric=yes
{% if pcscf_is_v6 %}
rtp_ipv6=yes
{% endif %}
rtp_keepalive=1
```

* `rtp_symmetric=yes`: Latch symmetrically onto incoming RTP from the carrier MGW's dynamic port.
* `rtp_ipv6=yes`: Explicitly bind IPv6 media sockets when connecting over an IPv6 IMS P-CSCF.
* `rtp_keepalive=1`: Immediately sends RTP keepalive packets every second from Asterisk to the carrier MGW, keeping carrier firewalls open and triggering the MGW to route downlink audio to Asterisk.

### 3. WebRTC Softphone RTCP-Mux Enforcement (`softphone.js`)

Updated `answer()` in `softphone.js` and the bundled asset to enforce `rtcpMuxPolicy: 'require'`:

```javascript
  answer() {
    if (this.session) {
      this.session.answer({
        mediaConstraints: { audio: true, video: false },
        pcConfig: { rtcpMuxPolicy: 'require', iceServers: [] }
      })
    }
  }
```

---

## Automated Fix Script

An idempotent script `scripts/patch_inbound_audio.py` is included to apply these fixes across templates, container environments, and web assets:

```bash
python3 scripts/patch_inbound_audio.py /root/vowifi_gateway
```
