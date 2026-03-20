"""Generate a GitHub social preview banner for GridRunner (1280x640)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).parent

# ── Colours ─────────────────────────────────────────────────────────────────

BG_TOP = (79, 70, 229)       # indigo-600
BG_BOTTOM = (109, 40, 217)   # violet-600
GRID_LINE = (255, 160, 40, 70)         # neon orange ~27%
TEXT_PRIMARY = (255, 255, 255, 255)
TEXT_SECONDARY = (255, 255, 255, 190)  # white 75%
PILL_BG = (255, 255, 255, 28)
PILL_TEXT = (255, 255, 255, 210)


def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_rounded_rect(draw, bbox, radius, fill):
    x0, y0, x1, y1 = bbox
    d = radius * 2
    draw.pieslice([x0, y0, x0 + d, y0 + d], 180, 270, fill=fill)
    draw.pieslice([x1 - d, y0, x1, y0 + d], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - d, x0 + d, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - d, y1 - d, x1, y1], 0, 90, fill=fill)
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)


def load_font(name, size):
    """Try to load a named font, fall back to default."""
    try:
        return ImageFont.truetype(name, size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype(f"/System/Library/Fonts/{name}.ttc", size)
        except (OSError, IOError):
            return ImageFont.load_default()


def generate_banner():
    W, H = 1280, 640
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # ── gradient background ───────────────────────────────────────────
    for y in range(H):
        # Diagonal-ish gradient: blend based on both x-center and y
        t = y / (H - 1)
        row_color = lerp_color(BG_TOP, BG_BOTTOM, t) + (255,)
        draw.line([(0, y), (W - 1, y)], fill=row_color)

    # ── grid pattern (composited via overlay for correct alpha blend) ─
    grid_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_overlay)
    spacing = 120
    lw = 1
    for x in range(spacing, W, spacing):
        grid_draw.line([(x, 0), (x, H)], fill=GRID_LINE, width=lw)
    for y in range(spacing, H, spacing):
        grid_draw.line([(0, y), (W, y)], fill=GRID_LINE, width=lw)
    img = Image.alpha_composite(img, grid_overlay)
    draw = ImageDraw.Draw(img)

    # ── icon (reuse the 1024px master, resize to 160px) ───────────────
    icon_size = 140
    icon_path = ASSETS_DIR / "icon-macos-1024.png"
    if icon_path.exists():
        icon = Image.open(icon_path).convert("RGBA")
        icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    else:
        from generate_icons import render_icon
        icon = render_icon(icon_size, apply_squircle=True)

    # Create a shadow layer behind the icon for contrast
    shadow_expand = 16
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    # We'll paste the shadow after computing layout

    # ── layout: icon + text, vertically centered ──────────────────────
    # Fonts
    font_title = load_font("HelveticaNeue", 96)
    font_tagline = load_font("HelveticaNeue", 32)
    font_pills = load_font("HelveticaNeue", 22)

    title_text = "GridRunner"
    tagline_text = "Manage, schedule, and monitor your scripts"

    # Measure text — use anchor="lt" so draw position = left-top of bbox
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title, anchor="lt")
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]

    tagline_bbox = draw.textbbox((0, 0), tagline_text, font=font_tagline, anchor="lt")
    tagline_w = tagline_bbox[2] - tagline_bbox[0]
    tagline_h = tagline_bbox[3] - tagline_bbox[1]

    # Pills row
    pills = ["FastAPI", "Alpine.js", "APScheduler", "Cross-Platform"]
    pill_padding_x = 16
    pill_padding_y = 8
    pill_gap = 12
    pill_radius = 14

    pill_measurements = []
    total_pills_w = 0
    for p in pills:
        pb = draw.textbbox((0, 0), p, font=font_pills)
        pw = pb[2] - pb[0] + pill_padding_x * 2
        ph = pb[3] - pb[1] + pill_padding_y * 2
        pill_measurements.append((pw, ph))
        total_pills_w += pw
    total_pills_w += pill_gap * (len(pills) - 1)

    # Vertical layout spacing
    gap_icon_title = 32
    gap_title_tagline = 24
    gap_tagline_pills = 28

    # Total content height
    content_h = (
        icon_size
        + gap_icon_title
        + title_h
        + gap_title_tagline
        + tagline_h
        + gap_tagline_pills
        + (pill_measurements[0][1] if pill_measurements else 0)
    )

    y_start = (H - content_h) // 2

    # Draw icon shadow (dark translucent rounded rect, slightly larger)
    icon_x = (W - icon_size) // 2
    icon_y = y_start
    se = shadow_expand
    r_frac = 0.2237
    icon_r = int(icon_size * r_frac)
    draw_rounded_rect(
        shadow_draw,
        (icon_x - se // 2, icon_y - se // 2 + 4,
         icon_x + icon_size + se // 2, icon_y + icon_size + se // 2 + 4),
        icon_r + se // 2,
        fill=(0, 0, 0, 50),
    )
    img = Image.alpha_composite(img, shadow_layer)
    draw = ImageDraw.Draw(img)

    # Draw icon centered
    img.paste(icon, (icon_x, icon_y), icon)

    # Draw title
    title_x = (W - title_w) // 2
    title_y = icon_y + icon_size + gap_icon_title
    draw.text((title_x, title_y), title_text, font=font_title, fill=TEXT_PRIMARY, anchor="lt")

    # Draw tagline
    tagline_x = (W - tagline_w) // 2
    tagline_y = title_y + title_h + gap_title_tagline
    draw.text((tagline_x, tagline_y), tagline_text, font=font_tagline, fill=TEXT_SECONDARY, anchor="lt")

    # Draw pills
    pills_y = tagline_y + tagline_h + gap_tagline_pills
    pills_x = (W - total_pills_w) // 2
    cursor_x = pills_x

    # Draw pills on a separate overlay so alpha blending works correctly
    pill_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill_overlay)

    for i, p in enumerate(pills):
        pw, ph = pill_measurements[i]
        draw_rounded_rect(
            pill_draw,
            (cursor_x, pills_y, cursor_x + pw, pills_y + ph),
            pill_radius,
            fill=PILL_BG,
        )
        # Center text in pill
        tb = pill_draw.textbbox((0, 0), p, font=font_pills, anchor="lt")
        tx = cursor_x + (pw - (tb[2] - tb[0])) // 2
        ty = pills_y + (ph - (tb[3] - tb[1])) // 2
        pill_draw.text((tx, ty), p, font=font_pills, fill=PILL_TEXT, anchor="lt")
        cursor_x += pw + pill_gap

    img = Image.alpha_composite(img, pill_overlay)

    # ── save ──────────────────────────────────────────────────────────
    out = ASSETS_DIR / "social-banner.png"
    img.save(out, "PNG")
    print(f"Banner saved: {out} ({W}x{H})")


if __name__ == "__main__":
    generate_banner()
