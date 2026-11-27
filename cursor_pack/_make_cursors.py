# -*- coding: utf-8 -*-
"""
把 neko_png 目录下的像素猫 PNG 打包成 Windows 光标方案：
- 单帧  -> .cur
- 帧对  -> .ani（动画光标）
白底素材（pet / mati2 / mati3）从边缘洪泛去白底，保留猫身内部白色。
"""
import os
import struct
import zlib
from collections import deque
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = BASE
OUT = os.path.join(BASE, "光标包")
EXTRAS = os.path.join(OUT, "备用方向")
os.makedirs(EXTRAS, exist_ok=True)

SIZE = 32
FRAME_RATE = 12  # ANI 帧间隔，单位 1/60 秒（约 200ms）


def load_rgba(name: str) -> Image.Image:
    im = Image.open(os.path.join(SRC, name + ".png")).convert("RGBA")
    px = im.load()
    # 若四角为不透明白底，做边缘洪泛去白
    corner = px[0, 0]
    if corner[3] == 255 and corner[:3] == (255, 255, 255):
        w, h = im.size
        visited = [[False] * w for _ in range(h)]
        q = deque()
        for x in range(w):
            q.append((x, 0)); q.append((x, h - 1))
        for y in range(h):
            q.append((0, y)); q.append((w - 1, y))
        def is_bg(p):
            r, g, b, a = p
            return a == 255 and r >= 235 and g >= 235 and b >= 235
        while q:
            x, y = q.popleft()
            if x < 0 or y < 0 or x >= w or y >= h or visited[y][x]:
                continue
            visited[y][x] = True
            if not is_bg(px[x, y]):
                continue
            r, g, b, _ = px[x, y]
            # 近白边缘给半透明过渡
            alpha = 0 if min(r, g, b) >= 235 else 128
            px[x, y] = (255, 255, 255, alpha)
            q.extend([(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)])
    return im


def bmp_dib(im: Image.Image) -> bytes:
    """生成 32bpp BGRA 的 BMP DIB（XOR 位图 + 1bpp AND 掩码），光标/动画光标通用。"""
    w, h = im.size
    px = im.load()

    # XOR 位图：BGRA，自下而上
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))

    # AND 掩码：1bpp，每行 4 字节对齐，自下而上；不透明=0，透明=1
    row_bytes = ((w + 31) // 32) * 4
    andmask = bytearray(row_bytes * h)
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                andmask[(h - 1 - y) * row_bytes + x // 8] |= 0x80 >> (x % 8)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        w, 2 * h,    # biWidth, biHeight (XOR + AND 掩码)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression
        0,           # biSizeImage
        0, 0,        # biXPelsPerMeter, biYPelsPerMeter
        0, 0,        # biClrUsed, biClrImportant
    )
    return bytes(header) + bytes(xor) + bytes(andmask)


def make_cur(im: Image.Image, hotx: int, hoty: int) -> bytes:
    """封装单个 CUR（BMP DIB，兼容静态光标与 ANI 帧）。"""
    data = bmp_dib(im)
    out = struct.pack("<HHH", 0, 2, 1)  # reserved, type=cursor, count=1
    out += struct.pack(
        "<BBBBHHII",
        SIZE, SIZE, 0, 0,
        hotx, hoty,
        len(data), 22,
    )
    out += data
    return out


def chunk(tag: bytes, data: bytes) -> bytes:
    pad = b"\x00" if len(data) % 2 else b""
    return tag + struct.pack("<I", len(data)) + data + pad


def make_ani(frames: list[Image.Image], hotx: int, hoty: int,
             rate: int = FRAME_RATE) -> bytes:
    curs = [make_cur(im, hotx, hoty) for im in frames]
    n = len(curs)

    # anih 头（flags=1 帧为图标/CUR；cx/cy=0 从帧取尺寸）
    anih = struct.pack(
        "<IIIIIIIII",
        36,          # cbSizeOfHeader
        n,           # cFrames
        n,           # cSteps
        0, 0,        # cx, cy
        32,          # cBitCount
        1,           # cPlanes
        rate,        # jifRate (1/60 s)
        1,           # flags (ACON_FLAG_ICON)
    )

    # fram LIST（LIST 长度含 4 字节的 'fram' 类型标识）
    fram = b""
    for c in curs:
        fram += chunk(b"icon", c)
    body = (chunk(b"anih", anih) + b"LIST"
            + struct.pack("<I", len(fram) + 4) + b"fram" + fram)

    riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + body
    return riff


# ---------------------------------------------------------------------------
# 主方案：标准 Windows 光标用途 -> (帧列表, 热点)
# 热点为鼠标单击生效点（鼻尖 / 头部）。
MAIN = {
    "Arrow":        (["awake"],                 (16, 13), "cur"),   # 正常选择
    "Help":         (["pet"],                    (16, 15), "cur"),   # 帮助选择
    "AppStarting":  (["sleep1", "sleep2"],      (12, 16), "ani"),   # 后台运行
    "Wait":         (["mati2", "mati3"],         (15, 12), "ani"),   # 忙
    "Hand":         (["jare2"],                  (13, 8),  "cur"),   # 链接选择
    "NWPen":        (["kaki1", "kaki2"],          (4, 10), "ani"),   # 手写
    "SizeWE":       (["left1", "left2"],         (4, 10), "ani"),   # 水平调整
    "SizeNS":       (["up1", "up2"],            (15, 3),  "ani"),   # 垂直调整
    "SizeNWSE":     (["upleft1", "upleft2"],      (3, 4),  "ani"),   # 左上-右下
    "SizeNESW":     (["upright1", "upright2"],  (28, 4),  "ani"),   # 右上-左下
    "SizeAll":      (["ltogi1", "ltogi2"],       (4, 5),  "ani"),   # 移动
    "No":           (["no"],                     (4, 18), "cur"),   # 不可用
    "IBeam":        (["text"],                   (16, 13), "cur"),   # 文本选择
}

# 备用方向素材：同样打包，保留原名
EXTRAS_MAP = {
    "right":    (["right1", "right2"],           (28, 10)),
    "down":     (["down1", "down2"],            (15, 26)),
    "dwleft":   (["dwleft1", "dwleft2"],        (3, 17)),
    "dwright":  (["dwright1", "dwright2"],      (29, 17)),
    "rtogi":    (["rtogi1", "rtogi2"],          (28, 5)),
    "utogi":    (["utogi1", "utogi2"],          (15, 2)),
    "dtogi":    (["dtogi1", "dtogi2"],          (15, 28)),
}


def main():
    produced = []
    for name, (frames, hot, kind) in MAIN.items():
        ims = [load_rgba(f) for f in frames]
        hotx, hoty = hot
        if kind == "cur":
            data = make_cur(ims[0], hotx, hoty)
            path = os.path.join(OUT, name + ".cur")
        else:
            data = make_ani(ims, hotx, hoty)
            path = os.path.join(OUT, name + ".ani")
        with open(path, "wb") as f:
            f.write(data)
        produced.append(os.path.basename(path))

    for name, (frames, hot) in EXTRAS_MAP.items():
        ims = [load_rgba(f) for f in frames]
        hotx, hoty = hot
        data = make_ani(ims, hotx, hoty)
        path = os.path.join(EXTRAS, name + ".ani")
        with open(path, "wb") as f:
            f.write(data)
        produced.append(os.path.relpath(path, OUT))

    print("生成完成：")
    for p in produced:
        print("  -", p)


if __name__ == "__main__":
    main()
