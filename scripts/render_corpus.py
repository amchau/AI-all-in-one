"""Validate synthetic Markdown documents and render them as deterministic PDFs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from hashlib import sha256
from html import escape
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_METADATA = {
    "doc_id",
    "title",
    "doc_type",
    "product",
    "policy_id",
    "version",
    "effective_date",
    "acl",
}
DOCUMENT_TYPES = {"policy", "endorsement", "procedure", "regulation"}
EXPECTED_TYPE_COUNTS = {
    "policy": 3,
    "endorsement": 2,
    "procedure": 2,
    "regulation": 1,
}
DOC_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class CorpusError(ValueError):
    """Raised when corpus content or metadata is invalid."""


@dataclass(frozen=True)
class CorpusDocument:
    metadata: Mapping[str, str | None]
    body: str
    source_path: Path
    source_sha256: str


def parse_document(path: Path) -> CorpusDocument:
    """Parse one Markdown document and validate its front matter."""
    try:
        source_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CorpusError(f"cannot read {path}: {error}") from error

    lines = source_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CorpusError(f"{path}: expected YAML front matter at the start")

    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise CorpusError(f"{path}: front matter has no closing delimiter") from error

    try:
        metadata_value = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as error:
        raise CorpusError(f"{path}: invalid YAML front matter: {error}") from error

    if not isinstance(metadata_value, dict):
        raise CorpusError(f"{path}: front matter must be a mapping")

    missing_fields = sorted(REQUIRED_METADATA - metadata_value.keys())
    if missing_fields:
        raise CorpusError(
            f"{path}: missing required metadata: {', '.join(missing_fields)}"
        )

    metadata = dict(metadata_value)
    for field_name in ("doc_id", "title", "product", "version", "acl"):
        field_value = metadata[field_name]
        if not isinstance(field_value, str) or not field_value.strip():
            raise CorpusError(f"{path}: metadata {field_name} must be a non-empty string")
        metadata[field_name] = field_value.strip()

    doc_id = metadata["doc_id"]
    if DOC_ID_PATTERN.fullmatch(doc_id) is None:
        raise CorpusError(f"{path}: doc_id must contain only letters, digits, '.', '_' or '-'")

    doc_type = metadata["doc_type"]
    if not isinstance(doc_type, str):
        raise CorpusError(f"{path}: doc_type must be a string")
    if doc_type not in DOCUMENT_TYPES:
        raise CorpusError(f"{path}: unsupported doc_type {doc_type!r}")

    policy_id = metadata["policy_id"]
    if policy_id is not None and (not isinstance(policy_id, str) or not policy_id.strip()):
        raise CorpusError(f"{path}: policy_id must be a non-empty string or null")
    if doc_type in {"policy", "endorsement"} and policy_id is None:
        raise CorpusError(f"{path}: {doc_type} documents require policy_id")
    metadata["policy_id"] = policy_id.strip() if isinstance(policy_id, str) else None

    effective_date = metadata["effective_date"]
    if isinstance(effective_date, datetime):
        raise CorpusError(f"{path}: effective_date must be a date, not a timestamp")
    if isinstance(effective_date, date):
        metadata["effective_date"] = effective_date.isoformat()
    elif isinstance(effective_date, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date) is None:
            raise CorpusError(f"{path}: effective_date must use YYYY-MM-DD format")
        try:
            metadata["effective_date"] = date.fromisoformat(effective_date).isoformat()
        except ValueError as error:
            raise CorpusError(f"{path}: effective_date must use YYYY-MM-DD format") from error
    else:
        raise CorpusError(f"{path}: effective_date must use YYYY-MM-DD format")

    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        raise CorpusError(f"{path}: document body must not be empty")

    return CorpusDocument(
        metadata=metadata,
        body=body,
        source_path=path,
        source_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
    )


def load_corpus(source_dir: Path) -> list[CorpusDocument]:
    """Load Markdown documents in stable path order and reject duplicate IDs."""
    if not source_dir.is_dir():
        raise CorpusError(f"corpus directory does not exist: {source_dir}")

    source_paths = sorted(source_dir.rglob("*.md"))
    if not source_paths:
        raise CorpusError(f"no Markdown documents found in {source_dir}")

    documents = [parse_document(path) for path in source_paths]
    document_ids = [document.metadata["doc_id"] for document in documents]
    if len(set(document_ids)) != len(document_ids):
        raise CorpusError("doc_id values must be unique across the corpus")
    return documents


def validate_corpus(documents: list[CorpusDocument]) -> None:
    """Enforce the approved Phase 2.1 corpus size and document mix."""
    actual_counts = Counter(document.metadata["doc_type"] for document in documents)
    if actual_counts != EXPECTED_TYPE_COUNTS:
        raise CorpusError(
            "expected document counts "
            f"{EXPECTED_TYPE_COUNTS}, found {dict(sorted(actual_counts.items()))}"
        )


def _markdown_inline(text: str) -> str:
    escaped = escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)


def _document_story(document: CorpusDocument) -> list[object]:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CorpusTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17324D"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CorpusH1",
            parent=styles["Heading1"],
            textColor=colors.HexColor("#17324D"),
            spaceBefore=14,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CorpusH2",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#245B63"),
            spaceBefore=10,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CorpusMeta",
            parent=styles["Normal"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#56616A"),
            fontSize=9,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CorpusBullet",
            parent=styles["BodyText"],
            leftIndent=14,
        )
    )

    metadata = document.metadata
    story: list[object] = [
        Paragraph(_markdown_inline(str(metadata["title"])), styles["CorpusTitle"]),
        Paragraph(
            _markdown_inline(
                f"{metadata['doc_id']} | {metadata['version']} | "
                f"Effective {metadata['effective_date']}"
            ),
            styles["CorpusMeta"],
        ),
    ]
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            story.append(
                Paragraph(
                    _markdown_inline(" ".join(paragraph_lines)),
                    styles["BodyText"],
                )
            )
            story.append(Spacer(1, 5))
            paragraph_lines.clear()

    for line in document.body.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            style_name = "CorpusH1" if len(heading.group(1)) == 1 else "CorpusH2"
            story.append(Paragraph(_markdown_inline(heading.group(2)), styles[style_name]))
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            flush_paragraph()
            story.append(
                Paragraph(
                    f"- {_markdown_inline(bullet.group(1))}",
                    styles["CorpusBullet"],
                )
            )
            story.append(Spacer(1, 3))
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()
    return story


def _render_document(document: CorpusDocument, output_path: Path) -> None:
    metadata = document.metadata
    document_id = str(metadata["doc_id"])

    def draw_page_footer(pdf_canvas: canvas.Canvas, layout: SimpleDocTemplate) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setFont("Helvetica", 8)
        pdf_canvas.setFillColor(colors.HexColor("#56616A"))
        pdf_canvas.drawString(layout.leftMargin, 0.45 * inch, document_id)
        pdf_canvas.drawRightString(
            A4[0] - layout.rightMargin,
            0.45 * inch,
            f"Page {pdf_canvas.getPageNumber()}",
        )
        pdf_canvas.restoreState()

    def create_canvas(*args: object, **kwargs: object) -> canvas.Canvas:
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        pdf_canvas = canvas.Canvas(*args, **kwargs)
        pdf_canvas.setTitle(str(metadata["title"]))
        pdf_canvas.setAuthor("Synthetic Insurance Knowledge Corpus")
        pdf_canvas.setSubject(
            f"{document_id}; {metadata['doc_type']}; "
            f"{metadata['product']}; effective {metadata['effective_date']}"
        )
        keywords = [
            str(metadata["doc_type"]),
            str(metadata["product"]),
            str(metadata["version"]),
        ]
        if metadata["policy_id"]:
            keywords.append(str(metadata["policy_id"]))
        pdf_canvas.setKeywords(", ".join(keywords))
        return pdf_canvas

    layout = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.75 * inch,
        title=str(metadata["title"]),
        author="Synthetic Insurance Knowledge Corpus",
    )
    layout.build(
        _document_story(document),
        onFirstPage=draw_page_footer,
        onLaterPages=draw_page_footer,
        canvasmaker=partial(create_canvas),
    )


def render_corpus(source_dir: Path, output_dir: Path) -> list[Path]:
    """Render the approved corpus and write its metadata sidecar manifest."""
    documents = load_corpus(source_dir)
    validate_corpus(documents)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_documents: list[dict[str, object]] = []
    output_paths: list[Path] = []
    for document in documents:
        document_id = str(document.metadata["doc_id"])
        pdf_path = output_dir / f"{document_id}.pdf"
        _render_document(document, pdf_path)
        pdf_hash = sha256(pdf_path.read_bytes()).hexdigest()
        manifest_documents.append(
            {
                "metadata": dict(document.metadata),
                "source": document.source_path.relative_to(source_dir).as_posix(),
                "source_sha256": document.source_sha256,
                "pdf": pdf_path.name,
                "pdf_sha256": pdf_hash,
            }
        )
        output_paths.append(pdf_path)

    manifest = {"schema_version": 1, "documents": manifest_documents}
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=REPOSITORY_ROOT / "data",
        help="directory containing corpus Markdown files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "generated",
        help="directory for rendered PDFs and manifest.json",
    )
    arguments = parser.parse_args()

    try:
        output_paths = render_corpus(arguments.source_dir, arguments.output_dir)
    except (CorpusError, OSError, ValueError) as error:
        print(f"Corpus rendering failed: {error}", file=sys.stderr)
        return 1

    print(f"Rendered {len(output_paths)} PDFs and manifest to {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())