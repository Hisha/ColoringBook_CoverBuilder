#!/usr/bin/env python3
"""
cover_builder.py — KDP-ready wraparound cover generator for Kids Coloring Books

Features
- Builds a full wrap (back + spine + front) with bleed at 300 DPI
- Computes spine from page count and paper type per KDP specs
- Places 2–5 interior page PNGs (fbnp_*.png) as tilted mini "sheets"
- Big playful title on the front; optional spine text if pages >= 79
- Back-cover description block and reserved barcode white box
- Outputs PNG preview and a print-ready PDF (via ImageMagick if available)

Input/Output
- INPUT directory: /mnt/ai_data/ColoringBooks/{safeTitle}/
  * Interior images named fbnp_X.png (X is an integer)
- OUTPUT files (same directory):
  * fbnp_cover.png (raster master @300 DPI)
  * fbnp_cover.pdf (single-page PDF, ready for KDP)

Usage
python cover_builder.py \
  --safe-title "Cute_Dinosaurs" \
  --title "Cute Dinosaurs Coloring Book for Kids" \
  --description "Includes 30 fun illustrations. Stomp into a world of friendly dinos!" \
  --pages 30 \
  --paper white \
  --trim "8.5x11" \
  --max-images 4 \
  --spine-title "Cute Dinosaurs Coloring Book" \
  --bg "gradient:pastel:1" \
  --seed 42

Dependencies
- Python 3.9+
- Pillow (PIL)
- ImageMagick "magick" CLI (optional, for best PDF output)

"""
import argparse
import math
import os
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

DPI = 300
BLEED_IN = 0.125  # inches (KDP)
SAFE_MARGIN_IN = 0.25  # inches inside trim for text blocks
BARCODE_W_IN = 2.0
BARCODE_H_IN = 1.2
BARCODE_BOTTOM_OFFSET_IN = 0.25

# Spine thickness per page (inches) per KDP guidance
PAPER_THICKNESS = {
    "white": 0.002252,
    "cream": 0.0025,
    # color options (use Premium for illustration-heavy covers unless user overrides)
    "color_premium": 0.002347,
    "color_standard": 0.002252,
}

