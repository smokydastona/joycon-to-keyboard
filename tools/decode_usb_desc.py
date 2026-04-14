#!/usr/bin/env python3
"""Extract and decode the USB configuration descriptor from the firmware binary."""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r'ci-artifacts-pid4031/esp32s3_usb_kbd.bin'

with open(path, 'rb') as f:
    data = f.read()

# Config descriptor: find any 09 02 <len_lo> <len_hi> <num_ifaces> 01 00 80 <power>
# Search for any config descriptor (bLength=9, bDescType=2, bConfigValue=1, bmAttrib=0x80)
pos = -1
for i in range(len(data) - 9):
    if data[i] == 0x09 and data[i+1] == 0x02 and data[i+5] == 0x01 and data[i+7] == 0x80:
        total_len = data[i+2] | (data[i+3] << 8)
        if 100 <= total_len <= 300:
            pos = i
            break
if pos < 0:
    print("Config descriptor not found")
    sys.exit(1)

total_len = data[pos+2] | (data[pos+3] << 8)
desc = data[pos:pos+total_len]
print(f"Found config descriptor at offset 0x{pos:x}, wTotalLength={total_len}")
print("Hex dump:")
for i in range(0, len(desc), 16):
    chunk = desc[i:i+16]
    print(f"  {i:3d}: {' '.join(f'{b:02x}' for b in chunk)}")

# Parse interfaces
print("\nParsed structure:")
i = 9  # skip config header
while i < len(desc):
    bLen = desc[i]
    bType = desc[i+1] if i+1 < len(desc) else 0
    if bLen == 0:
        print(f"  ERROR: zero-length descriptor at offset {i}")
        break
    chunk = desc[i:i+bLen]
    if bType == 0x0B:  # IAD
        print(f"  [{i:3d}] IAD: firstIface={chunk[2]}, count={chunk[3]}, class={chunk[4]:02x}, sub={chunk[5]:02x}, proto={chunk[6]:02x}")
    elif bType == 0x04:  # Interface
        print(f"  [{i:3d}] Interface: num={chunk[2]}, alt={chunk[3]}, eps={chunk[4]}, class={chunk[5]:02x}, sub={chunk[6]:02x}, proto={chunk[7]:02x}, iface_str={chunk[8]}")
    elif bType == 0x05:  # Endpoint
        ep_addr = chunk[2]
        ep_type = chunk[3] & 0x03
        types = ['Control','Isochronous','Bulk','Interrupt']
        wMaxPacket = chunk[4] | (chunk[5] << 8)
        print(f"  [{i:3d}] Endpoint: addr=0x{ep_addr:02x} ({'IN' if ep_addr & 0x80 else 'OUT'}), type={types[ep_type]}, maxPkt={wMaxPacket}, interval={chunk[6]}")
    elif bType == 0x24:  # CS_INTERFACE
        print(f"  [{i:3d}] CS_Interface (subtype={chunk[2]:02x})")
    elif bType == 0x21:  # HID descriptor
        hid_len = chunk[6] | (chunk[7] << 8)
        print(f"  [{i:3d}] HID desc: bcdHID={chunk[3]:02x}{chunk[2]:02x}, numDesc={chunk[5]}, reportLen={hid_len}")
    else:
        print(f"  [{i:3d}] Descriptor type=0x{bType:02x} len={bLen}")
    i += bLen
