# ColoringBook\_CoverBuilder

Tools for generating professional, KDP‑ready coloring book files (cover + interior).

## Features

* **cover\_builder.py**

  * Generates a full wraparound cover (back + spine + front) with bleed at 300 DPI.
  * Automatically computes spine width based on page count and paper type.
  * Places 2–5 sample interior pages (tilted “mini sheets”) on front and back covers.
  * Large, playful title font with optional spine text.
  * Back cover description block with reserved white box for barcode.
  * Outputs:

    * `fbnp_cover.png` (preview)
    * `fbnp_cover.pdf` (print‑ready for KDP)

* **interior\_builder.py**

  * Scans a folder of interior PNGs (`fbnp_*.png`).
  * Creates a PDF interior sized to trim size (default 8.5"×11" at 300 DPI).
  * Adds front matter pages:

    * Page 1: “This Book Belongs To”
    * Page 2: Copyright / brand text
  * Centers each coloring page with safe margins (default 0.5").
  * Outputs:

    * `fbnp_interior.pdf`

## Requirements

* Python 3.9+
* [Pillow](https://python-pillow.org/)
* [ImageMagick](https://imagemagick.org/) (for best PDF output from covers)
* Fonts: Place playful TTF fonts under `fonts/` or rely on system fonts.

Install dependencies:

```bash
pip install pillow
sudo apt-get install -y imagemagick fonts-dejavu-core
```

## File Structure

```
/mnt/ai_data/ColoringBooks/{safeTitle}/
├── fbnp_1.png
├── fbnp_2.png
├── ...
├── fbnp_cover.pdf
└── fbnp_interior.pdf
```

## Usage

### Cover Builder

```bash
python cover_builder.py \
  --safe-title "Cute_Dinosaurs" \
  --title "Cute Dinosaurs Coloring Book for Kids" \
  --description "Includes 30 fun illustrations..." \
  --pages 30 \
  --paper white \
  --trim 8.5x11 \
  --max-images 4 \
  --spine-title "Cute Dinosaurs Coloring Book" \
  --bg gradient:pastel:1 \
  --seed 42
```

### Interior Builder

```bash
python interior_builder.py \
  --safe-title "Cute_Dinosaurs" \
  --trim 8.5x11 \
  --dpi 300 \
  --margin-in 0.5 \
  --no-bleed
```

## Output

* **Interior**: `fbnp_interior.pdf`
* **Cover**: `fbnp_cover.pdf`

Upload both files to KDP when creating your paperback.

## Notes

* Default trim size is 8.5"×11" (standard for kids coloring books).
* Spine text only appears when `pages ≥ 79`.
* KDP previewer must show no bleed/margin errors before publishing.
* Cover background can be solid color (`#RRGGBB`) or gradient preset (`gradient:pastel:1`).

## License

Internal use, © 2025 Fantasy Broadcast Network.
