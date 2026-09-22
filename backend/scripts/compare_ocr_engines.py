"""Compare PaddleOCR vs Tesseract on selected PDF pages (optional operator tool).

Usage:
  set PYTHONPATH=backend
  python backend/scripts/compare_ocr_engines.py --pdf PATH --pages 1,2
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import fitz
from PIL import Image


def _render(page: fitz.Page, dpi: int = 200) -> Image.Image:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--pages", default="1", help="1-based page numbers, comma-separated")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    pages = [int(x) for x in args.pages.split(",") if x.strip()]
    doc = fitz.open(args.pdf)

    from app.document_processing.ocr.paddle_ocr import (
        ocr_pil_image_detailed_paddle,
        paddle_available,
    )
    from app.document_processing.ocr_processor import ocr_pil_image_detailed as tess_ocr

    print(f"pdf={args.pdf} paddle_available={paddle_available()}")
    for pn in pages:
        if pn < 1 or pn > len(doc):
            print(f"skip invalid page {pn}")
            continue
        img = _render(doc[pn - 1], args.dpi)
        print(f"\n=== page {pn} ===")

        if paddle_available():
            t0 = time.perf_counter()
            try:
                paddle = ocr_pil_image_detailed_paddle(img, page_number=pn)
                dt = time.perf_counter() - t0
                print(
                    f"Paddle: {dt:.2f}s conf={paddle.mean_confidence} "
                    f"chars={len(paddle.text)} boxes={len(paddle.boxes)}"
                )
                print("Paddle snippet:", (paddle.text or "")[:400].replace("\n", " | "))
            except Exception as exc:  # noqa: BLE001
                print(f"Paddle FAILED: {exc}")
        else:
            print("Paddle: not available")

        t0 = time.perf_counter()
        try:
            tess = tess_ocr(img)
            dt = time.perf_counter() - t0
            print(
                f"Tesseract: {dt:.2f}s conf={tess.mean_confidence} chars={len(tess.text)}"
            )
            print("Tesseract snippet:", (tess.text or "")[:400].replace("\n", " | "))
        except Exception as exc:  # noqa: BLE001
            print(f"Tesseract FAILED: {exc}")

        # Entity cue check (informational only — no hard-coded expected values)
        blob_p = ""
        blob_t = ""
        if paddle_available():
            try:
                blob_p = ocr_pil_image_detailed_paddle(img, page_number=pn).text.upper()
            except Exception:  # noqa: BLE001
                blob_p = ""
        try:
            blob_t = tess_ocr(img).text.upper()
        except Exception:  # noqa: BLE001
            blob_t = ""
        import re

        for token in ("NLCIL", "CIL"):
            # Word-boundary so CIL does not match inside NLCIL
            pat = re.compile(rf"\b{re.escape(token)}\b", re.I)
            print(
                f"contains {token}: paddle={bool(pat.search(blob_p))} "
                f"tesseract={bool(pat.search(blob_t))}"
            )

    doc.close()


if __name__ == "__main__":
    main()
