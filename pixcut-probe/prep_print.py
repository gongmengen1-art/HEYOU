#!/usr/bin/env python3
"""
Standardize a cutout (transparent-bg subject) into a fixed-size, centered sticker
composited on the paper canvas, ready for the PixCut S1.

Outputs:
  out/print.jpg   - RGB on white, baseline JPEG, = paper px size (what gets printed)
  out/cut_src.png - RGBA, subject on transparent, same canvas (input to plt cutter)

Geometry: subject is cropped to its alpha bbox, scaled to FIT inside a fixed
target box (default 3x3in = 900x900px) preserving aspect, then centered on the
paper canvas (default 4x7in = 1200x2100px). This is the "fixed size, centered,
won't exceed the sheet" behavior.
"""
import sys
from PIL import Image

DPI = 300
PAPER_IN = (4, 7)        # 4x7 photo paper
STICKER_IN = (3, 3)      # fixed sticker box, centered
SRC = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/xiaomengen/work/vscode/heyou/pixcut-probe/samples/sample_4x7_print.png"
OUTDIR = "/Users/xiaomengen/work/vscode/heyou/pixcut-probe/out"

import os
os.makedirs(OUTDIR, exist_ok=True)

canvas_w, canvas_h = PAPER_IN[0] * DPI, PAPER_IN[1] * DPI      # 1200 x 2100
box_w, box_h = STICKER_IN[0] * DPI, STICKER_IN[1] * DPI        # 900 x 900

img = Image.open(SRC).convert("RGBA")
print(f"source: {SRC}  {img.size}  mode RGBA")

# Analyze alpha: is there a real transparent background to find the subject?
alpha = img.getchannel("A")
bbox = alpha.getbbox()                         # bbox of non-zero alpha
amin, amax = alpha.getextrema()
print(f"alpha extrema: {amin}..{amax}   alpha bbox: {bbox}")

if bbox is None or amin == amax == 255:
    # Fully opaque (no usable cutout) -> fall back to whole image as subject.
    print("WARNING: alpha is fully opaque; using whole image as the subject "
          "(no real cutout). Cut path will be the image rectangle.")
    subject = img
else:
    subject = img.crop(bbox)
print(f"subject (cropped): {subject.size}")

# Scale subject to FIT inside the fixed sticker box, preserve aspect.
sw, sh = subject.size
scale = min(box_w / sw, box_h / sh)
new = (max(1, round(sw * scale)), max(1, round(sh * scale)))
subject = subject.resize(new, Image.LANCZOS)
print(f"subject scaled to fit {box_w}x{box_h} box: {subject.size}  (scale={scale:.4f})")

# Center on canvas.
ox = (canvas_w - subject.size[0]) // 2
oy = (canvas_h - subject.size[1]) // 2
print(f"placed at offset ({ox},{oy}) on {canvas_w}x{canvas_h} canvas (centered)")

# cut_src.png: subject on transparent canvas (for the cut-path generator).
cut_src = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
cut_src.paste(subject, (ox, oy), subject)
cut_src.save(f"{OUTDIR}/cut_src.png")

# print.jpg: flatten on white, RGB, baseline JPEG.
print_img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
print_img.paste(subject, (ox, oy), subject)
print_img.save(f"{OUTDIR}/print.jpg", "JPEG", quality=92, optimize=True)

import os as _os
print(f"\nwrote {OUTDIR}/print.jpg  ({_os.path.getsize(OUTDIR+'/print.jpg')} bytes, {canvas_w}x{canvas_h})")
print(f"wrote {OUTDIR}/cut_src.png ({_os.path.getsize(OUTDIR+'/cut_src.png')} bytes)")
