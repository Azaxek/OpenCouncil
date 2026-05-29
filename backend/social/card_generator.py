"""
News card image generator for OpenCouncil.

Generates 1080x1080 PNG news cards with:
- Cinematic dramatic background from pollinations.ai (with retries)
- Heavy vignette effect (dark edges, bright center)
- Film grain texture overlay
- Color grading tint (deep blue/gold blockbuster look)
- OpenCouncil logo
- Bold impact headline with glow + drop shadow
- Accent bar above headline
- Summary text, date, and source bar
- Category badge (top-right pill)
- Programmatic abstract fallback if pollinations.ai is unreachable
"""

import io
import math
import os
import random
from typing import Optional

import httpx
import numpy
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Constants
CARD_WIDTH = 1080
CARD_HEIGHT = 1080
LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "opencouncil_logo.png")
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # fallback
FONT_REGULAR_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ── Aggressive pollinations.ai prompts ──────────────────────────────────────

PROMPT_TEMPLATES = [
    "epic cinematic {theme} city council, dramatic lighting volumetric rays, "
    "hyperrealistic 8k highly detailed, moody atmosphere golden hour, "
    "awe-inspiring grand scale, lens flare",

    "dramatic {theme} urban landscape, cinematic wide shot, lens flare, "
    "dark blue and gold tones, photorealistic, highly detailed, atmospheric",

    "epic {theme} infrastructure, brutalist architecture, dramatic sky, "
    "cinematic lighting, 8k resolution, hyperrealistic, moody cinematic, "
    "blood-orange sunset",

    "cinematic {theme} civic center, dramatic shadows, volumetric fog, "
    "golden hour light rays, hyperdetailed 8k, epic wide angle, "
    "dark moody atmosphere",
]

THEME_INTENSIFIERS = {
    "housing": "soaring brutalist housing towers against a blood-orange sunset sky, dramatic clouds",
    "infrastructure": "massive steel bridge at golden hour, dramatic lighting, epic scale",
    "education": "grand university hall with dramatic columns, cinematic lighting, hopeful atmosphere",
    "public safety": "dramatic city skyline at dusk, emergency lights reflecting, moody atmosphere",
    "transportation": "epic highway interchange at golden hour, light trails, dramatic sky",
    "parks": "majestic ancient trees in golden light, dramatic shadows, serene epic scale",
    "budget": "towering financial district skyscrapers, dramatic clouds, cinematic lighting",
    "zoning": "aerial view of sprawling cityscape at sunset, dramatic lighting, epic scale",
}


def _theme_intensifier(theme: str) -> str:
    """Return a theme-specific dramatic description, or a generic one."""
    key = theme.strip().lower()
    return THEME_INTENSIFIERS.get(key, "")


async def fetch_background(theme: str) -> Optional[bytes]:
    """
    Fetch a cinematic dramatic background from pollinations.ai.

    Tries up to 3 different prompts with varying angles/tones before giving up.
    Returns raw image bytes or None on total failure.
    """
    base_intensifier = _theme_intensifier(theme)

    for i, template in enumerate(PROMPT_TEMPLATES):
        prompt = template.format(theme=theme)
        if base_intensifier and i == 0:
            prompt = f"{prompt}, {base_intensifier}"

        url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.content
        except Exception:
            continue

    return None


# ── Vignette effect ─────────────────────────────────────────────────────────

def create_vignette(width: int, height: int, intensity: float = 1.0) -> Image.Image:
    """
    Create a heavy vignette effect — dark edges, bright center.

    Uses horizontal strips for O(n) performance instead of O(n²) point-by-point.
    """
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    # Draw horizontal strips — much faster than point-by-point
    strip_height = 4
    for y in range(0, height, strip_height):
        dy = y - center_y
        for x in range(0, width, strip_height):
            dx = x - center_x
            dist = math.sqrt(dx ** 2 + dy ** 2)
            # Quadratic falloff for dramatic effect
            alpha = int(min(255, (dist / max_radius) ** 2 * 255 * intensity))
            if alpha > 0:
                draw.rectangle(
                    [x, y, x + strip_height, y + strip_height],
                    fill=(0, 0, 0, alpha),
                )

    return overlay


# ── Color grading overlay ───────────────────────────────────────────────────

