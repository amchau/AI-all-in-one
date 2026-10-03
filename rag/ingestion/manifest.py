from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from rag.ingestion.models import ManifestDocument


class ManifestError(ValueError):
    """Raised when the ingestion manifest or its PDF artifacts are invalid."""


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
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ManifestError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_metadata(value: Any, doc_index: int) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ManifestError(f"documents[{doc_index}].metadata must be an object")
    missing = sorted(REQUIRED_METADATA - value.keys())
    if missing:
        raise ManifestError(
            f"documents[{doc_index}].metadata is missing: {', '.join(missing)}"
        )

    metadata: dict[str, str | None] = {}
    for field in ("doc_id", "title", "product", "version", "acl"):
        field_value = value[field]
        if not isinstance(field_value, str) or not field_value.strip():
            raise ManifestError(f"documents[{doc_index}].metadata.{field} must be non-empty")
        metadata[field] = field_value.strip()

    doc_type = value["doc_type"]
    if not isinstance(doc_type, str) or doc_type not in DOCUMENT_TYPES:
        raise ManifestError(f"documents[{doc_index}].metadata.doc_type is unsupported")
    metadata["doc_type"] = doc_type

    policy_id = value["policy_id"]
    if policy_id is not None and (not isinstance(policy_id, str) or not policy_id.strip()):
        raise ManifestError(
            f"documents[{doc_index}].metadata.policy_id must be non-empty or null"
        )
    if doc_type in {"policy", "endorsement"} and policy_id is None:
        raise ManifestError(f"documents[{doc_index}] requires policy_id")
    metadata["policy_id"] = policy_id.strip() if isinstance(policy_id, str) else None

    effective_date = value["effective_date"]
    if not isinstance(effective_date, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", effective_date
    ) is None:
        raise ManifestError(
            f"documents[{doc_index}].metadata.effective_date must use YYYY-MM-DD"
        )
    try:
        date.fromisoformat(effective_date)
    except ValueError as error:
        raise ManifestError(
            f"documents[{doc_index}].metadata.effective_date must be a valid YYYY-MM-DD date"
        ) from error
    metadata["effective_date"] = effective_date
    return metadata


def _safe_relative_path(value: Any, field: str, suffix: str | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ManifestError(f"{field} must be a safe relative filename")
    if suffix is not None and path.suffix.lower() != suffix:
        raise ManifestError(f"{field} must end in {suffix}")
    return value


def load_manifest(input_dir: Path) -> list[ManifestDocument]:
    """Load and verify every PDF listed by the Phase 2.1 manifest."""
    manifest_path = input_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read valid manifest at {manifest_path}") from error

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ManifestError("manifest schema_version must be 1")
    entries = manifest.get("documents")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("manifest documents must be a non-empty list")

    root = input_dir.resolve(strict=True)
    documents: list[ManifestDocument] = []
    seen_ids: set[str] = set()
    seen_pdf_names: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"documents[{index}] must be an object")
        metadata = _validate_metadata(entry.get("metadata"), index)
        doc_id = str(metadata["doc_id"])
        if doc_id in seen_ids:
            raise ManifestError(f"duplicate doc_id: {doc_id}")
        seen_ids.add(doc_id)

        source = _safe_relative_path(entry.get("source"), f"documents[{index}].source")
        pdf_name = _safe_relative_path(
            entry.get("pdf"), f"documents[{index}].pdf", suffix=".pdf"
        )
        if "/" in pdf_name or "\\" in pdf_name:
            raise ManifestError(f"documents[{index}].pdf must be a safe relative filename")
        if pdf_name in seen_pdf_names:
            raise ManifestError(f"duplicate PDF filename: {pdf_name}")
        seen_pdf_names.add(pdf_name)

        source_sha256 = _validate_sha256(
            entry.get("source_sha256"), f"documents[{index}].source_sha256"
        )
        pdf_sha256 = _validate_sha256(entry.get("pdf_sha256"), f"documents[{index}].pdf_sha256")
        try:
            pdf_path = (root / pdf_name).resolve(strict=True)
        except OSError as error:
            raise ManifestError(f"PDF file is missing: {pdf_name}") from error
        if pdf_path.parent != root or not pdf_path.is_file():
            raise ManifestError(f"documents[{index}].pdf must resolve inside the input directory")
        actual_hash = sha256(pdf_path.read_bytes()).hexdigest()
        if actual_hash != pdf_sha256:
            raise ManifestError(f"SHA-256 mismatch for {pdf_name}")

        documents.append(
            ManifestDocument(
                metadata=metadata,
                source=source,
                source_sha256=source_sha256,
                pdf_name=pdf_name,
                pdf_sha256=pdf_sha256,
                pdf_path=pdf_path,
            )
        )
    return documents