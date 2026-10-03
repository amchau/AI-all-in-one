from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ManifestDocument:
    metadata: Mapping[str, str | None]
    source: str
    source_sha256: str
    pdf_name: str
    pdf_sha256: str
    pdf_path: Path


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    ordinal: int
    section: str | None
    clause: str | None
    page: int
    token_count: int
    content_hash: str
    text: str