# Fallback fonts (user can drop TTFs into ./fonts)
DEFAULT_TITLE_FONTS = [
    "fonts/Baloo2-SemiBold.ttf",
    "fonts/Fredoka-SemiBold.ttf",
    "fonts/ComicNeue-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
DEFAULT_TEXT_FONTS = [
    "fonts/Inter-Regular.ttf",
    "fonts/Quicksand-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

PASTEL_PALETTES = [
    ("#FDF2F8", "#DBEAFE"),
    ("#FDE68A", "#A7F3D0"),
    ("#E9D5FF", "#BFDBFE"),
    ("#FFE4E6", "#FEF9C3"),
    ("#E0F2FE", "#DCFCE7"),
]

@dataclass
class Size:
    w: int
    h: int


def inches_to_px(inches: float) -> int:
    return int(round(inches * DPI))


def parse_trim(trim_str: str) -> Tuple[float, float]:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*$", trim_str.lower())
    if not m:
        raise ValueError("--trim must look like '8.5x11' (inches)")
    return float(m.group(1)), float(m.group(2))


def pick_first_existing_font(candidates: List[str]) -> Optional[str]:
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def draw_gradient(bg: Image.Image, top_hex: str, bottom_hex: str) -> None:
    top = Image.new("RGB", bg.size, top_hex)
    bottom = Image.new("RGB", bg.size, bottom_hex)
    mask = Image.new("L", bg.size)
    md = ImageDraw.Draw(mask)
    # vertical gradient
    for y in range(bg.height):
        v = int(255 * (y / max(1, bg.height - 1)))
        md.line([(0, y), (bg.width, y)], fill=v)
    bg.paste(top)
    bg.paste(bottom, mask=mask)


def add_text_with_shadow(img: Image.Image, xy: Tuple[int, int], text: str, font: ImageFont.FreeTypeFont,
                         fill=(20, 20, 20), shadow=(255, 255, 255), offset=(0, 0), shadow_offset=(3, 3),
                         shadow_blur=3) -> None:
    # Render shadow layer
    txt = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    sx, sy = xy[0] + shadow_offset[0], xy[1] + shadow_offset[1]
    d.text((sx, sy), text, font=font, fill=shadow + (255,))
    if shadow_blur > 0:
        txt = txt.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
    img.alpha_composite(txt)
    # Render main text
    d2 = ImageDraw.Draw(img)
    d2.text((xy[0] + offset[0], xy[1] + offset[1]), text, font=font, fill=fill + (255,))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    words = text.split()
    lines = []
    line = []
    for w in words:
        test = " ".join(line + [w])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            line.append(w)
        else:
            if line:
                lines.append(" ".join(line))
            line = [w]
    if line:
        lines.append(" ".join(line))
    return "\n".join(lines)


def load_interior_images(images_dir: Path, max_images: int) -> List[Path]:
    candidates = []
    for p in sorted(images_dir.glob("fbnp_*.png")):
        m = re.search(r"fbnp_(\d+)\.png$", p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    candidates.sort(key=lambda t: t[0])
    files = [p for _, p in candidates]
    if not files:
        raise FileNotFoundError(f"No fbnp_*.png found in {images_dir}")
    # Choose up to max_images (at least 2)
    k = max(2, min(max_images, len(files)))
    # Prefer first few, but add a small shuffle for variety
    head = files[:min(6, len(files))]
    random.shuffle(head)
    return head[:k]


def place_tilted_sheet(base: Image.Image, sheet: Image.Image, box: Tuple[int, int, int, int], angle_deg: float,
                       border_px: int = 12, shadow_px: int = 12) -> None:
    # Create a white "paper" matte with border around the sheet
    w = box[2] - box[0]
    h = box[3] - box[1]
    paper = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    inner = sheet.copy().convert("L").convert("RGBA")
    # Fit the interior art with padding
    pad = max(8, min(w, h) // 20)
    inner_w = w - 2 * (border_px + pad)
    inner_h = h - 2 * (border_px + pad)
    if inner_w <= 0 or inner_h <= 0:
        return
    inner = inner.resize(_fit_within(inner.size, (inner_w, inner_h)), Image.LANCZOS)
    # paste centered
    cx = (w - inner.width) // 2
    cy = (h - inner.height) // 2
    paper.alpha_composite(inner, (cx, cy))

    # Rotate paper
    rotated = paper.rotate(angle_deg, expand=True, resample=Image.BICUBIC)

    # Shadow
    shadow = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
    mask = rotated.split()[3]
    sh.paste((0, 0, 0, 180), (0, 0), mask)
    sh = sh.filter(ImageFilter.GaussianBlur(radius=shadow_px))
    shadow.alpha_composite(sh, (shadow_px, shadow_px))

    # Composite shadow then paper
    px = box[0] - (rotated.width - w) // 2
    py = box[1] - (rotated.height - h) // 2
    base.alpha_composite(shadow, (px, py))
    base.alpha_composite(rotated, (px, py))


def _fit_within(src_size: Tuple[int, int], target_size: Tuple[int, int]) -> Tuple[int, int]:
    sw, sh = src_size
    tw, th = target_size
    scale = min(tw / sw, th / sh)
    return max(1, int(sw * scale)), max(1, int(sh * scale))


def compute_dimensions(trim_w_in: float, trim_h_in: float, pages: int, paper: str) -> Tuple[Size, Size, int]:
    bleed_px = inches_to_px(BLEED_IN)
    trim_w_px = inches_to_px(trim_w_in)
    trim_h_px = inches_to_px(trim_h_in)

    spine_in = PAPER_THICKNESS[paper] * pages
    spine_px = inches_to_px(spine_in)

    total_w_px = inches_to_px(BLEED_IN * 2 + trim_w_in * 2 + spine_in)
    total_h_px = inches_to_px(BLEED_IN * 2 + trim_h_in)

    return Size(total_w_px, total_h_px), Size(trim_w_px, trim_h_px), spine_px


def build_cover(
    safe_title: str,
    book_title: str,
    description: str,
    pages: int,
    paper: str,
    trim: Tuple[float, float],
    max_images: int,
    spine_title: Optional[str],
    bg: str,
    seed: Optional[int] = None,
) -> Path:
    if seed is not None:
        random.seed(seed)

    images_dir = Path(f"/mnt/ai_data/ColoringBooks/{safe_title}")
    out_png = images_dir / "fbnp_cover.png"
    out_pdf = images_dir / "fbnp_cover.pdf"

    (total, trim_px, spine_px) = compute_dimensions(trim[0], trim[1], pages, paper)

    # Base RGBA canvas
    base = Image.new("RGBA", (total.w, total.h), (255, 255, 255, 255))

    # Background: gradient or solid
    if bg.startswith("gradient:pastel"):
        _, _, variant = bg.partition(":pastel:")
        idx = 0
        try:
            idx = max(0, min(len(PASTEL_PALETTES) - 1, int(variant)))
        except Exception:
            idx = 0
        draw_gradient(base.convert("RGB"), *PASTEL_PALETTES[idx])
        base = base.convert("RGBA")
    elif re.match(r"^#?[0-9a-fA-F]{6}$", bg):
        color = bg if bg.startswith("#") else f"#{bg}"
        ImageDraw.Draw(base).rectangle([(0, 0), (total.w, total.h)], fill=color + "ff")
    else:
        # default soft teal
        ImageDraw.Draw(base).rectangle([(0, 0), (total.w, total.h)], fill="#E0F2FEff")

    # Panels
    bleed_px = inches_to_px(BLEED_IN)
    left_x0 = 0 + bleed_px
    left_x1 = left_x0 + trim_px.w  # back cover area
    spine_x0 = left_x1
    spine_x1 = spine_x0 + spine_px
    right_x0 = spine_x1
    right_x1 = right_x0 + trim_px.w  # front cover area

    # Load interior images
    interior_files = load_interior_images(images_dir, max_images)
    interior_imgs = [Image.open(p).convert("L") for p in interior_files]

    # Place tilted sheets: layout boxes
    def random_boxes(panel_x0: int, panel_x1: int, rows: int = 2, cols: int = 3) -> List[Tuple[int, int, int, int]]:
        panel_w = panel_x1 - panel_x0
        panel_h = total.h
        boxes = []
        cell_w = panel_w // cols
        cell_h = panel_h // rows
        for r in range(rows):
            for c in range(cols):
                x0 = panel_x0 + c * cell_w + random.randint(-cell_w // 10, cell_w // 10)
                y0 = bleed_px + r * cell_h + random.randint(-cell_h // 10, cell_h // 10)
                w = int(cell_w * 0.8)
                h = int(cell_h * 0.8)
                boxes.append((x0, y0, x0 + w, y0 + h))
        random.shuffle(boxes)
        return boxes

    front_boxes = random_boxes(right_x0, right_x1)
    back_boxes = random_boxes(left_x0, left_x1)

    all_boxes = []
    # Interleave some front and back placements
    for i, img in enumerate(interior_imgs):
        angle = random.uniform(-15, 15)
        # Alternate placement: front, back, front, ...
        target_boxes = front_boxes if i % 2 == 0 else back_boxes
        if not target_boxes:
            target_boxes = front_boxes
        box = target_boxes.pop()
        # Convert line art to RGBA black
        art = ImageOps.autocontrast(img)
        art = art.convert("RGBA")
        for j in range(3):
            art.putchannel(j, art.split()[3])
        place_tilted_sheet(base, art, box, angle)
        all_boxes.append(box)

    # Title on front
    title_font_path = pick_first_existing_font(DEFAULT_TITLE_FONTS)
    if not title_font_path:
        raise FileNotFoundError("No title font found. Add a TTF under ./fonts or install DejaVuSans.")

    # Scale title to fit ~70% width of front panel
    draw = ImageDraw.Draw(base)
    max_title_w = int((right_x1 - right_x0) * 0.8)
    title_size = 150
    while title_size > 24:
        f = ImageFont.truetype(title_font_path, title_size)
        bbox = draw.textbbox((0, 0), book_title, font=f)
        if bbox[2] - bbox[0] <= max_title_w:
            break
        title_size -= 4
    f_title = ImageFont.truetype(title_font_path, title_size)

    title_x = right_x0 + (right_x1 - right_x0 - (draw.textbbox((0, 0), book_title, font=f_title)[2])) // 2
    title_y = bleed_px + inches_to_px(0.35)  # top-ish

    add_text_with_shadow(
        base,
        (title_x, title_y),
        book_title,
        f_title,
        fill=(25, 25, 25),
        shadow=(255, 255, 255),
        shadow_offset=(3, 3),
        shadow_blur=4,
    )

    # Optional spine text (only if pages >= 79 per KDP)
    if spine_title and pages >= 79 and spine_px > 0:
        spine_font_size = max(24, min(80, spine_px - inches_to_px(0.125)))
        f_spine = ImageFont.truetype(title_font_path, spine_font_size)
        txt_img = Image.new("RGBA", (spine_px, total.h), (0, 0, 0, 0))
        td = ImageDraw.Draw(txt_img)
        # Rotate text 90 degrees (bottom-to-top typical)
        text_w = td.textlength(spine_title, font=f_spine)
        # Center along spine height
        tx = (spine_px - int(text_w)) // 2
        ty = (total.h - f_spine.size) // 2
        td.text((tx, ty), spine_title, font=f_spine, fill=(30, 30, 30, 255))
        txt_img = txt_img.rotate(90, expand=True, resample=Image.BICUBIC)
        # After rotation, center onto spine region
        sx = spine_x0 + (spine_px - txt_img.width) // 2
        sy = (total.h - txt_img.height) // 2
        base.alpha_composite(txt_img, (sx, sy))

    # Back-cover description block
    text_font_path = pick_first_existing_font(DEFAULT_TEXT_FONTS)
    if not text_font_path:
        text_font_path = title_font_path
    f_body = ImageFont.truetype(text_font_path, 40)
    bd = ImageDraw.Draw(base)

    desc_max_w = int((left_x1 - left_x0) * 0.8)
    desc_x = left_x0 + int((left_x1 - left_x0 - desc_max_w) * 0.5)
    desc_y = bleed_px + inches_to_px(0.75)
    wrapped = wrap_text(description, f_body, desc_max_w, bd)

    # Background rounded rectangle for readability
    # (Keep subtle opacity to remain print-safe once flattened)
    padding = inches_to_px(0.2)
    text_bbox = bd.multiline_textbbox((0, 0), wrapped, font=f_body, spacing=10)
    tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
    card = Image.new("RGBA", (tw + 2 * padding, th + 2 * padding), (255, 255, 255, 210))
    base.alpha_composite(card, (desc_x - padding, desc_y - padding))

    bd = ImageDraw.Draw(base)
    bd.multiline_text((desc_x, desc_y), wrapped, font=f_body, fill=(30, 30, 30, 255), spacing=10, align="left")

    # Reserve barcode area: bottom-right of back cover by default
    barcode_w = inches_to_px(BARCODE_W_IN)
    barcode_h = inches_to_px(BARCODE_H_IN)
    barcode_x = left_x1 - barcode_w - inches_to_px(0.25)  # 0.25" margin from inner edge
    barcode_y = total.h - bleed_px - barcode_h - inches_to_px(BARCODE_BOTTOM_OFFSET_IN)

    # Ensure it stays within back cover panel
    barcode_x = max(left_x0 + inches_to_px(0.25), barcode_x)
    barcode_y = min(total.h - bleed_px - barcode_h - inches_to_px(0.1), barcode_y)

    bd.rectangle([(barcode_x, barcode_y), (barcode_x + barcode_w, barcode_y + barcode_h)], fill=(255, 255, 255, 255))

    # Final save
    base = base.convert("RGB")  # flatten alpha
    base.save(out_png, format="PNG", dpi=(DPI, DPI))

    # Attempt PDF creation via ImageMagick for high-quality embedding
    if shutil.which("magick"):
        try:
            subprocess.run([
                "magick", str(out_png),
                "-units", "PixelsPerInch", "-density", str(DPI),
                str(out_pdf)
            ], check=True)
        except subprocess.CalledProcessError:
            # fallback to Pillow's PDF save
            base.save(out_pdf, "PDF", resolution=DPI)
    else:
        base.save(out_pdf, "PDF", resolution=DPI)

    return out_pdf


def main():
    ap = argparse.ArgumentParser(description="Build a KDP-ready wraparound cover for a kids coloring book.")
    ap.add_argument("--safe-title", required=True, help="Safe folder name under /mnt/ai_data/ColoringBooks/{safeTitle}/")
    ap.add_argument("--title", required=True, help="Front cover title text")
    ap.add_argument("--description", required=True, help="Back cover description text (80–120 words)")
    ap.add_argument("--pages", type=int, required=True, help="Exact interior page count (e.g., 30)")
    ap.add_argument("--paper", choices=list(PAPER_THICKNESS.keys()), default="white", help="Paper type for spine calc")
    ap.add_argument("--trim", default="8.5x11", help="Trim size in inches, e.g. '8.5x11'")
    ap.add_argument("--max-images", type=int, default=5, help="Max interior images to place (2–5)")
    ap.add_argument("--spine-title", default=None, help="Optional spine text (requires pages >= 79)")
    ap.add_argument("--bg", default="gradient:pastel:1", help="Background: '#RRGGBB' or 'gradient:pastel:N'")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducible layout")

    args = ap.parse_args()

    if args.max_images < 2:
        args.max_images = 2
    if args.max_images > 5:
        args.max_images = 5

    trim = parse_trim(args.trim)

    out_pdf = build_cover(
        safe_title=args.safe_title,
        book_title=args.title,
        description=args.description,
        pages=args.pages,
        paper=args.paper,
        trim=trim,
        max_images=args.max_images,
        spine_title=args.spine_title,
        bg=args.bg,
        seed=args.seed,
    )

    print(f"✅ Cover built: {out_pdf}")


if __name__ == "__main__":
    # Lazy imports used above
    from PIL import ImageOps  # noqa: E402
    main()
