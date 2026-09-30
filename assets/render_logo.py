"""Rasterise the integration icon.

Two strands of warm white Christmas lights hanging across a night-blue tile,
with a small Bluetooth rune in the corner.

Drawn with Pillow at 4x and downsampled, so regenerating the artwork needs no
SVG engine.

    python assets/render_logo.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BACKGROUND = (22, 36, 71)
WIRE = (46, 94, 58)
BULB = (255, 214, 130)
GLOW = (255, 190, 90)
RUNE = (120, 170, 255)

CANVAS = 2048
OUT = Path(__file__).parent.parent / "custom_components/ble_christmas_lights/brand"


def u(value: float) -> float:
    """Design units (a 512 grid) to canvas pixels."""
    return value * CANVAS / 512


def strand(y0: float, sag: float) -> list[tuple[float, float]]:
    """Points along a hanging wire from left to right."""
    return [
        (u(x), u(y0 + sag * math.sin(math.pi * (x - 40) / 432)))
        for x in range(40, 473, 4)
    ]


def render() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, CANVAS, CANVAS], radius=u(104), fill=BACKGROUND)

    strands = [strand(150, 90), strand(300, 90)]
    bulbs = []
    for points in strands:
        draw.line(points, fill=WIRE, width=int(u(10)), joint="curve")
        bulbs += points[10:-5:18]

    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for x, y in bulbs:
        r = u(34)
        glow_draw.ellipse(
            [x - r, y + u(18) - r, x + r, y + u(18) + r], fill=(*GLOW, 150)
        )
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(u(14))))

    draw = ImageDraw.Draw(image)
    for x, y in bulbs:
        draw.rectangle([x - u(7), y - u(2), x + u(7), y + u(12)], fill=WIRE)
        draw.ellipse([x - u(13), y + u(6), x + u(13), y + u(40)], fill=BULB)

    # Bluetooth rune, bottom right
    cx, cy, s = u(420), u(430), u(34)
    draw.line(
        [
            (cx - s * 0.6, cy - s * 0.45),
            (cx + s * 0.6, cy + s * 0.45),
            (cx, cy + s),
            (cx, cy - s),
            (cx + s * 0.6, cy - s * 0.45),
            (cx - s * 0.6, cy + s * 0.45),
        ],
        fill=RUNE,
        width=int(u(9)),
        joint="curve",
    )
    return image


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    image = render()
    image.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    image.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png")
