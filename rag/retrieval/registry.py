from __future__ import annotations

from typing import Any

import psycopg

from rag.retrieval.models import SourceDocument


class PostgresSourceRegistry:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL query DSN is required")
        self._dsn = dsn

    def list_for_policy(self, policy_id: str) -> list[SourceDocument]:
        with psycopg.connect(self._dsn, connect_timeout=3) as connection:
            rows = connection.execute(
                """SELECT id, title, doc_type, product, policy_id,
                          effective_date, version, acl
                   FROM rag.documents
                   WHERE policy_id = %s OR policy_id IS NULL
                   ORDER BY effective_date, id""",
                (policy_id,),
            ).fetchall()
        return [
            SourceDocument(
                doc_id=str(row[0]),
                title=str(row[1]),
                doc_type=str(row[2]),
                product=str(row[3]),
                policy_id=str(row[4]) if row[4] is not None else None,
                effective_date=row[5],
                version=str(row[6]),
                acl=str(row[7]),
            )
            for row in rows
        ]