# Open-Source Sources, Specifications, and Technical Attribution

This project is built by synthesizing several specialized open-source cellular stacks, smart card middlewares, and international telecommunication standards. This document details each upstream component, its author/maintainer, licensing, and exact role in the system.

---

## 1. Upstream Open-Source Codebases

### 1.1 `vowifi_gateway` (VoCat)
* **Repository:** [https://github.com/pagecat/vowifi_gateway](https://github.com/pagecat/vowifi_gateway)
* **Maintainer:** `pagecat`
* **License:** MIT License
* **How It Was Used:**
  * Serves as the primary architectural scaffolding.
  * Provides the **FastAPI control plane** managing SIM line lifecycle and Docker engine containers.
  * Implements the **React + Vite WebUI dashboard**, browser softphone (SIP over WebSockets/WebRTC), and SMS chat interface.
  * Houses the supervisor scripts (`pin_keeper.py`, `ami_usim.py`, `render.py`, and `notify.py`) that orchestrate per-SIM instances.

### 1.2 `SWu-IKEv2`
* **Repository:** [https://github.com/fasferraz/SWu-IKEv2](https://github.com/fasferraz/SWu-IKEv2)
* **Author:** Fernando Ferraz (`fasferraz`)
* **How It Was Used:**
  * Foundational core of `swu_ike.py` (located in the engine image at `/usr/local/bin/swu_ike.py`).
  * Implements the **RFC 7296 IKEv2 state machine**, handling cryptographic exchanges (`IKE_SA_INIT`, `IKE_AUTH`) and Diffie-Hellman key derivation.
  * Implements the client side of the **3GPP SWu reference point** (3GPP TS 24.302), establishing userspace ESP packet processing across a Linux `tun` interface (`ipsec0`).
  * In this stack, it was enhanced with:
    * 3GPP notification code classification (`NO_APN_SUBSCRIPTION`, `AUTHENTICATION_FAILED`, `NETWORK_FAILURE`).
    * Backoff timer adherence (GPRS Timer 3 / TS 24.302).
    * RFC 7383 IKEv2 fragmentation support.
    * Dead Peer Detection (DPD) and NAT-T keepalive probes.

### 1.3 `sysmocom/asterisk` & `sysmocom/pjproject`
* **Repository:** [https://gitea.sysmocom.de/sysmocom/asterisk](https://gitea.sysmocom.de/sysmocom/asterisk) and [https://gitea.sysmocom.de/sysmocom/pjproject](https://gitea.sysmocom.de/sysmocom/pjproject)
* **Maintainer:** sysmocom - s.f.m.c. GmbH
* **How It Was Used:**
  * Cellular-grade Asterisk 20.7.0 fork with PJSIP 2.14.
  * Extends standard SIP with 3GPP cellular IMS capabilities:
    * **IMS-AKA Authentication:** Support for Digest-AKAv1-MD5 challenges via the Asterisk Manager Interface (AMI).
    * **P-Access-Network-Info (PANI):** Injects 3GPP cellular network headers.
    * **Cellular SMS-over-IP:** Translates between `SIP MESSAGE` payloads and 3GPP RP-DATA / TPDU SMS formats.
    * Audio codecs: AMR, AMR-WB, Opus.

### 1.4 `CryptoMobile`
* **Repository:** [https://github.com/mitshell/CryptoMobile](https://github.com/mitshell/CryptoMobile)
* **Author:** Benoit Michau (`mitshell`)
* **License:** LGPL
* **How It Was Used:**
  * Implements 3GPP cryptographic functions in pure Python / C bindings: Milenage (f1, f2, f3, f4, f5), TUAK, SNOW 3G, KASUMI, and ZUC.
  * Used inside `swu_ike.py` to derive EAP-AKA session keys from the SIM's returned Cipher Key (`CK`) and Integrity Key (`IK`):
    * `MSK` (Master Session Key)
    * `EMSK` (Extended Master Session Key)
    * `K_aut` (EAP-AKA Authentication Key)
    * `K_encr` (EAP-AKA Encryption Key)

### 1.5 `card`
* **Repository:** [https://github.com/mitshell/card](https://github.com/mitshell/card)
* **Author:** Benoit Michau (`mitshell`)
* **How It Was Used:**
  * Python abstraction layer for smart cards and SIM/USIM operations.
  * Structures and parses ISO 7816 / ETSI 102 221 Application Protocol Data Units (APDUs).
  * Specifically executes the 3GPP `AUTHENTICATE` APDU (`00 88 00 81 ...`) passing `RAND` and `AUTN` to the physical SIM card and retrieving `RES`, `CK`, and `IK`.

### 1.6 `PCSC` (pcsc-lite) & `CCID` (libccid)
* **Repository:** [https://github.com/LudovicRousseau/PCSC](https://github.com/LudovicRousseau/PCSC) and [https://github.com/LudovicRousseau/CCID](https://github.com/LudovicRousseau/CCID)
* **Maintainer:** Ludovic Rousseau
* **How It Was Used:**
  * **`pcsc-lite 2.3.3`**: Compiled from source with `-Dpolkit=false` on Ubuntu 24.04 inside LXC 105. This avoids PolicyKit permission blocks in unprivileged containers and version-locks the daemon protocol with client libraries.
  * **`libccid`**: The USB CCID IFDHandler driver enabling low-level communication with the USB smart card reader hardware.

### 1.7 `panoramisk`
* **Repository:** [https://github.com/winebarrel/panoramisk](https://github.com/winebarrel/panoramisk)
* **Author:** Yoann Roman
* **How It Was Used:**
  * Python asyncio library for Asterisk Manager Interface (AMI).
  * Used in `ami_usim.py` to listen for Asterisk IMS-AKA challenge events and dispatch them to the SIM card.

---

## 2. 3GPP & IETF Specifications Referenced

The system operates strictly according to standard cellular and internet engineering standards:

* **3GPP TS 23.402:** *Architecture enhancements for non-3GPP accesses*  
  Governs the functional architecture for untrusted non-3GPP access (VoWiFi / WLAN) interfacing with the EPC via an ePDG.
* **3GPP TS 24.302:** *Access to the 3GPP Evolved Packet Core (EPC) via non-3GPP access networks*  
  Specifies IKEv2 signaling, ePDG FQDN resolution, Identity (IDi/IDr) formats, and notification status/error codes.
* **3GPP TS 33.402:** *3GPP System Architecture Evolution (SAE); Security aspects of non-3GPP accesses*  
  Defines EAP-AKA authentication procedures, session key derivation, and IPsec ESP encapsulation.
* **3GPP TS 23.003:** *Numbering, addressing and identification*  
  Specifies the construction of:
  * ePDG FQDN: `epdg.epc.mnc<MNC>.mcc<MCC>.pub.3gppnetwork.org`
  * Root NAI: `0<IMSI>@nai.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org`
* **3GPP TS 31.102:** *Characteristics of the Universal Subscriber Identity Module (USIM) application*  
  Governs elementary files: `EF.IMSI` (`6F07`), `EF.ICCID` (`2FE2`), `EF.DIR` (`2F00`), and the `AUTHENTICATE` command APDU.
* **RFC 7296:** *Internet Key Exchange Protocol Version 2 (IKEv2)*.
* **RFC 4187:** *Extensible Authentication Protocol Method for 3rd Generation Authentication and Key Agreement (EAP-AKA)*.
* **RFC 3261 & 3GPP TS 24.229:** *Session Initiation Protocol (SIP) and IMS call control protocol*.

---

## 3. Engineering Adaptations in This Deployment

1. **Unprivileged LXC Passthrough:**
   Configured Proxmox VE 8+ native `dev0` (`/dev/bus/usb/...`) and `dev1` (`/dev/net/tun`) passthrough to allow full userspace networking and direct USB CCID access in an unprivileged container.
2. **PolicyKit Bypass:**
   Compiled `pcsc-lite 2.3.3` with `-Dpolkit=false` on Ubuntu 24.04 inside LXC 105 to eliminate PolicyKit authorization rejections in headless environments.
3. **Layered Fast-Build Architecture:**
   Created `Dockerfile.fast` to layer Python dependencies on top of `phcodercat/asterisk-vowifi:latest`, reducing the engine container build time from 20 minutes to under 30 seconds.
4. **Operator ePDG Identity Tuning:**
   Tuned `idr_mode` to `apn` (`ID_FQDN` with bare string `"ims"`), enabling compatibility with operator ePDG gateways that reject full FQDN responder identities.