def create_color_grade(width: int, height: int) -> Image.Image:
    """
    Create a subtle color grading overlay — deep blue/gold blockbuster look.

    A radial gradient with warm gold in center, deep blue at edges.
    """
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    for y in range(0, height, 4):
        dy = y - center_y
        for x in range(0, width, 4):
            dx = x - center_x
            dist = math.sqrt(dx ** 2 + dy ** 2)
            t = dist / max_radius  # 0 at center, 1 at edges

            # Center: warm gold tint; Edges: deep blue tint
            r = int(15 * t)
            g = int(10 * t)
            b = int(30 * t)
            alpha = int(40 * t)  # subtle — max 40 alpha at edges

            if alpha > 0:
                draw.rectangle(
                    [x, y, x + 4, y + 4],
                    fill=(r, g, b, alpha),
                )

    return overlay


# ── Film grain texture ──────────────────────────────────────────────────────

def add_grain_texture(image: Image.Image, intensity: int = 25) -> Image.Image:
    """
    Add subtle film grain noise using numpy.

    numpy is already a dependency (used by EasyOCR fallback).
    """
    np_image = numpy.array(image, dtype=numpy.float32)
    noise = numpy.random.normal(0, intensity, np_image.shape[:2])
    for c in range(3):
        np_image[:, :, c] = numpy.clip(np_image[:, :, c] + noise, 0, 255)
    return Image.fromarray(np_image.astype(numpy.uint8))


# ── Programmatic abstract background (fallback) ─────────────────────────────

def generate_abstract_background(width: int, height: int) -> Image.Image:
    """
    Generate a cinematic abstract background using blurred shapes.

    Used when pollinations.ai is completely unreachable.
    Dark blue, deep purple, gold tones — layered colored circles with blur.
    """
    bg = Image.new("RGB", (width, height), (10, 15, 30))
    draw = ImageDraw.Draw(bg, "RGBA")

    random.seed(42)
    colors = [
        (25, 40, 80, 120),   # deep blue
        (60, 40, 80, 100),   # purple
        (80, 60, 30, 80),    # gold
        (15, 25, 60, 150),   # dark navy
        (100, 50, 40, 60),   # warm rust
        (40, 30, 70, 110),   # indigo
    ]

    for _ in range(10):
        cx = random.randint(0, width)
        cy = random.randint(0, height)
        r = random.randint(150, 500)
        color = random.choice(colors)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # Heavy Gaussian blur for soft abstract look
    bg = bg.filter(ImageFilter.GaussianBlur(radius=80))
    return bg


# ── Text glow effect ────────────────────────────────────────────────────────

def draw_text_with_glow(
    draw: ImageDraw.ImageDraw,
    xy: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color,
    glow_color,
    glow_radius: int = 5,
):
    """
    Draw text with a glow effect.

    Draws progressively larger, more transparent copies behind the main text.
    """
    x, y = xy
    # Draw glow layers (larger, transparent)
    for r in range(glow_radius, 0, -1):
        alpha = int(70 / (glow_radius - r + 1))
        if len(glow_color) == 4:
            glow = (glow_color[0], glow_color[1], glow_color[2], alpha)
        else:
            glow = (*glow_color, alpha)
        draw.text((x - r, y), text, fill=glow, font=font)
        draw.text((x + r, y), text, fill=glow, font=font)
        draw.text((x, y - r), text, fill=glow, font=font)
        draw.text((x, y + r), text, fill=glow, font=font)
        draw.text((x - r, y - r), text, fill=glow, font=font)
        draw.text((x + r, y + r), text, fill=glow, font=font)
    # Draw main text
    draw.text((x, y), text, fill=text_color, font=font)


# ── Category badge ──────────────────────────────────────────────────────────

def draw_category_badge(
    draw: ImageDraw.ImageDraw,
    category: str,
    card_width: int,
):
    """
    Draw a category pill badge in the top-right corner.
    """
    font = load_font(18, bold=True)
    badge_text = category.upper()
    bbox = font.getbbox(badge_text)
    text_w = bbox[2] if bbox else 0
    padding = 16
    badge_w = text_w + padding * 2
    badge_h = 36
    x = card_width - badge_w - 30
    y = 30

    # Draw pill background
    draw.rounded_rectangle(
        [x, y, x + badge_w, y + badge_h],
        radius=18,
        fill=(200, 170, 110, 220),
    )
    # Draw text
    draw.text(
        (x + padding, y + 6),
        badge_text,
        fill=(10, 15, 30, 255),
        font=font,
    )


