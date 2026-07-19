from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OcrOutput:
    text: str
    confidence: float | None = None
    width: int | None = None
    height: int | None = None
    warnings: list[str] = field(default_factory=list)


class OcrAdapter:
    def is_available(self) -> bool:
        return False

    def extract_image(self, image_path: str | Path) -> OcrOutput:
        raise RuntimeError("OCR adapter is not available")

    def extract_pdf_page(self, pdf_path: str | Path, page_number: int) -> OcrOutput:
        raise RuntimeError("OCR adapter is not available for PDF pages")

    def version(self) -> str:
        return "ocr-unavailable"


class OptionalTesseractOcrAdapter(OcrAdapter):
    def __init__(self, language: str = "vie+eng", tesseract_cmd: str | None = None):
        self.language = language
        self._pytesseract = None
        self._image = None
        self._image_ops = None
        self._image_filter = None
        self._fitz = None
        self._tesseract_cmd = tesseract_cmd
        try:
            import pytesseract
            from PIL import Image, ImageFilter, ImageOps

            self._pytesseract = pytesseract
            self._image = Image
            self._image_filter = ImageFilter
            self._image_ops = ImageOps
        except Exception:
            return
        try:
            import fitz

            self._fitz = fitz
        except Exception:
            self._fitz = None
        if not self._tesseract_cmd:
            self._tesseract_cmd = shutil.which("tesseract")
        if self._tesseract_cmd:
            try:
                self._pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
            except Exception:
                pass

    def is_available(self) -> bool:
        return bool(self._pytesseract is not None and self._image is not None and self._tesseract_cmd)

    def version(self) -> str:
        if not self.is_available():
            return "ocr-unavailable"
        try:
            version = str(self._pytesseract.get_tesseract_version())
        except Exception:
            version = "unknown"
        return f"tesseract:{version}:lang={self.language}"

    def extract_image(self, image_path: str | Path) -> OcrOutput:
        if not self.is_available():
            raise RuntimeError("Tesseract OCR is not available")
        image = self._image.open(str(image_path))
        prepared = self._preprocess(image)
        text = self._pytesseract.image_to_string(prepared, lang=self.language, config="--oem 3 --psm 6")
        return OcrOutput(text=text or "", width=getattr(image, "width", None), height=getattr(image, "height", None))

    def extract_pdf_page(self, pdf_path: str | Path, page_number: int) -> OcrOutput:
        if not self.is_available() or self._fitz is None:
            raise RuntimeError("Tesseract/PyMuPDF OCR is not available for PDF pages")
        doc = self._fitz.open(str(pdf_path))
        try:
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=self._fitz.Matrix(2.0, 2.0), alpha=False)
            image = self._image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            prepared = self._preprocess(image)
            text = self._pytesseract.image_to_string(prepared, lang=self.language, config="--oem 3 --psm 6")
            return OcrOutput(text=text or "", width=pix.width, height=pix.height)
        finally:
            doc.close()

    def _preprocess(self, image):
        if not (self._image_ops and self._image_filter):
            return image
        prepared = image.convert("L")
        prepared = self._image_ops.autocontrast(prepared)
        prepared = prepared.resize((max(prepared.width * 2, 1), max(prepared.height * 2, 1)))
        prepared = prepared.filter(self._image_filter.SHARPEN)
        return prepared
