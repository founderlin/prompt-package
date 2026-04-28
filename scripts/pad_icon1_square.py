"""Square-pad icon1.png so it fits browser tab favicons cleanly.

Favicons render in 16x16 / 32x32 / 192x192 square slots. A non-square
source gets squashed when the browser / OS resizes it, which distorts
the logo. We copy the alpha-channel icon onto a transparent square
canvas (side = max(w, h)), centered, so every renderer can just scale
the whole frame uniformly.

In addition to overwriting icon1.png in place, we also emit a few
common favicon sizes next to it so index.html / manifest.json can
pick the right one without on-the-fly scaling.

Run:
    python3 scripts/pad_icon1_square.py

Original bytes are backed up to icon1.png.<timestamp>.bak before the
overwrite, consistent with transparentize_logos.py.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PIL import Image


FAVICON_SIZES = (48, 96, 192)


def pad_to_square(src_rgba: Image.Image) -> Image.Image:
    w, h = src_rgba.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset = ((side - w) // 2, (side - h) // 2)
    canvas.paste(src_rgba, offset, src_rgba)
    return canvas


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    src = root / "frontend" / "src" / "icon1.png"
    if not src.exists():
        raise FileNotFoundError(src)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = src.with_suffix(src.suffix + f".{stamp}.bak")
    shutil.copy2(src, backup)

    original = Image.open(src).convert("RGBA")
    print(f"source  : {src.name}  {original.size}  mode={original.mode}")
    print(f"backup  : {backup.name}")

    squared = pad_to_square(original)
    squared.save(src, format="PNG", optimize=True)
    print(f"overwrote : {src.name}  {squared.size}")

    # Emit scaled favicon variants next to the source. PNG is universally
    # supported for <link rel="icon">, so we don't bother with .ico.
    for size in FAVICON_SIZES:
        thumb = squared.resize((size, size), Image.LANCZOS)
        out = src.with_name(f"favicon-{size}.png")
        thumb.save(out, format="PNG", optimize=True)
        print(f"wrote    : {out.name}  {thumb.size}")


if __name__ == "__main__":
    main()
