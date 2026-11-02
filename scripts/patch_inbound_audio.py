#!/usr/bin/env python3
"""
patch_inbound_audio.py
Idempotently applies inbound call audio and SIP 100rel / PRACK fixes:
1. extensions.conf.j2:
   - Removes premature Progress(), WaitForPrecondition(), and Ringing() in [volte_ims]
     before Dial(). This eliminates duplicate 180 Ringing responses that violate RFC 3262 §3
     and cause carrier ZTE IMS SBCs to fail to ACK the 200 OK answer.
2. pjsip.conf.j2:
   - Adds rtp_symmetric=yes, rtp_ipv6=yes (when pcscf_is_v6), and rtp_keepalive=1
     under [volte_ims] endpoint to ensure symmetric media latching on IPv6 and
     immediate RTP keepalive pinholing through carrier SBC/NAT firewalls.
3. webui/src/softphone.js & webui/dist:
   - Adds rtcpMuxPolicy: 'require' to this.session.answer() in the WebRTC softphone
     client to match modern browser WebRTC RTCP-mux requirements.
"""

import sys
import os
import re


def patch_extensions_template(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # Check for [volte_ims] block
    if "[volte_ims]" in content:
        # Remove Progress(), WaitForPrecondition(), and Ringing() before Dial
        # Target block:
        old_pattern = (
            r"(exten => _\.,1,NoOp\(Incoming call from \$\{CALLERID\(num\)\}\)\n"
            r"\s*same => n,Set\(CALLPEER=\$\{CALLERID\(num\)\}\)\n)"
            r"\s*same => n,Progress\(\)\n"
            r"(\s*same => n,Set\(FILE\(/logs/calls\.txt,,,a\)=IN call from \$\{CALLERID\(num\)\} at \$\{STRFTIME\(\$\{EPOCH\},,%Y-%m-%d %H:%M:%S\)\}\)\n"
            r"\s*same => n,TrySystem\(/usr/local/bin/notify\.py call_in \"\$\{CALLERID\(num\)\}\" &\)\n)"
            r"\s*same => n,WaitForPrecondition\(10,2000\)\n"
            r"\s*same => n,Ringing\(\)\n"
        )
        replacement = r"\1\2"
        new_content, count = re.subn(old_pattern, replacement, content)
        if count > 0:
            content = new_content
            modified = True
            print(f" [+] Removed premature Progress(), WaitForPrecondition(), Ringing() from {path}.")
        else:
            # Fallback direct replacements if slightly different whitespace
            for line in ["same => n,Progress()\n", "same => n,WaitForPrecondition(10,2000)\n", "same => n,Ringing()\n"]:
                if line in content and "[volte_ims]" in content:
                    # Only remove if it occurs in [volte_ims] context
                    parts = content.split("[volte_ims]")
                    if len(parts) == 2:
                        subparts = parts[1].split("[", 1)
                        if line in subparts[0]:
                            subparts[0] = subparts[0].replace(line, "")
                            content = parts[0] + "[volte_ims]" + "[".join(subparts)
                            modified = True
                            print(f" [+] Removed '{line.strip()}' from [volte_ims] in {path}.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {path}.")
        return True
    else:
        print(f" [.] {path} is already up-to-date.")
        return False


def patch_pjsip_template(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    if "rtp_symmetric=yes" not in content or "rtp_keepalive=1" not in content:
        target = "direct_media=no\n"
        replacement = (
            "direct_media=no\n"
            "rtp_symmetric=yes\n"
            "{% if pcscf_is_v6 %}\n"
            "rtp_ipv6=yes\n"
            "{% endif %}\n"
            "rtp_keepalive=1\n"
        )
        if target in content:
            content = content.replace(target, replacement, 1)
            modified = True
            print(f" [+] Added rtp_symmetric, rtp_ipv6, and rtp_keepalive to {path}.")

    if "100rel=peer_supported" in content:
        content = content.replace("100rel=peer_supported", "100rel=yes\ntimers=no")
        modified = True
        print(f" [+] Changed 100rel to 'yes' and added timers=no in {path}.")
    elif "100rel=yes" in content and "timers=no" not in content:
        content = content.replace("100rel=yes", "100rel=yes\ntimers=no")
        modified = True
        print(f" [+] Added timers=no to {path}.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {path}.")
        return True
    else:
        print(f" [.] {path} is already up-to-date.")
        return False


def patch_softphone_js(path):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    modified = False

    # Look for answer() { ... pcConfig: { iceServers: [] } }
    target = "this.session.answer({ mediaConstraints: { audio: true, video: false }, pcConfig: { iceServers: [] } })"
    replacement = "this.session.answer({ mediaConstraints: { audio: true, video: false }, pcConfig: { rtcpMuxPolicy: 'require', iceServers: [] } })"

    if target in content:
        content = content.replace(target, replacement, 1)
        modified = True
        print(f" [+] Added rtcpMuxPolicy: 'require' to answer() in {path}.")

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {path}.")
        return True
    else:
        print(f" [.] {path} is already up-to-date.")
        return False


def patch_webui_dist(dist_dir):
    if not os.path.exists(dist_dir):
        return False
    modified = False
    for root, _, files in os.walk(dist_dir):
        for f in files:
            if f.endswith(".js"):
                fp = os.path.join(root, f)
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    c = fh.read()
                old = 'this.session.answer({mediaConstraints:{audio:!0,video:!1},pcConfig:{iceServers:[]}})'
                new = 'this.session.answer({mediaConstraints:{audio:!0,video:!1},pcConfig:{rtcpMuxPolicy:"require",iceServers:[]}})'
                if old in c:
                    c = c.replace(old, new)
                    with open(fp, "w", encoding="utf-8") as fh:
                        fh.write(c)
                    print(f" [+] Patched compiled WebUI asset {fp}.")
                    modified = True
    return modified


def main():
    target_root = sys.argv[1] if len(sys.argv) > 1 else "/root/vowifi_gateway"

    ext_j2 = os.path.join(target_root, "engine/templates/extensions.conf.j2")
    pjsip_j2 = os.path.join(target_root, "engine/templates/pjsip.conf.j2")
    softphone_js = os.path.join(target_root, "webui/src/softphone.js")
    dist_dir = os.path.join(target_root, "webui/dist")

    patch_extensions_template(ext_j2)
    patch_pjsip_template(pjsip_j2)
    patch_softphone_js(softphone_js)
    patch_webui_dist(dist_dir)


if __name__ == "__main__":
    main()
