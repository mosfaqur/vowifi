#!/usr/bin/env python3
"""
patch_swu_ike.py
Idempotently applies compatibility patches to upstream swu_ike.py:
1. Sets multiprocessing start method to 'fork' (prevents Python 3.14 forkserver unpicklable object crash).
2. Cleans up DHParameterNumbers and private key references after key exchange.
3. Fixes IPv6 link-local address generation to prevent double-colon (fe80:::1) syntax errors.
"""

import sys
import os

def patch_file(path):
    if not os.path.exists(path):
        print(f"Error: {path} not found.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    modified = False

    # 1. Multiprocessing start method
    if "multiprocessing.set_start_method" not in content:
        orig = "import multiprocessing\n"
        replacement = (
            "import multiprocessing\n"
            "try:\n"
            '    multiprocessing.set_start_method("fork", force=True)\n'
            "except Exception:\n"
            "    pass\n"
        )
        if orig in content:
            content = content.replace(orig, replacement, 1)
            modified = True
            print(" [+] Applied multiprocessing fork fix.")

    # 2. DH parameter cleanup
    if "self.pn = None" not in content:
        orig = "self.dh_shared_key = self.dh_private_key.exchange(peer_public_key)\n"
        replacement = (
            "self.dh_shared_key = self.dh_private_key.exchange(peer_public_key)\n"
            "        self.pn = None\n"
            "        self.dh_private_key = None\n"
        )
        if orig in content:
            content = content.replace(orig, replacement, 1)
            modified = True
            print(" [+] Applied DH parameter cleanup fix.")

    # 3. IPv6 link-local address derivation fix
    if "int(_ip6) & 0xFFFFFFFFFFFFFFFF" not in content:
        target = "ipv6_address_identifier = 'fe80::' + ':'.join(self.ipv6_address_list[0].split(':')[4:8])"
        replacement = (
            "try:\n"
            "                _ip6 = ipaddress.IPv6Address(self.ipv6_address_list[0])\n"
            "                ipv6_address_identifier = str(ipaddress.IPv6Address(0xFE800000000000000000000000000000 | (int(_ip6) & 0xFFFFFFFFFFFFFFFF)))\n"
            "            except Exception:\n"
            "                ipv6_address_identifier = 'fe80::1'"
        )
        # Check if the split-line exists
        for line in content.splitlines():
            if "split(':')[4:8]" in line and "fe80::" in line:
                content = content.replace(line.strip(), replacement.strip(), 1)
                modified = True
                print(" [+] Applied IPv6 link-local address generation fix.")
                break

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully patched {path}.")
    else:
        print(f"{path} is already up-to-date.")

if __name__ == "__main__":
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/root/vowifi_gateway/engine/swu_ike.py"
    patch_file(target_path)
