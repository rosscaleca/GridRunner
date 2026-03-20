"""Generate GridRunner app icons for macOS, Windows, and Linux."""

import math
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ASSETS_DIR = Path(__file__).parent

# ── Colours ─────────────────────────────────────────────────────────────────

BG_TOP = (79, 70, 229)      # indigo-600
BG_BOTTOM = (109, 40, 217)  # violet-600
GRID_LINE = (255, 255, 255, 38)   # white 15%
ARROW_FILL = (255, 255, 255, 240) # white 94%
ARROW_SHADOW = (0, 0, 0, 50)


# ── Drawing helpers ─────────────────────────────────────────────────────────

def lerp_color(c1, c2, t):
    """Linearly interpolate between two RGB tuples."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_rounded_rect(draw, bbox, radius, fill):
    """Draw a filled rounded rectangle (Pillow ≥ 10 has this built in, but
    this works on older versions too)."""
    x0, y0, x1, y1 = bbox
    # Use pieslice + rectangles approach
    d = radius * 2
    draw.pieslice([x0, y0, x0 + d, y0 + d], 180, 270, fill=fill)
    draw.pieslice([x1 - d, y0, x1, y0 + d], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - d, x0 + d, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - d, y1 - d, x1, y1], 0, 90, fill=fill)
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)


def make_squircle_mask(size, radius_fraction=0.2237):
    """Create a macOS Big Sur-style squircle mask.
    Apple's standard corner radius is ~22.37% of icon width."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    r = int(size * radius_fraction)
    draw_rounded_rect(draw, (0, 0, size, size), r, fill=255)
    return mask


def render_icon(size, apply_squircle=False):
    """Render the GridRunner icon at the given pixel size.

    Design:
      - Gradient background (indigo → violet)
      - 4×4 grid of subtle white lines
      - A bold right-pointing play-arrow (the "Runner")
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── background gradient ───────────────────────────────────────────
    for y in range(size):
        t = y / (size - 1)
        row_color = lerp_color(BG_TOP, BG_BOTTOM, t) + (255,)
        draw.line([(0, y), (size - 1, y)], fill=row_color)

    # ── grid lines ────────────────────────────────────────────────────
    margin = size * 0.18
    grid_area = size - 2 * margin
    line_w = max(1, round(size / 128))

    for i in range(1, 4):
        frac = i / 4
        # vertical
        x = int(margin + grid_area * frac)
        draw.line([(x, int(margin)), (x, int(size - margin))],
                  fill=GRID_LINE, width=line_w)
        # horizontal
        y = int(margin + grid_area * frac)
        draw.line([(int(margin), y), (int(size - margin), y)],
                  fill=GRID_LINE, width=line_w)

    # ── play arrow ────────────────────────────────────────────────────
    # Centered, takes ~48% of the icon size
    cx, cy = size / 2, size / 2
    arrow_h = size * 0.48
    arrow_w = arrow_h * 0.87  # equilateral-ish

    # Triangle vertices (pointing right)
    x_left = cx - arrow_w * 0.38
    x_right = cx + arrow_w * 0.52
    y_top = cy - arrow_h / 2
    y_bot = cy + arrow_h / 2

    arrow_pts = [
        (x_left, y_top),
        (x_right, cy),
        (x_left, y_bot),
    ]

    # Shadow (offset down-right)
    sh_offset = max(2, size // 128)
    shadow_pts = [(x + sh_offset, y + sh_offset) for x, y in arrow_pts]
    draw.polygon(shadow_pts, fill=ARROW_SHADOW)

    # Arrow fill
    draw.polygon(arrow_pts, fill=ARROW_FILL)

    # ── apply squircle mask for macOS ─────────────────────────────────
    if apply_squircle:
        mask = make_squircle_mask(size)
        # Composite onto transparent background through mask
        bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        img = Image.composite(img, bg, mask)

    return img


# ── macOS .icns via iconutil ────────────────────────────────────────────────

def generate_macos_icns():
    """Generate macOS .icns using an iconset bundle + iconutil."""
    iconset = ASSETS_DIR / "GridRunner.iconset"
    iconset.mkdir(exist_ok=True)

    # macOS icon sizes: 16,32,128,256,512 at 1x and 2x
    pairs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    master = render_icon(1024, apply_squircle=True)
    for name, px in pairs:
        resized = master.resize((px, px), Image.LANCZOS)
        resized.save(iconset / name, "PNG")

    # Also save the 1024px master as a standalone PNG
    master.save(ASSETS_DIR / "icon-macos-1024.png", "PNG")

    # Convert to .icns via iconutil (macOS only)
    icns_path = ASSETS_DIR / "GridRunner.icns"
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            check=True, capture_output=True,
        )
        print(f"  macOS: {icns_path}")
    except FileNotFoundError:
        print("  macOS: iconutil not found — .iconset saved, .icns skipped")
    except subprocess.CalledProcessError as e:
        print(f"  macOS: iconutil failed: {e.stderr.decode()}")


# ── Windows .ico ────────────────────────────────────────────────────────────

def generate_windows_ico():
    """Generate a multi-resolution .ico file."""
    master = render_icon(256, apply_squircle=False)
    sizes = [16, 24, 32, 48, 64, 128, 256]

    ico_path = ASSETS_DIR / "GridRunner.ico"
    # Save with explicit bitmap sizes — Pillow embeds all requested sizes
    master.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"  Windows: {ico_path}")


# ── Linux PNGs + SVG placeholder ────────────────────────────────────────────

def generate_linux_pngs():
    """Generate standard Freedesktop icon sizes as PNGs."""
    linux_dir = ASSETS_DIR / "linux"
    linux_dir.mkdir(exist_ok=True)

    master = render_icon(512, apply_squircle=False)
    for s in [16, 24, 32, 48, 64, 128, 256, 512]:
        resized = master.resize((s, s), Image.LANCZOS)
        resized.save(linux_dir / f"gridrunner-{s}.png", "PNG")

    print(f"  Linux:   {linux_dir}/ (16–512 px PNGs)")


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating GridRunner icons...")
    generate_macos_icns()
    generate_windows_ico()
    generate_linux_pngs()
    print("Done.")
