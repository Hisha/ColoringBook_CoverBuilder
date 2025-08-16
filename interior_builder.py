#!/usr/bin/env python3
"""
interior_builder.py — KDP-ready interior PDF generator for Kids Coloring Books

Features
- Scans /mnt/ai_data/ColoringBooks/{safeTitle}/ for fbnp_*.png
- Builds a print-ready PDF interior (8.5"x11" default, 300 DPI)
- Adds front matter pages: "This Book Belongs To" + optional copyright
- Centers each coloring page art within safe margins
- Supports no-bleed layout (default for coloring books)

Usage:
python interior_builder.py \
  --safe-title "Cute_Dinosaurs" \
  --trim "8.5x11" \
  --dpi 300 \
  --margin-in 0.5 \
  --no-bleed

Output:
/mnt/ai_data/ColoringBooks/{safeTitle}/fbnp_interior.pdf
"""
import argparse
import os
import re
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont

DPI_DEFAULT = 300

# Fallback font (system)
DEFAULT_FONTS = [
    "fonts/ComicNeue-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def pick_first_existing_font(candidates: List[str]) -> str:
    for f in candidates:
        if Path(f).exists():
            return f
    raise FileNotFoundError("No suitable font found. Place a TTF under ./fonts or install DejaVuSans.")

def inches_to_px(inches: float, dpi: int) -> int:
    return int(round(inches * dpi))

def parse_trim(trim_str: str) -> Tuple[float, float]:
    m = re.match(r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)$", trim_str)
    if not m:
        raise ValueError("--trim must look like '8.5x11'")
    return float(m.group(1)), float(m.group(2))

def new_blank_page(trim_w_in: float, trim_h_in: float, dpi: int) -> Image.Image:
    return Image.new("RGB", (inches_to_px(trim_w_in, dpi), inches_to_px(trim_h_in, dpi)), (255, 255, 255))

def add_front_matter(pages: List[Image.Image], trim_w_in: float, trim_h_in: float, dpi: int) -> None:
    font_path = pick_first_existing_font(DEFAULT_FONTS)
    f = ImageFont.truetype(font_path, 100)

    # Page 1: This Book Belongs To
    p1 = new_blank_page(trim_w_in, trim_h_in, dpi)
    d1 = ImageDraw.Draw(p1)
    text = "This Book Belongs To:"
    bbox = d1.textbbox((0,0), text, font=f)
    x = (p1.width - (bbox[2]-bbox[0])) // 2
    y = (p1.height - (bbox[3]-bbox[1])) // 3
    d1.text((x,y), text, font=f, fill=(0,0,0))
    line_y = y + (bbox[3]-bbox[1]) + 100
    d1.line([(x, line_y), (x+inches_to_px(5,dpi), line_y)], fill=(0,0,0), width=5)
    pages.append(p1)

    # Page 2: Copyright/brand
    p2 = new_blank_page(trim_w_in, trim_h_in, dpi)
    d2 = ImageDraw.Draw(p2)
    smallf = ImageFont.truetype(font_path, 60)
    ctext = "© 2025 Fantasy Broadcast Network\nAll Rights Reserved"
    bbox2 = d2.multiline_textbbox((0,0), ctext, font=smallf, spacing=20)
    x2 = (p2.width - (bbox2[2]-bbox2[0])) // 2
    y2 = (p2.height - (bbox2[3]-bbox2[1])) // 2
    d2.multiline_text((x2,y2), ctext, font=smallf, fill=(0,0,0), spacing=20, align="center")
    pages.append(p2)

def add_coloring_pages(pages: List[Image.Image], images_dir: Path, trim_w_in: float, trim_h_in: float, dpi: int, margin_in: float) -> None:
    margin_px = inches_to_px(margin_in, dpi)
    page_w = inches_to_px(trim_w_in, dpi)
    page_h = inches_to_px(trim_h_in, dpi)
    max_w = page_w - 2*margin_px
    max_h = page_h - 2*margin_px

    files = sorted(images_dir.glob("fbnp_*.png"), key=lambda p: int(re.search(r"fbnp_(\d+)\.png", p.name).group(1)))
    if not files:
        raise FileNotFoundError(f"No fbnp_*.png found in {images_dir}")

    for f in files:
        img = Image.open(f).convert("L")
        img = img.convert("RGB")
        # fit image into safe area
        scale = min(max_w / img.width, max_h / img.height)
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        page = new_blank_page(trim_w_in, trim_h_in, dpi)
        px = (page.width - img.width)//2
        py = (page.height - img.height)//2
        page.paste(img, (px, py))
        pages.append(page)

def build_interior(safe_title: str, trim: Tuple[float,float], dpi: int, margin_in: float, no_bleed: bool) -> Path:
    images_dir = Path(f"/mnt/ai_data/ColoringBooks/{safe_title}")
    out_pdf = images_dir / "fbnp_interior.pdf"

    pages: List[Image.Image] = []
    add_front_matter(pages, trim[0], trim[1], dpi)
    add_coloring_pages(pages, images_dir, trim[0], trim[1], dpi, margin_in)

    # Save all pages into one PDF
    first, rest = pages[0], pages[1:]
    first.save(out_pdf, "PDF", resolution=dpi, save_all=True, append_images=rest)

    return out_pdf

def main():
    ap = argparse.ArgumentParser(description="Build a KDP-ready interior PDF for a kids coloring book")
    ap.add_argument("--safe-title", required=True, help="Safe folder name under /mnt/ai_data/ColoringBooks/{safeTitle}/")
    ap.add_argument("--trim", default="8.5x11", help="Trim size in inches, e.g. '8.5x11'")
    ap.add_argument("--dpi", type=int, default=DPI_DEFAULT, help="Target DPI (default 300)")
    ap.add_argument("--margin-in", type=float, default=0.5, help="Margin around content in inches")
    ap.add_argument("--no-bleed", action="store_true", help="Force layout as no-bleed (default for coloring)")
    args = ap.parse_args()

    trim = parse_trim(args.trim)
    out_pdf = build_interior(
        safe_title=args.safe_title,
        trim=trim,
        dpi=args.dpi,
        margin_in=args.margin_in,
        no_bleed=args.no_bleed,
    )

    print(f"✅ Interior built: {out_pdf}")

if __name__ == "__main__":
    main()
