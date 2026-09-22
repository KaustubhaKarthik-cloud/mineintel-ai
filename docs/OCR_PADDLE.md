# PaddleOCR integration (SIH 26023)

MineIntel keeps **Tesseract** and adds **PaddleOCR** as a configurable primary engine for scanned PDFs and images. Native/text PDFs still use embedded text only (no OCR).

## Install (existing project venv)

From the repo root, using `backend/.venv`:

```powershell
$py = ".\backend\.venv\Scripts\python.exe"

# CPU PaddlePaddle (official mirror)
& $py -m pip install --default-timeout=600 "paddlepaddle==3.2.2" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

# PaddleOCR (+ document/table extras via paddlex)
& $py -m pip install --default-timeout=600 "paddleocr==3.7.0"

# Verify
& $py -c "import paddle; import paddleocr; print('paddle', paddle.__version__); print('paddleocr ok')"
```

Optional extras file (does not replace core `requirements.txt`):

```powershell
& $py -m pip install -r .\backend\requirements-ocr-paddle.txt
```

Revert OCR code (not packages) from backup:

```powershell
Copy-Item .\backend\app\document_processing\_backup_pre_paddle\*.py .\backend\app\document_processing\ -Force
# then restore config.py from the same backup folder if needed
```

## Start backend

```powershell
.\start-backend.ps1
# or
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## OCR engine selection

Set in `.env` (project root or `backend/.env`) or the environment:

| Variable | Default | Meaning |
|---|---|---|
| `OCR_ENGINE` | `paddle` | Primary: `paddle` \| `tesseract` \| `auto` |
| `OCR_FALLBACK` | `tesseract` | Fallback: `tesseract` \| `paddle` \| `none` |
| `OCR_TABLE_ENGINE` | `existing` | `existing` = PyMuPDF `structured_table` (primary). `paddle` = optional PP-Structure **assist** only |
| `PADDLE_OCR_LANG` | `en` | Paddle language code |
| `OCR_MIN_USABLE_CHARS` | `8` | If primary returns fewer chars, try fallback |

Example:

```env
OCR_ENGINE=paddle
OCR_FALLBACK=tesseract
OCR_TABLE_ENGINE=existing
```

## Pipeline after the change

```
Native/text PDF  →  PyMuPDF get_text  →  pages (no OCR)
Scanned/image PDF → render page → OCR strategy (Paddle → Tesseract)
                 → content_meta: ocr_engine, ocr_mean_confidence, ocr_boxes
                 → existing chunking / structured_table / evidence / review
Image upload     → same OCR strategy
```

## Tables

- **Primary** remains `app.retrieval.structured_table` (PyMuPDF `find_tables`, header-first facts).
- If `OCR_TABLE_ENGINE=paddle` and PP-Structure is installed, assistive table hints may be stored under `content_meta.ocr_table_assist`.
- On any failure or empty assist output, the existing extractor is unchanged.

## Evidence / review

OCR pages store provenance in `DocumentPage.content_meta`:

- `ocr_engine`, `ocr_mean_confidence`, `ocr_boxes` (when provided)
- `source_location` like `page:N:ocr`

Geological `review_required` facts still enqueue into the shared Review Queue (`GET /api/reviews`).

## Tests

```powershell
$env:PYTHONPATH = "C:\Users\karth\mineintel-ai\backend"
.\backend\.venv\Scripts\python.exe -m pytest tests/test_ocr_paddle_strategy.py tests/test_phase2_ingestion.py -q
.\backend\.venv\Scripts\python.exe -m pytest tests -q
```

For live comparison on a local scanned PDF (optional script):

```powershell
$env:PYTHONPATH = ".\backend"
.\backend\.venv\Scripts\python.exe .\backend\scripts\compare_ocr_engines.py --pdf PATH\to\scan.pdf --pages 1,2
```
