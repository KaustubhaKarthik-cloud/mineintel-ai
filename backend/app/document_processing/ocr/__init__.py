"""OCR engine package (PaddleOCR + strategy). Tesseract stays in ocr_processor.py."""

from app.document_processing.ocr.strategy import ocr_pil_image_detailed, resolved_engine

__all__ = ["ocr_pil_image_detailed", "resolved_engine"]
