import sys
from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (7, 87, 255, 255)
NAVY = (7, 24, 77, 255)
PAPER = (255, 255, 255, 255)
FOLD = (203, 216, 232, 255)
LINES = (71, 97, 143, 255)
GREEN = (11, 122, 59, 255)

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
BADGE_MIN_SIZE = 32
DETAIL_MIN_SIZE = 48
SUPERSAMPLE = 8


def render(size: int) -> Image.Image:
    detailed = size >= DETAIL_MIN_SIZE
    badge = size >= BADGE_MIN_SIZE
    s = size * SUPERSAMPLE
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    u = s / 64
    d.rounded_rectangle([1 * u, 1 * u, 63 * u, 63 * u], radius=14 * u, fill=ACCENT)
    left, top, right, bottom, fold = 17 * u, 9 * u, 47 * u, 45 * u, 10 * u
    d.polygon(
        [(left, top), (right - fold, top), (right, top + fold), (right, bottom), (left, bottom)],
        fill=PAPER,
    )
    d.polygon([(right - fold, top), (right - fold, top + fold), (right, top + fold)], fill=FOLD)
    if detailed:
        for i, width in enumerate((20, 24, 16)):
            y = top + 17 * u + i * 6 * u
            d.rounded_rectangle(
                [left + 5 * u, y, left + (5 + width) * u, y + 2.6 * u], radius=1.3 * u, fill=LINES
            )
    else:
        d.rounded_rectangle(
            [left + 5 * u, top + 18 * u, right - 5 * u, top + 22 * u], radius=2 * u, fill=LINES
        )
    tray_top = 41 * u
    d.rounded_rectangle([10 * u, tray_top, 54 * u, 55 * u], radius=4 * u, fill=NAVY)
    d.rounded_rectangle([18 * u, tray_top, 46 * u, tray_top + 5 * u], radius=2.5 * u, fill=ACCENT)
    if badge:
        cx, cy, r = 47 * u, 13 * u, 9 * u
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN, outline=PAPER, width=int(2 * u))
        d.line(
            [
                (cx - 4.2 * u, cy + 0.2 * u),
                (cx - 1 * u, cy + 3.4 * u),
                (cx + 4.6 * u, cy - 3.4 * u),
            ],
            fill=PAPER,
            width=max(int(2.6 * u), 1),
            joint="curve",
        )
    return image.resize((size, size), Image.LANCZOS)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: make_icon.py OUTPUT_DIR", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    frames = [render(size) for size in SIZES]
    frames[-1].save(
        out / "belegdock.ico",
        sizes=[(size, size) for size in SIZES],
        append_images=frames[:-1],
    )
    frames[-1].save(out / "belegdock.png", optimize=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
