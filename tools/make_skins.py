"""从 Gneko_png 生成预制皮肤。

原版 oneko 猫是**纯黑身体 + 白色描边/细节**的像素图，配色只有这两色，
所以换肤就是替换这两个颜色：黑 -> 身体色，白 -> 描边色。

少数素材（mati / pet）是白底版，会先按「与边缘连通的白色」抠掉底，
避免换肤后露出白方块。

用法：
    py -3 tools/make_skins.py
生成结果：
    skins/<皮肤名>/*.png
"""

from pathlib import Path

from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = APP_DIR / "Gneko_png"
SKINS_DIR = APP_DIR / "skins"

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# 皮肤名 -> (中文名, 身体色（替换黑）, 描边色（替换白）)
SKINS = {
    "orange":   ("橘猫", (255, 150, 62),  (255, 242, 226)),
    "gray":     ("银灰", (112, 120, 132), (245, 248, 252)),
    "pink":     ("粉猫", (255, 172, 208), (255, 246, 250)),
    "mint":     ("薄荷", (118, 216, 188), (240, 255, 250)),
    "sky":      ("天空", (92, 158, 232),  (235, 244, 255)),
    "lavender": ("香芋", (178, 158, 240), (246, 241, 255)),
    "coffee":   ("咖啡", (168, 120, 80),  (243, 228, 208)),
    "snow":     ("雪白", (246, 246, 250), (86, 92, 108)),
    "black":    ("墨黑", (32, 32, 36),    (238, 238, 244)),
}


def strip_white_backdrop(im: Image.Image) -> Image.Image:
    """仅对「白底不透明」的素材生效：抠掉与边缘连通的纯白底。"""
    if im.getpixel((0, 0))[3] < 250:
        return im          # 已经是透明底，白是描边，不能动
    w, h = im.size
    marker = (255, 0, 255, 0)
    work = im.copy()
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if work.getpixel(xy) == (255, 255, 255, 255):
            ImageDraw.floodfill(work, xy, marker, thresh=0)
    px = work.load()
    for y in range(h):
        for x in range(w):
            if px[x, y] == marker:
                px[x, y] = (0, 0, 0, 0)
    return work


def recolor(im: Image.Image, body, rim) -> Image.Image:
    """纯黑 -> 身体色，纯白 -> 描边色，其余颜色不动。"""
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[3] == 0:
                continue
            rgb = p[:3]
            if rgb == BLACK:
                px[x, y] = (body[0], body[1], body[2], p[3])
            elif rgb == WHITE:
                px[x, y] = (rim[0], rim[1], rim[2], p[3])
    return im


def main() -> None:
    if not SRC_DIR.exists():
        raise SystemExit(f"找不到素材目录: {SRC_DIR}")

    src_files = sorted(SRC_DIR.glob("*.png"))
    if not src_files:
        raise SystemExit("素材目录里没有 PNG")

    SKINS_DIR.mkdir(exist_ok=True)
    for skin, (label, body, rim) in SKINS.items():
        out_dir = SKINS_DIR / skin
        out_dir.mkdir(parents=True, exist_ok=True)
        for png in src_files:
            im = Image.open(png).convert("RGBA")
            if png.stem.lower() != "mouse":
                # 鼠标光标是细线小图，统一保持原样更好辨认
                im = strip_white_backdrop(im)
                im = recolor(im, body, rim)
            im.save(out_dir / png.name)
        print(f"[skin] {skin:9s} {label} -> {out_dir.name}  {len(src_files)} 张")

    print(f"\n共 {len(SKINS)} 套皮肤，目录: {SKINS_DIR}")
    print("启用：Gneko_config.json 里改 SKIN，或右键菜单「皮肤」直接切。")


if __name__ == "__main__":
    main()
