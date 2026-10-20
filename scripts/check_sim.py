#!/usr/bin/env python3
"""
check_sim.py
Inspects connected PC/SC smart card readers, identifies inserted SIM cards,
decodes IMSI / ICCID / ATR, and tests ePDG DNS reachability.
"""

import sys
import socket

try:
    from smartcard.System import readers
    from smartcard.util import toHexString, toBytes
except ImportError:
    print("Error: pyscard is not installed. Run: pip install pyscard")
    sys.exit(1)


def decode_imsi(raw_bytes):
    # 3GPP TS 31.102 EF_IMSI decoding
    if len(raw_bytes) < 2:
        return "N/A"
    b = raw_bytes[1:]
    digits = []
    digits.append(str(b[0] >> 4))
    for x in b[1:]:
        digits.append(str(x & 0x0F))
        digits.append(str(x >> 4))
    return "".join(digits)[:15]


def decode_iccid(raw_bytes):
    # Swap nibbles (BCD)
    digits = []
    for b in raw_bytes:
        digits.append(str(b & 0x0F))
        digits.append(str(b >> 4))
    return "".join(digits).rstrip("F")


def main():
    r_list = readers()
    if not r_list:
        print("No PC/SC smart card readers detected.")
        sys.exit(1)

    print(f"Found {len(r_list)} reader(s):")
    for i, r in enumerate(r_list):
        print(f" [{i}] {r}")

    conn = r_list[0].createConnection()
    try:
        conn.connect()
    except Exception as e:
        print(f"Failed to connect to card: {e}")
        sys.exit(1)

    atr = toHexString(conn.getATR())
    print(f"\nATR: {atr}")

    # Select MF (3F00)
    conn.transmit([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00])

    # Select and read EF_ICCID (2FE2)
    conn.transmit([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x2F, 0xE2])
    data, sw1, sw2 = conn.transmit([0x00, 0xB0, 0x00, 0x00, 0x0A])
    if sw1 == 0x90:
        iccid = decode_iccid(data)
        print(f"ICCID: {iccid}")

    # Read EF_DIR to find USIM AID
    conn.transmit([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x2F, 0x00])
    dir_data, sw1, sw2 = conn.transmit([0x00, 0xB2, 0x01, 0x04, 0x00])
    aid = None
    if sw1 == 0x90 and len(dir_data) > 4 and dir_data[0] == 0x61:
        aid_len = dir_data[3]
        aid = dir_data[4:4 + aid_len]
        print(f"USIM AID: {toHexString(aid)}")

    # Select USIM ADF and read EF_IMSI (6F07)
    if aid:
        conn.transmit([0x00, 0xA4, 0x04, 0x0C, len(aid)] + aid)
        conn.transmit([0x00, 0xA4, 0x00, 0x0C, 0x02, 0x6F, 0x07])
        imsi_data, sw1, sw2 = conn.transmit([0x00, 0xB0, 0x00, 0x00, 0x09])
        if sw1 == 0x90:
            imsi = decode_imsi(imsi_data)
            print(f"IMSI:  {imsi}")
            mcc = imsi[:3]
            mnc = imsi[3:5]
            mnc3 = f"0{mnc}" if len(mnc) == 2 else mnc
            print(f"MCC:   {mcc}")
            print(f"MNC:   {mnc}")

            epdg_fqdn = f"epdg.epc.mnc{mnc3}.mcc{mcc}.pub.3gppnetwork.org"
            print(f"\nResolving ePDG FQDN: {epdg_fqdn}...")
            try:
                ip = socket.gethostbyname(epdg_fqdn)
                print(f"Resolved ePDG IP: {ip}")
            except Exception as e:
                print(f"ePDG DNS resolution failed: {e}")


if __name__ == "__main__":
    main()
