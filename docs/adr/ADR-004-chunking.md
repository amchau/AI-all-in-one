# ADR-004 - Document model and chunking strategy

## Status

Accepted (2026-10-01)

## Context

Insurance documents are clause-structured (sections, numbered clauses, endorsements that override
clauses). Answers must cite clause-level sources. Corpus is synthetic.

## Options

| Criterion | Structure-aware (heading/clause) | Fixed token windows | Semantic (embedding-boundary) |
|-----------|------|------|------|
| Citation precision | Clause-level, natural | Arbitrary spans | Variable |
| Retrieval quality | High on structured docs | Baseline | Good on prose |
| Complexity | Parser per format | Trivial | Extra embedding calls |
| Determinism | Yes | Yes | Model-dependent |

Corpus format: author Markdown with front-matter metadata, render to PDF (`reportlab`) and ingest
the PDF, vs ingest Markdown directly.

## Decision

- Structure-aware chunking: split on section headings and clause numbers; cap ~400 tokens;
  overlap only when splitting an oversized clause. Keep `section`, `clause`, `page`.
- Fixed windows kept as an eval baseline.
- Author Markdown, render to PDF, ingest PDF (exercises real parsing); metadata from front-matter
  carried via a sidecar manifest.

## Validation

Eval: structure-aware vs fixed windows on recall@5 and citation accuracy.

## Consequences

- Positive: precise citations; endorsements retrievable as their own clauses.
- Negative: PDF heading detection is heuristic; relies on consistent clause numbering in corpus.
