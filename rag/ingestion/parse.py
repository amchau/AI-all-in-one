from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from rag.ingestion.models import PageText


class PdfParseError(ValueError):
    """Raised when a PDF cannot provide usable text for ingestion."""


def extract_pdf_pages(pdf_path: Path) -> list[PageText]:
    """Extract text in physical page order, preserving one-based page numbers."""
    try:
        reader = PdfReader(str(pdf_path), strict=True)
        pages = [
            PageText(page=index, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        ]
    except Exception as error:
        raise PdfParseError(f"cannot parse PDF {pdf_path.name}") from error

    if not pages or not any(page.text.strip() for page in pages):
        raise PdfParseError(f"PDF {pdf_path.name} has no extractable text")
    return pages