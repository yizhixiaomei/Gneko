"""把几张素材拼成 README 用的预览图：python tools/make_preview.py"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "Gneko_png"
OUT = ROOT / "docs" / "preview.png"

FRAMES = ["awake.png", "up1.png", "right1.png", "dwleft1.png", "kaki1.png", "pet.png", "mouse.png"]
SCALE = 4
PAD = 10
BG = (24, 24, 34, 255)


def main() -> None:
    tiles = []
    for name in FRAMES:
        p = SRC / name
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA")
        im = im.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)
        tiles.append(im)

    if not tiles:
        raise SystemExit("没有找到素材")

    cell_w = max(t.width for t in tiles) + PAD * 2
    cell_h = max(t.height for t in tiles) + PAD * 2
    out = Image.new("RGBA", (cell_w * len(tiles), cell_h), BG)
    for i, t in enumerate(tiles):
        x = i * cell_w + (cell_w - t.width) // 2
        y = (cell_h - t.height) // 2
        out.alpha_composite(t, (x, y))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
