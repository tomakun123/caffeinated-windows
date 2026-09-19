"""
Caffeinated (Win) logo — white mug with a lightning bolt on an amber badge.

Drawn with PIL so the tray icon, window/taskbar icon, header and icon.ico all
come from one source and stay crisp from 16 px to 256 px.

    python logo.py      # regenerates icon.ico and screenshots/logo.png
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw

GRAD_TOP, GRAD_BOT = (246, 178, 107), (224, 114, 42)
EDGE               = (190, 90, 30)
WHITE              = (255, 255, 255, 255)
BOLT               = (217, 84, 30, 255)

SS = 4   # supersample factor


def _gradient_badge(px: int, radius: int, inner_edge: bool) -> Image.Image:
    grad = Image.new("RGBA", (1, px))
    for y in range(px):
        t = y / max(1, px - 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(GRAD_TOP, GRAD_BOT)) + (255,))
    grad = grad.resize((px, px))
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=255)
    badge = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    badge.paste(grad, (0, 0), mask)
    if inner_edge:
        d = ImageDraw.Draw(badge)
        w = max(1, px // 64)
        d.rounded_rectangle([w // 2, w // 2, px - 1 - w // 2, px - 1 - w // 2],
                            radius=radius, outline=EDGE + (110,), width=w)
    return badge


def make_logo(size: int) -> Image.Image:
    """Return an RGBA logo of `size`×`size` pixels."""
    small = size <= 24
    px = size * SS
    u = px / 64.0                                   # design unit: 64-unit grid

    img = _gradient_badge(px, int(14 * u), inner_edge=not small)
    d = ImageDraw.Draw(img)

    # ── mug body ───────────────────────────────────────────────────────────
    bx0, by0, bx1, by1 = 13 * u, 22 * u, 43 * u, 52 * u
    if small:                                        # bigger, simpler shapes
        bx0, by0, bx1, by1 = 10 * u, 18 * u, 44 * u, 54 * u
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(5 * u), fill=WHITE)

    # ── handle (thick arc on the right) ────────────────────────────────────
    hw = int((7 if small else 5.5) * u)
    hx0 = bx1 - 3 * u
    hy0 = by0 + (by1 - by0) * 0.18
    hy1 = by0 + (by1 - by0) * 0.72
    hx1 = hx0 + (hy1 - hy0) * 0.95
    d.arc([hx0, hy0, hx1, hy1], start=270, end=90, fill=WHITE, width=hw)

    # ── lightning bolt (cut-out colour) ────────────────────────────────────
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    bw, bh = (bx1 - bx0), (by1 - by0)
    k = 0.42 if small else 0.34                      # bolt half-width factor
    bolt = [
        (cx + bw * 0.05,  cy - bh * 0.42),
        (cx - bw * k,     cy + bh * 0.06),
        (cx - bw * 0.02,  cy + bh * 0.04),
        (cx - bw * 0.10,  cy + bh * 0.42),
        (cx + bw * k,     cy - bh * 0.08),
        (cx + bw * 0.00,  cy - bh * 0.06),
    ]
    d.polygon(bolt, fill=BOLT)

    # ── steam ──────────────────────────────────────────────────────────────
    if not small:
        # each wisp is an S: a left-bulging arc stacked on a right-bulging arc
        sw = int(2.4 * u)
        r  = 2.4 * u
        col = (255, 255, 255, 220)
        for x in (bx0 + bw * 0.28, bx0 + bw * 0.52, bx0 + bw * 0.76):
            top = by0 - 15 * u
            d.arc([x - r, top,         x + r, top + 2 * r],  start=90,  end=270, fill=col, width=sw)
            d.arc([x - r, top + 2 * r, x + r, top + 4 * r],  start=270, end=90,  fill=col, width=sw)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    root = Path(__file__).resolve().parent
    sizes = [16, 24, 32, 48, 64, 128, 256]
    renders = {s: make_logo(s) for s in sizes}
    # Pillow writes one ICO frame per size, each rendered from its own image
    renders[256].save(root / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes],
                      append_images=[renders[s] for s in sizes if s != 256])
    (root / "screenshots").mkdir(exist_ok=True)
    renders[256].save(root / "screenshots" / "logo.png")
    print("wrote icon.ico and screenshots/logo.png")


if __name__ == "__main__":
    main()
