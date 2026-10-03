from __future__ import annotations

import os

import httpx
import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege
from qdrant_client import QdrantClient


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RAG_QUERY_INTEGRATION") != "1",
    reason="set RUN_RAG_QUERY_INTEGRATION=1 with query API and local services available",
)


def test_dense_query_returns_grounded_citations_without_writes() -> None:
    api_url = os.getenv("RAG_QUERY_API_URL", "http://127.0.0.1:8000")
    postgres_dsn = os.getenv("POSTGRES_QUERY_DSN", "")
    qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    if not postgres_dsn:
        pytest.fail("POSTGRES_QUERY_DSN is required for the query integration test")

    qdrant = QdrantClient(url=qdrant_url, timeout=10)
    try:
        with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
            current_user = connection.execute("SELECT current_user").fetchone()[0]
            assert current_user == "rag_query"
            schema_usage, schema_create, public_schema_usage, public_schema_create, database_create, database_temp = connection.execute(
                "SELECT has_schema_privilege(current_user, 'rag', 'USAGE'), "
                "has_schema_privilege(current_user, 'rag', 'CREATE'), "
                "has_schema_privilege(current_user, 'public', 'USAGE'), "
                "has_schema_privilege(current_user, 'public', 'CREATE'), "
                "has_database_privilege(current_user, current_database(), 'CREATE'), "
                "has_database_privilege(current_user, current_database(), 'TEMP')"
            ).fetchone()
            public_connect = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_database AS db "
                "CROSS JOIN LATERAL aclexplode(COALESCE(db.datacl, acldefault('d', db.datdba))) AS acl "
                "WHERE db.datname = current_database() AND acl.grantee = 0 "
                "AND acl.privilege_type = 'CONNECT')"
            ).fetchone()[0]
            assert schema_usage is True
            assert schema_create is False
            assert public_schema_usage is False
            assert public_schema_create is False
            assert database_create is False
            assert database_temp is False
            assert public_connect is False
            public_default_privileges = connection.execute(
                "WITH creator_roles(role_oid) AS ("
                "SELECT datdba FROM pg_database WHERE datname = current_database() UNION "
                "SELECT 'rag_ingest'::regrole::oid), "
                "object_types(object_type) AS (VALUES "
                "('r'::\"char\"), ('S'::\"char\"), ('f'::\"char\")), "
                "global_acl_sets AS ("
                "SELECT COALESCE(defaults.defaclacl, "
                "acldefault(object_types.object_type, creator_roles.role_oid)) AS privileges "
                "FROM creator_roles CROSS JOIN object_types "
                "LEFT JOIN pg_default_acl AS defaults "
                "ON defaults.defaclrole = creator_roles.role_oid "
                "AND defaults.defaclnamespace = 0 "
                "AND defaults.defaclobjtype = object_types.object_type), "
                "all_acl_sets AS (SELECT privileges FROM global_acl_sets UNION ALL "
                "SELECT defaults.defaclacl FROM pg_default_acl AS defaults "
                "JOIN creator_roles ON creator_roles.role_oid = defaults.defaclrole "
                "WHERE defaults.defaclnamespace = 'rag'::regnamespace "
                "AND defaults.defaclobjtype IN ('r', 'S', 'f')) "
                "SELECT EXISTS (SELECT 1 FROM all_acl_sets "
                "CROSS JOIN LATERAL aclexplode(privileges) AS acl WHERE acl.grantee = 0)"
            ).fetchone()[0]
            assert public_default_privileges is False
            public_object_privileges = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_class AS object "
                "JOIN pg_namespace AS namespace ON namespace.oid = object.relnamespace "
                "CROSS JOIN LATERAL aclexplode(COALESCE(object.relacl, "
                "acldefault(CASE WHEN object.relkind = 'S' THEN 'S'::\"char\" "
                "ELSE 'r'::\"char\" END, object.relowner))) AS acl "
                "WHERE namespace.nspname = 'rag' "
                "AND object.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND acl.grantee = 0) "
                "OR EXISTS (SELECT 1 FROM pg_proc AS routine "
                "JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace "
                "CROSS JOIN LATERAL aclexplode(COALESCE(routine.proacl, "
                "acldefault('f', routine.proowner))) AS acl "
                "WHERE namespace.nspname = 'rag' AND acl.grantee = 0)"
            ).fetchone()[0]
            assert public_object_privileges is False
            owns_database_objects = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_shdepend "
                "WHERE refclassid = 'pg_authid'::regclass "
                "AND refobjid = current_user::regrole::oid AND deptype = 'o' "
                "AND (dbid = 0 OR dbid = "
                "(SELECT oid FROM pg_database WHERE datname = current_database())))"
            ).fetchone()[0]
            assert owns_database_objects is False
            table_columns = {
                "documents": [
                    "id", "title", "doc_type", "product", "policy_id", "version",
                    "effective_date", "acl", "source_path", "source_sha256", "pdf_sha256",
                    "content_fingerprint", "embedding_model", "object_key", "created_at",
                    "updated_at",
                ],
                "chunks": [
                    "id", "document_id", "ordinal", "section", "clause", "page",
                    "token_count", "content_hash",
                ],
                "ingestion_runs": [
                    "id", "started_at", "finished_at", "status", "docs_seen", "docs_changed",
                    "chunks_written", "error_category",
                ],
            }
            readable_document_columns = {
                "id", "title", "doc_type", "product", "policy_id", "effective_date",
                "version", "acl",
            }
            for table_name, columns in table_columns.items():
                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    allowed = connection.execute(
                        "SELECT has_table_privilege(current_user, %s, %s)",
                        (f"rag.{table_name}", privilege),
                    ).fetchone()[0]
                    assert allowed is False
                for column_name in columns:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                        allowed = connection.execute(
                            "SELECT has_column_privilege(current_user, %s, %s, %s)",
                            (f"rag.{table_name}", column_name, privilege),
                        ).fetchone()[0]
                        expected = (
                            table_name == "documents"
                            and column_name in readable_document_columns
                            and privilege == "SELECT"
                        )
                        assert allowed is expected
            for sequence in connection.execute(
                "SELECT c.oid FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'rag' AND c.relkind = 'S'"
            ).fetchall():
                for privilege in ("USAGE", "SELECT", "UPDATE"):
                    allowed = connection.execute(
                        "SELECT has_sequence_privilege(current_user, %s, %s)",
                        (sequence[0], privilege),
                    ).fetchone()[0]
                    assert allowed is False
            for routine in connection.execute(
                "SELECT p.oid FROM pg_proc AS p "
                "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'rag'"
            ).fetchall():
                allowed = connection.execute(
                    "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
                    (routine[0],),
                ).fetchone()[0]
                assert allowed is False
            documents_before = connection.execute(
                "SELECT COUNT(id) FROM rag.documents"
            ).fetchone()[0]

        with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
            with pytest.raises(InsufficientPrivilege):
                connection.execute(
                    "UPDATE rag.documents SET title = title WHERE false"
                )
        with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
            with pytest.raises(InsufficientPrivilege):
                connection.execute("SELECT source_sha256 FROM rag.documents LIMIT 1")
        points_before = qdrant.count("insurance_docs", exact=True).count

        response = httpx.post(
            f"{api_url.rstrip('/')}/v1/rag/query",
            json={
                "question": "What water damage is covered under policy HOME-002?",
                "policy_id": "HOME-002",
                "loss_date": "2025-03-01",
                "guidance_as_of": "2026-01-01",
                "top_k": 5,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["status"] == "answered"
        assert payload["answer"]
        assert payload["citations"]
        chunks_by_id = {chunk["chunk_id"]: chunk for chunk in payload["chunks"]}
        refs_by_chunk_id = {
            chunk["chunk_id"]: chunk["ref"] for chunk in payload["chunks"]
        }
        assert chunks_by_id
        for citation in payload["citations"]:
            assert citation["chunk_id"] in chunks_by_id
            assert citation["ref"] == refs_by_chunk_id[citation["chunk_id"]]
            assert f"[{citation['ref']}]" in payload["answer"]

        with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
            documents_after = connection.execute(
                "SELECT COUNT(id) FROM rag.documents"
            ).fetchone()[0]
        points_after = qdrant.count("insurance_docs", exact=True).count
        assert documents_after == documents_before
        assert points_after == points_before
    finally:
        qdrant.close()