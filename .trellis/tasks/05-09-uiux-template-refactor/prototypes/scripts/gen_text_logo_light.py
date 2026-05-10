"""Generate a transparent-background, ocean-blue Text logo PNG.

Source : /Users/shan/Downloads/nanobot/Text logo.jpg  (white background, dark text)
Output : ./assets/text-logo-light.png                 (transparent bg, ocean-blue text)

Strategy:
  1. Invert RGB so the original dark text becomes light, white bg becomes black.
  2. Use per-pixel brightness as alpha -> pixels that were originally bright (bg)
     become transparent, pixels that were originally dark (text) stay opaque.
  3. Force remaining RGB to ocean-blue (#1E90FF = 30/144/255) so the glyph
     matches the logo.png primary color on any dark background.
"""
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[5]  # project root (nanobot)
SRC = ROOT / "Text logo.jpg"
OUT_DIR = Path(__file__).resolve().parents[1] / "assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "text-logo-light.png"


# Ocean blue / DodgerBlue: #1E90FF (matches logo.png primary color).
TEXT_RGB = (30, 144, 255)


def main() -> None:
    src = Image.open(SRC).convert("RGB")
    inv = ImageChops.invert(src).convert("RGBA")
    w, h = inv.size
    pixels = inv.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _ = pixels[x, y]
            # Brightness of inverted pixel == darkness of original pixel.
            # Use it directly as alpha, so text is opaque ocean-blue, bg transparent.
            lum = max(r, g, b)
            pixels[x, y] = (TEXT_RGB[0], TEXT_RGB[1], TEXT_RGB[2], lum)
    inv.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({w}x{h}) color=#{TEXT_RGB[0]:02X}{TEXT_RGB[1]:02X}{TEXT_RGB[2]:02X}")


if __name__ == "__main__":
    main()
