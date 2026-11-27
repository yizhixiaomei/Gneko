# -*- coding: utf-8 -*-
import struct, os, glob

OUT = r"D:\Desktop\neko\neko_png\光标包"

def parse_cur(data):
    _, _, count = struct.unpack("<HHH", data[:6])
    out = []
    for i in range(count):
        w, h, cc, res, hx, hy, size, off = struct.unpack(
            "<BBBBHHII", data[6 + i*16:22 + i*16])
        out.append((w, h, hx, hy, size, off))
    return out

def check_cur(data, label):
    e = parse_cur(data)[0]
    w, h, hx, hy, size, off = e
    dib = data[off:off + size]
    biSize, bw, bh2 = struct.unpack("<Iii", dib[:12])
    assert biSize == 40, f"{label}: 非 BMP DIB 头"
    assert bw == w and bh2 == 2 * h, f"{label}: DIB 尺寸不符"
    print(f"{label:22s} CUR hot=({hx},{hy}) img={w}x{h} bytes={len(data)}")

def check_ani(data, label):
    assert data[:4] == b"RIFF" and data[8:12] == b"ACON"
    pos, frames, rate, n = 12, 0, None, 0
    while pos + 8 <= len(data):
        tag = data[pos:pos+4]
        sz = struct.unpack("<I", data[pos+4:pos+8])[0]
        if tag == b"anih":
            v = struct.unpack("<9I", data[pos+8:pos+44])
            rate, n = v[7], v[1]
        elif tag == b"LIST":
            sp = pos + 12
            end = pos + 8 + sz
            while sp + 8 <= end:
                t = data[sp:sp+4]
                s = struct.unpack("<I", data[sp+4:sp+8])[0]
                if t == b"icon":
                    frames += 1
                    check_cur(data[sp+8:sp+8+s], "  └ frame")
                sp += 8 + s + (s % 2)
        pos += 8 + sz + (sz % 2)
    assert frames == n, f"{label}: 帧数不符 anih={n} actual={frames}"
    print(f"{label:22s} ANI frames={frames} rate={rate} bytes={len(data)}")

for p in sorted(glob.glob(OUT + r"\**\*", recursive=True)):
    if not os.path.isfile(p): continue
    data = open(p, "rb").read()
    rel = os.path.relpath(p, OUT)
    if p.lower().endswith(".cur"):
        check_cur(data, rel)
    elif p.lower().endswith(".ani"):
        check_ani(data, rel)
print("\n全部校验通过。")
