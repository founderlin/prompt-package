"""Make near-white pixels transparent on the Prompt Package logos.

Run:
    python3 scripts/transparentize_logos.py

The script processes frontend/src/icon1.png and icon2.png in place.
It keeps a timestamped .bak copy alongside each file so the change is
reversible. The original files are overwritten on success.

Strategy:
    * Use a soft alpha ramp near pure white so antialiased edges on the
      logo outline stay smooth — hard "white -> 0 / not white -> 255"
      would give a jagged, cut-out look.
    * Tolerance is tuned for the off-white background ImageMagick-
      rendered logos use (~250-255 per channel).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PIL import Image


# Pixels with all three channels above ``WHITE_FLOOR`` are fully
# transparent; anything below ``OFF_WHITE_FLOOR`` stays fully opaque.
# In between we ramp linearly so antialiased edges blend cleanly into
# whatever background the logo is placed on.
WHITE_FLOOR = 250
OFF_WHITE_FLOOR = 230


def transparentize(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)

    # Back up the original next to the file so undo is one `mv` away.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, backup)

    img = Image.open(path).convert("RGBA")
    pixels = img.load()
    width, height = img.size

    changed = 0
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue  # already transparent, leave alone

            brightness = min(r, g, b)
            if brightness >= WHITE_FLOOR:
                # Pure / near-pure white → fully transparent.
                pixels[x, y] = (r, g, b, 0)
                changed += 1
            elif brightness >= OFF_WHITE_FLOOR:
                # Antialiased border: ramp alpha down so edges fade
                # rather than hard-cut.
                ramp = (brightness - OFF_WHITE_FLOOR) / (
                    WHITE_FLOOR - OFF_WHITE_FLOOR
                )
                new_alpha = int(a * (1 - ramp))
                pixels[x, y] = (r, g, b, new_alpha)
                changed += 1

    img.save(path, format="PNG", optimize=True)
    print(
        f"✓ {path}: {changed:,} pixels adjusted "
        f"(backup: {backup.name})"
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    targets = [
        root / "frontend" / "src" / "icon1.png",
        root / "frontend" / "src" / "icon2.png",
    ]
    for t in targets:
        transparentize(t)


if __name__ == "__main__":
    main()
