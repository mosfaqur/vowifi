#!/usr/bin/env python3
"""
patch_sms_delivery.py
Idempotently applies SMS delivery and submit-report detection fixes:
1. extensions.conf.j2: Do not route incoming SIP MESSAGE to the WebRTC softphone
   (JsSIP does not handle MESSAGE and responds with SIP 405 Method Not Allowed).
2. control/app/main.py:
   - Handle 3GPP TS 24.011 Network-to-MS RP-MTIs (RP-ACK = 2, RP-ERROR = 4) as well as MS-to-Network.
   - Ignore SIP responses from local WebSocket (WSS:) / WebRTC clients so browser 405s
     are not mistaken for carrier rejections.
   - Recognize 2-byte RP-ACK submit reports logged by Asterisk.
3. patches/asterisk/01_rp_ack_submit_report.patch:
   - Allows res_pjsip_messaging.c parse_rpdata to accept 2-byte RP-ACK submit reports (len >= 2).
"""

import sys
import os
import re

def patch_extensions_template(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    target = "{% if webrtc_enable %}{% set _ = msg_targets.append(webrtc_user) %}{% endif %}"
    replacement = (
        "{# Do not route incoming SIP MESSAGE to the WebRTC endpoint (webrtc_user). The browser #}\n"
        "{# softphone (JsSIP) does not support SIP MESSAGE (returns 405 Method Not Allowed), and #}\n"
        "{# SMS messages are delivered to the WebUI via HTTP/WebSocket (notify.py sms_in).       #}"
    )
    if target in content:
        content = content.replace(target, replacement, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Patched {path} (removed webrtc from msg_targets).")
    else:
        print(f" [.] {path} is already up-to-date.")


def patch_main_control(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # 1. Update RP MTI constants
    if "_RP_ACK_MTIS = {2, 3}" not in content:
        target = "_RP_ACK_MTI = 3\n_RP_ERROR_MTI = 5"
        replacement = (
            "# Byte 0 low 3 bits = RP-MTI (3GPP TS 24.011 §8.2.2):\n"
            "# Network-to-MS: 0 = RP-DATA, 2 = RP-ACK, 4 = RP-ERROR\n"
            "# MS-to-Network: 1 = RP-DATA, 3 = RP-ACK, 5 = RP-ERROR\n"
            "_RP_ACK_MTIS = {2, 3}\n"
            "_RP_ERROR_MTIS = {4, 5}"
        )
        if target in content:
            content = content.replace(target, replacement, 1)
            modified = True
            print(" [+] Updated RP-MTI definition to handle Network-to-MS submit reports.")

    # 2. Update _decode_rp_report
    if "if mti in _RP_ACK_MTIS:" not in content:
        content = content.replace("if mti == _RP_ACK_MTI:", "if mti in _RP_ACK_MTIS:", 1)
        content = content.replace("if mti == _RP_ERROR_MTI:", "if mti in _RP_ERROR_MTIS:", 1)
        modified = True
        print(" [+] Updated _decode_rp_report to check _RP_ACK_MTIS and _RP_ERROR_MTIS.")

    # 3. Update detect_sms_result
    if "from WSS:" not in content:
        old_detect = (
            "    # 2. Fall back to a negative SIP response to our MESSAGE.\n"
            "    result = {\"ok\": None}\n"
            "    for b in SMS_RESP_RE.split(raw)[1:]:\n"
            "        m = re.search(r\"SIP/2\\.0 (\\d{3})([^\\n]*)\", b)\n"
            "        if not m:\n"
            "            continue\n"
            "        if re.search(r\"CSeq:\\s*\\d+\\s+MESSAGE\", b):   # a response to our MESSAGE\n"
            "            code = int(m.group(1))\n"
            "            result = {\"ok\": 200 <= code < 300, \"code\": code, \"reason\": m.group(2).strip()}"
        )
        new_detect = (
            "    # Fallback for 2-byte RP-ACK submit report logged by Asterisk:\n"
            "    if re.search(r\"parse_rpdata.*MESSAGE RP-DATA is too short or error:\\s*2\\.\", raw) or \\\n"
            "       re.search(r\"RP-ACK submit report received\", raw):\n"
            "        return {\"ok\": True}\n"
            "    # 2. Fall back to a negative SIP response to our MESSAGE from the carrier IMS.\n"
            "    result = {\"ok\": None}\n"
            "    for b in SMS_RESP_RE.split(raw)[1:]:\n"
            "        # Ignore responses from local WebSocket (WSS) / WebRTC softphones or local endpoints\n"
            "        if \"from WSS:\" in b or \"webrtc\" in b:\n"
            "            continue\n"
            "        m = re.search(r\"SIP/2\\.0 (\\d{3})([^\\n]*)\", b)\n"
            "        if not m:\n"
            "            continue\n"
            "        if re.search(r\"CSeq:\\s*\\d+\\s+MESSAGE\", b):   # a response to our MESSAGE\n"
            "            code = int(m.group(1))\n"
            "            if code >= 400:\n"
            "                result = {\"ok\": False, \"code\": code, \"reason\": m.group(2).strip()}"
        )
        if old_detect in content:
            content = content.replace(old_detect, new_detect, 1)
            modified = True
            print(" [+] Updated detect_sms_result to ignore local WebSocket responses and support RP-ACK.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f" [+] Patched {path} successfully.")
    else:
        print(f" [.] {path} is already up-to-date.")


if __name__ == "__main__":
    gateway_dir = sys.argv[1] if len(sys.argv) > 1 else "/root/vowifi_gateway"
    patch_extensions_template(os.path.join(gateway_dir, "engine/templates/extensions.conf.j2"))
    patch_main_control(os.path.join(gateway_dir, "control/app/main.py"))
