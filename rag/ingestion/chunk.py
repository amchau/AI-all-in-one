from __future__ import annotations

from hashlib import sha256
import re
from typing import Iterable
import uuid

import tiktoken

from rag.ingestion.models import Chunk, PageText


DEFAULT_MAX_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 60
TOKENIZER_NAME = "cl100k_base"
_CHUNK_NAMESPACE = uuid.UUID("ade24e36-a5bf-53f2-90ca-c6b14aeb8e87")
_CLAUSE_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+(.+?)\s*$")
_SECTION_PATTERN = re.compile(r"^\s*(?:section\s+)?(\d{1,3})\.?\s+(.+?)\s*$", re.IGNORECASE)


def _is_section_heading(line: str) -> re.Match[str] | None:
    if _CLAUSE_PATTERN.match(line):
        return None
    return _SECTION_PATTERN.match(line)


def _text_blocks(
    pages: Iterable[PageText],
) -> list[tuple[str | None, str | None, list[tuple[int, str]]]]:
    blocks: list[tuple[str | None, str | None, list[tuple[int, str]]]] = []
    section: str | None = None
    clause: str | None = None
    lines: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal lines
        if lines:
            blocks.append((section, clause, lines))
            lines = []

    for page in pages:
        for raw_line in page.text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            clause_match = _CLAUSE_PATTERN.match(line)
            section_match = _is_section_heading(line)
            if section_match:
                flush()
                section = section_match.group(1)
                clause = None
                lines.append((page.page, line))
            elif clause_match:
                if clause is not None or not lines:
                    flush()
                clause = clause_match.group(1)
                lines.append((page.page, line))
            else:
                lines.append((page.page, line))
    flush()
    return blocks


def chunk_pages(
    document_id: str,
    pages: Iterable[PageText],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Create deterministic section/clause chunks and split only oversized blocks."""
    if not document_id.strip():
        raise ValueError("document_id must be non-empty")
    if max_tokens <= 0 or overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("token limits must satisfy max_tokens > overlap_tokens >= 0")

    encoding = tiktoken.get_encoding(TOKENIZER_NAME)
    chunks: list[Chunk] = []
    for section, clause, block_lines in _text_blocks(pages):
        text = "\n".join(line for _, line in block_lines).strip()
        encoded = encoding.encode(text)
        decoded_text, token_offsets = encoding.decode_with_offsets(encoded)
        start = 0
        while start < len(encoded):
            end = min(start + max_tokens, len(encoded))
            char_start = token_offsets[start]
            char_end = token_offsets[end] if end < len(encoded) else len(decoded_text)
            raw_piece = decoded_text[char_start:char_end]
            piece = raw_piece.strip()
            while piece and len(encoding.encode(piece)) > max_tokens and end > start + 1:
                end -= 1
                char_end = token_offsets[end] if end < len(encoded) else len(decoded_text)
                raw_piece = decoded_text[char_start:char_end]
                piece = raw_piece.strip()
            if not piece:
                if end >= len(encoded):
                    break
                start = max(start + 1, end - overlap_tokens)
                continue
            page_offset = char_start + len(raw_piece) - len(raw_piece.lstrip())
            line_offset = 0
            chunk_page = block_lines[0][0]
            for page_number, line in block_lines:
                if line_offset > page_offset:
                    break
                chunk_page = page_number
                line_offset += len(line) + 1
            ordinal = len(chunks)
            chunk_id = uuid.uuid5(
                _CHUNK_NAMESPACE, f"{document_id}:{ordinal}"
            )
            chunks.append(
                Chunk(
                    chunk_id=str(chunk_id),
                    document_id=document_id,
                    ordinal=ordinal,
                    section=section,
                    clause=clause,
                    page=chunk_page,
                    token_count=len(encoding.encode(piece)),
                    content_hash=sha256(piece.encode("utf-8")).hexdigest(),
                    text=piece,
                )
            )
            if end >= len(encoded):
                break
            start = max(start + 1, end - overlap_tokens)
    return chunks