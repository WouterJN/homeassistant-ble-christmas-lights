"""Rasterise the integration icon.

A string of warm white lights wound around a Christmas tree, with a star on
top and a small Bluetooth rune in the corner.

Drawn with Pillow at 4x and downsampled, so regenerating the artwork needs no
SVG engine.

    python assets/render_logo.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BACKGROUND_TOP = (14, 40, 30)
BACKGROUND_BOTTOM = (8, 22, 18)
WIRE = (48, 104, 70)
BULB = (255, 214, 130)
GLOW = (255, 180, 80)
STAR = (255, 225, 150)
RUNE = (120, 170, 255)

CANVAS = 2048
TURNS = 5.5
OUT = Path(__file__).parent.parent / "custom_components/ble_christmas_lights/brand"


def u(value: float) -> float:
    """Design units (a 512 grid) to canvas pixels."""
    return value * CANVAS / 512


def background() -> Image.Image:
    """A rounded tile with a dark green vertical gradient."""
    gradient = Image.new("RGBA", (CANVAS, CANVAS))
    draw = ImageDraw.Draw(gradient)
    for y in range(CANVAS):
        t = y / CANVAS
        color = tuple(
            int(a + (b - a) * t)
            for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM, strict=True)
        )
        draw.line([(0, y), (CANVAS, y)], fill=(*color, 255))
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, CANVAS, CANVAS], radius=u(104), fill=255
    )
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    image.paste(gradient, (0, 0), mask)
    return image


def glow(image: Image.Image, points, radius: float, alpha: int, blur: float) -> None:
    """Add a soft halo around each point."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for x, y in points:
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius], fill=(*GLOW, alpha)
        )
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(u(blur))))


def render() -> Image.Image:
    image = background()
    draw = ImageDraw.Draw(image)

    # The light string spirals down the tree, widening towards the bottom.
    top, bottom, centre = 84, 418, 248
    wire = []
    for i in range(1001):
        t = i / 1000
        angle = t * TURNS * 2 * math.pi
        x = centre + (28 + 152 * t) * math.sin(angle)
        wire.append((u(x), u(top + (bottom - top) * t), math.cos(angle)))
    draw.line([(x, y) for x, y, _ in wire], fill=WIRE, width=int(u(7)), joint="curve")

    # Bulbs on the front of the tree only, so the spiral reads as 3D.
    bulbs = [
        (x, y) for i, (x, y, depth) in enumerate(wire) if i % 22 == 0 and depth > -0.3
    ]
    glow(image, bulbs, u(22), alpha=170, blur=12)
    draw = ImageDraw.Draw(image)
    for x, y in bulbs:
        draw.ellipse([x - u(10), y - u(10), x + u(10), y + u(10)], fill=BULB)

    # The star on top.
    sx, sy, r = u(248), u(60), u(28)
    star = [
        (
            sx + (r if k % 2 == 0 else r * 0.45) * math.sin(k * math.pi / 5),
            sy - (r if k % 2 == 0 else r * 0.45) * math.cos(k * math.pi / 5),
        )
        for k in range(10)
    ]
    glow(image, [(sx, sy)], u(36), alpha=190, blur=12)
    ImageDraw.Draw(image).polygon(star, fill=STAR)

    # Bluetooth rune, bottom right.
    cx, cy, s = u(452), u(450), u(30)
    ImageDraw.Draw(image).line(
        [
            (cx - s * 0.6, cy - s * 0.45),
            (cx + s * 0.6, cy + s * 0.45),
            (cx, cy + s),
            (cx, cy - s),
            (cx + s * 0.6, cy - s * 0.45),
            (cx - s * 0.6, cy + s * 0.45),
        ],
        fill=RUNE,
        width=int(u(10)),
        joint="curve",
    )
    return image


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    image = render()
    image.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    image.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png")