# ── Existing helpers (unchanged) ────────────────────────────────────────────

def create_gradient_overlay(width: int, height: int) -> Image.Image:
    """
    Create a dark gradient overlay (black at bottom, transparent at top).

    Returns an RGBA image suitable for pasting as a mask.
    """
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(height):
        alpha = int(180 * (y / height))  # 0 to 180
        draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    return overlay


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to Pillow's default bitmap font."""
    try:
        if bold:
            return ImageFont.truetype(FONT_BOLD_PATH, size)
        else:
            return ImageFont.truetype(FONT_REGULAR_PATH, size)
    except (IOError, OSError):
        return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within *max_width* pixels."""
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        if bbox and bbox[2] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines


def _create_placeholder_logo() -> Image.Image:
    """Create a simple 120x120 circular placeholder logo with 'OC' text."""
    logo = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    # Gold circle
    draw.ellipse([5, 5, 115, 115], fill=(200, 170, 110, 255))
    # "OC" text
    font = load_font(40, bold=True)
    draw.text((35, 35), "OC", fill=(20, 25, 35, 255), font=font)
    return logo


# ── Main card generation ────────────────────────────────────────────────────

async def generate_card(
    headline: str,
    theme: str = "City Council",
    summary_text: str = "",
    city: str = "Paris, Texas",
    meeting_date: str = "",
    logo_path: Optional[str] = None,
    category: Optional[str] = None,
) -> bytes:
    """
    Generate a 1080x1080 news card PNG.

    Args:
        headline: The main impact headline (from neighborhood_impact).
        theme: Meeting category/theme for background generation.
        summary_text: Short summary text for the card body.
        city: City name (e.g. "Paris, Texas").
        meeting_date: Date of the meeting.
        logo_path: Path to OpenCouncil logo PNG. Falls back to a
                   programmatically-generated placeholder if not found.
        category: Optional category string for a top-right badge (e.g. "Housing").

    Returns:
        PNG image bytes.
    """
    # 1. Create base canvas (dark background as fallback)
    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), (20, 25, 35))

    # 2. Try to fetch and apply background from pollinations.ai
    bg_data = await fetch_background(theme)
    if bg_data:
        try:
            bg = Image.open(io.BytesIO(bg_data)).convert("RGB")
            bg = bg.resize((CARD_WIDTH, CARD_HEIGHT), Image.LANCZOS)
            card.paste(bg, (0, 0))
        except Exception:
            pass

    # If no background was fetched, use programmatic abstract fallback
    if bg_data is None:
        try:
            abstract_bg = generate_abstract_background(CARD_WIDTH, CARD_HEIGHT)
            card.paste(abstract_bg, (0, 0))
        except Exception:
            pass  # Keep the solid dark color

    # 3. Apply gradient overlay (bottom-to-top darkening)
    gradient = create_gradient_overlay(CARD_WIDTH, CARD_HEIGHT)
    card.paste(gradient, (0, 0), gradient)

    # 4. Apply heavy vignette effect (dark edges all around)
    vignette = create_vignette(CARD_WIDTH, CARD_HEIGHT, intensity=1.0)
    card.paste(vignette, (0, 0), vignette)

    # 5. Apply color grading (deep blue/gold blockbuster tint)
    color_grade = create_color_grade(CARD_WIDTH, CARD_HEIGHT)
    card.paste(color_grade, (0, 0), color_grade)

    # 6. Apply film grain texture
    try:
        card = add_grain_texture(card, intensity=20)
    except Exception:
        pass

    # 7. Prepare drawing surface
    draw = ImageDraw.Draw(card)

    # 8. Load logo (or create placeholder)
    logo_img = None
    resolved_logo_path = logo_path or LOGO_PATH
    if resolved_logo_path and os.path.exists(resolved_logo_path):
        try:
            logo_img = Image.open(resolved_logo_path).convert("RGBA")
            logo_img = logo_img.resize((120, 120), Image.LANCZOS)
        except Exception:
            pass

    if logo_img is None:
        logo_img = _create_placeholder_logo()

    card.paste(logo_img, (40, 40), logo_img)

    # 9. Draw "OPEN COUNCIL" brand text
    brand_font = load_font(28, bold=True)
    draw.text(
        (180, 65),
        "OPEN COUNCIL",
        fill=(200, 170, 110, 255),
        font=brand_font,
    )

    # 10. Draw city label
    city_font = load_font(22)
    draw.text(
        (180, 100),
        city.upper(),
        fill=(180, 180, 180, 200),
        font=city_font,
    )

    # 11. Draw category badge (if provided)
    if category:
        draw_category_badge(draw, category, CARD_WIDTH)

    # 12. Draw accent bar (thin gold line above headline)
    accent_y = 340
    accent_bar_width = 120
    accent_x = (CARD_WIDTH - accent_bar_width) // 2
    for i in range(accent_bar_width):
        # Gradient from gold to transparent gold
        t = i / accent_bar_width
        alpha = int(180 * (1 - abs(t - 0.5) * 2))  # peak in center
        draw.rectangle(
            [accent_x + i, accent_y, accent_x + i + 1, accent_y + 3],
            fill=(200, 170, 110, alpha),
        )

    # 13. Draw headline (large, bold, centered) with glow + drop shadow
    headline_font = load_font(76, bold=True)  # 72-80px range
    headline_lines = wrap_text(headline.upper(), headline_font, CARD_WIDTH - 120)
    headline_lines = headline_lines[:4]  # Limit to 4 lines

    y_start = 380
    glow_color = (200, 170, 110)  # gold glow
    for line in headline_lines:
        bbox = headline_font.getbbox(line)
        text_width = bbox[2] if bbox else 0
        x = (CARD_WIDTH - text_width) // 2

        # Drop shadow (more offset and blur simulated by multiple passes)
        shadow_offset = 4
        for sx, sy in [
            (shadow_offset, shadow_offset),
            (shadow_offset + 1, shadow_offset + 1),
        ]:
            draw.text(
                (x + sx, y_start + sy),
                line,
                fill=(0, 0, 0, 140),
                font=headline_font,
            )

        # Glow effect
        draw_text_with_glow(
            draw,
            (x, y_start),
            line,
            headline_font,
            text_color=(255, 255, 255, 255),
            glow_color=glow_color,
            glow_radius=5,
        )

        y_start += 88  # Slightly more spacing for larger font

    # 14. Draw summary text (if provided)
    if summary_text:
        summary_font = load_font(28)
        summary_lines = wrap_text(summary_text, summary_font, CARD_WIDTH - 160)
        summary_lines = summary_lines[:3]  # Max 3 lines
        y_start = max(y_start + 40, 620)
        for line in summary_lines:
            bbox = summary_font.getbbox(line)
            text_width = bbox[2] if bbox else 0
            x = (CARD_WIDTH - text_width) // 2
            draw.text(
                (x, y_start),
                line,
                fill=(220, 220, 220, 255),
                font=summary_font,
            )
            y_start += 40

    # 15. Draw date and source bar at bottom
    date_font = load_font(24)
    date_text = meeting_date if meeting_date else ""
    source_text = "OpenCouncil"

    draw.text(
        (60, CARD_HEIGHT - 80),
        date_text,
        fill=(180, 180, 180, 200),
        font=date_font,
    )

    # Right-align source
    bbox = date_font.getbbox(source_text)
    source_width = bbox[2] if bbox else 0
    draw.text(
        (CARD_WIDTH - 60 - source_width, CARD_HEIGHT - 80),
        source_text,
        fill=(200, 170, 110, 255),
        font=date_font,
    )

    # 16. Bottom accent line (thin gradient line at very bottom)
    bottom_line_y = CARD_HEIGHT - 10
    for i in range(CARD_WIDTH):
        t = i / CARD_WIDTH
        # Gradient: transparent → gold → transparent
        alpha = int(120 * (1 - abs(t - 0.5) * 2))
        if alpha > 0:
            draw.rectangle(
                [i, bottom_line_y, i + 1, bottom_line_y + 3],
                fill=(200, 170, 110, alpha),
            )

    # 17. Output to bytes
    buf = io.BytesIO()
    card.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()
