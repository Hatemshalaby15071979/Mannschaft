#!/usr/bin/env python3
"""Generate the Mannschaft brand assets from the founder's logo PDF.

    python3 tools/make_logo.py

Source: ``helix_codex_inevitable_engraving.pdf`` at the project root (one page,
white engraving on black). The PDF is rendered at 300 dpi, the near-black
background is converted to transparency, and the mark is cropped to its ink.

Outputs (committed, regenerable):

    src/v5/client/assets/logo-mark.png      1024 px, transparent, white ink
    src/v5/client/assets/logo-badge.png     512 px, dark square (docs/social)
    src/v5/client/icons/icon-192.png        PWA icon
    src/v5/client/icons/icon-512.png        PWA icon + maskable
    src/v5/client/icons/apple-touch-icon.png 180 px
    src/v5/client/icons/favicon-32.png      32 px

The light theme inverts the mark with CSS (``filter: invert(1)``), so one
transparent asset serves both themes.

Requires Pillow and poppler's ``pdftocairo``. Both are build-time only; the
committed PNGs are what the app ships.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT.parent / "helix_codex_inevitable_engraving.pdf"
CLIENT = ROOT / "src" / "v5" / "client"
ASSETS = CLIENT / "assets"
ICONS = CLIENT / "icons"

BACKGROUND = (13, 17, 23, 255)  # #0d1117, the app's dark surface
NOISE_FLOOR = 18  # the PDF's black is ~10/255, not 0
MARK_SIZE = 1024


def render_pdf(workdir: Path) -> Path:
    if not PDF.is_file():
        raise SystemExit(f"logo source not found: {PDF}")
    subprocess.run(
        ["pdftocairo", "-png", "-r", "300", "-f", "1", "-l", "1", str(PDF), str(workdir / "page")],
        check=True,
        capture_output=True,
    )
    page = workdir / "page-1.png"
    if not page.is_file():
        raise SystemExit("pdftocairo produced no page image")
    return page


def extract_mark(page: Path) -> Image.Image:
    """White ink with alpha taken from luminance, cropped to the drawing."""
    gray = Image.open(page).convert("L")
    alpha = gray.point(
        lambda v: 0 if v <= NOISE_FLOOR else min(255, round((v - NOISE_FLOOR) * 255 / (255 - NOISE_FLOOR)))
    )
    # Lift midtones: the engraving is fine-lined, so at 32-52 px a linear alpha
    # averages to a grey smudge. Gamma < 1 keeps small sizes legible.
    alpha = alpha.point(lambda a: round(255 * (a / 255) ** 0.72))
    box = alpha.getbbox()
    if box is None:
        raise SystemExit("no ink found in the logo PDF")
    ink = alpha.crop(box)
    mark = Image.new("RGBA", ink.size, (255, 255, 255, 255))
    mark.putalpha(ink)

    pad = max(2, round(max(ink.size) * 0.03))
    padded = Image.new("RGBA", (ink.width + 2 * pad, ink.height + 2 * pad), (0, 0, 0, 0))
    padded.paste(mark, (pad, pad))
    return padded.resize((MARK_SIZE, MARK_SIZE), Image.LANCZOS)


def on_square(mark: Image.Image, size: int, background: tuple[int, int, int, int], inset: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background)
    art = mark.copy()
    art.thumbnail((round(size * inset), round(size * inset)), Image.LANCZOS)
    canvas.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return canvas


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    print(f"{path.relative_to(ROOT)}  {image.width}x{image.height}  {path.stat().st_size // 1024} KiB")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mannschaft-logo-") as tmp:
        page = render_pdf(Path(tmp))
        mark = extract_mark(page)

    save_png(mark, ASSETS / "logo-mark.png")
    save_png(on_square(mark, 512, BACKGROUND, 0.78).convert("RGB"), ASSETS / "logo-badge.png")

    save_png(on_square(mark, 192, BACKGROUND, 0.80).convert("RGB"), ICONS / "icon-192.png")
    save_png(on_square(mark, 512, BACKGROUND, 0.80).convert("RGB"), ICONS / "icon-512.png")
    save_png(on_square(mark, 180, BACKGROUND, 0.78).convert("RGB"), ICONS / "apple-touch-icon.png")

    favicon = on_square(mark, 32, BACKGROUND, 0.86).convert("RGB")
    save_png(favicon, ICONS / "favicon-32.png")


if __name__ == "__main__":
    sys.exit(main())
