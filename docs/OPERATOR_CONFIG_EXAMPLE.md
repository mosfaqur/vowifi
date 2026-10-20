# Operator Configuration Guide & Carrier Profiles

This document details general network parameters, DNS resolution rules, APN definitions, and activation procedures for deploying VoWiFi on a mobile network operator.

---

## 1. Operator Identifiers & Network Parameters

In 3GPP cellular networks, each operator is identified by a Mobile Country Code (MCC) and Mobile Network Code (MNC):

| Parameter | Example / Standard Format | Description |
| :--- | :--- | :--- |
| **Mobile Country Code (MCC)** | `<MCC>` (e.g. `001`) | 3-digit country identifier |
| **Mobile Network Code (MNC)** | `<MNC>` (e.g. `01`) | 2- or 3-digit operator identifier |
| **VoWiFi ePDG FQDN** | `epdg.epc.mnc<MNC3>.mcc<MCC3>.pub.3gppnetwork.org` | Standard 3GPP TS 23.003 format |
| **ePDG Public IP** | Resolved via DNS | IP address of the carrier's ePDG gateway |
| **VoLTE / VoWiFi APN** | `ims` | Dedicated IMS APN for carrier voice/SMS |
| **Standard Internet APN** | `internet` / `<carrier_data_apn>` | General mobile data APN |
| **SMS Center (SMSC)** | Read from SIM EF.SMSP | Carrier SMS service center number |

> [!NOTE]
> If the MNC is 2 digits long, 3GPP TS 23.003 mandates that it must be padded with a leading zero to 3 digits (e.g. MNC `01` becomes `mnc001`).

---

## 2. ePDG DNS Discovery & Verification

In accordance with 3GPP TS 23.003 and TS 24.302, modern UEs construct the ePDG domain name using the SIM's MCC and MNC:

```bash
# Example DNS lookup for operator with MCC=001, MNC=01:
dig +short epdg.epc.mnc001.mcc001.pub.3gppnetwork.org
```

Testing port connectivity to the discovered ePDG IP:
```bash
# Verify UDP 500 (IKE) / 4500 (NAT-T) reachability
nc -z -v -u <EPDG_IP> 500
nc -z -v -u <EPDG_IP> 4500
```

---

## 3. Protocol Tuning & Compatibility

### 3.1 Responder Identity (`IDr`)
In 3GPP TS 24.302, a UE can submit its target APN in `IKE_AUTH` as:
1. **Bare APN (`idr_mode: apn`):** The string `"ims"`.
2. **Operator APN-FQDN (`idr_mode: fqdn`):** `ims.apn.epc.mnc<MNC3>.mcc<MCC3>.pub.3gppnetwork.org`.

> [!TIP]
> Most modern carrier ePDGs require **`idr_mode: apn`**.  
> If an ePDG rejects `IKE_AUTH (1)` with `AUTHENTICATION_FAILED (24)` before issuing an EAP-AKA challenge, verify that `idr_mode` is set to `apn` rather than `fqdn`.

### 3.2 Configuration Request (`CP`) Mode
Carrier IMS packet data networks (PDN) may offer IPv6, IPv4, or dual-stack addressing:
```yaml
cp_mode: auto
```
Setting `cp_mode: auto` enables the discovery ladder (`v6, dual, v4`), allowing the client to accept whatever addressing family the operator's PGW assigns.

---

## 4. Subscription & Provisioning Checklist

If the IKEv2 trace shows:
```text
Notify: NO_APN_SUBSCRIPTION (9002) - DIAMETER_ERROR_USER_NO_APN_SUBSCRIPTION
```
This error indicates that while the physical SIM card's cryptographic authentication succeeded (EAP-AKA verified), the operator's Home Subscriber Server (HSS) does not have the **`ims` APN** provisioned for this subscriber.

### Steps to Resolve:
1. Confirm with your mobile operator that **VoLTE and VoWiFi (Wi-Fi Calling)** services are enabled on the subscription.
2. Ensure the SIM is a 4G USIM or 5G ISIM compatible with the operator's IMS core.
3. Once active on the carrier side, restart the instance from the WebUI or CLI to complete tunnel establishment and SIP registration.
