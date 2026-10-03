DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'rag'
    LOOP
        EXECUTE format('ALTER TABLE rag.%I OWNER TO CURRENT_USER', table_name);
    END LOOP;
END
$$;

REVOKE ALL ON SCHEMA rag FROM rag_ingest;
REVOKE ALL ON SCHEMA rag FROM PUBLIC;
GRANT USAGE ON SCHEMA rag TO rag_ingest;
REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM rag_ingest;
REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM PUBLIC;
REVOKE SELECT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, created_at, updated_at
), INSERT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key
), UPDATE (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, created_at, updated_at
), REFERENCES (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, created_at, updated_at
) ON rag.documents FROM PUBLIC;
REVOKE SELECT (id, document_id, ordinal, section, clause, page, token_count, content_hash),
    INSERT (id, document_id, ordinal, section, clause, page, token_count, content_hash),
    UPDATE (id, document_id, ordinal, section, clause, page, token_count, content_hash),
    REFERENCES (id, document_id, ordinal, section, clause, page, token_count, content_hash)
    ON rag.chunks FROM PUBLIC;
REVOKE SELECT (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category),
    INSERT (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category),
    UPDATE (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category),
    REFERENCES (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category)
    ON rag.ingestion_runs FROM PUBLIC;
REVOKE SELECT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, created_at, updated_at
) ON rag.documents FROM rag_ingest;
REVOKE INSERT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key
) ON rag.documents FROM rag_ingest;
REVOKE UPDATE (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, created_at, updated_at
) ON rag.documents FROM rag_ingest;
REVOKE SELECT (id, document_id, ordinal, section, clause, page, token_count, content_hash)
    ON rag.chunks FROM rag_ingest;
REVOKE INSERT (id, document_id, ordinal, section, clause, page, token_count, content_hash)
    ON rag.chunks FROM rag_ingest;
REVOKE SELECT (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category)
    ON rag.ingestion_runs FROM rag_ingest;
REVOKE INSERT (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category)
    ON rag.ingestion_runs FROM rag_ingest;
REVOKE UPDATE (id, started_at, finished_at, status, docs_seen, docs_changed, chunks_written, error_category)
    ON rag.ingestion_runs FROM rag_ingest;
GRANT SELECT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key, updated_at
) ON rag.documents TO rag_ingest;
GRANT INSERT (
    id, title, doc_type, product, policy_id, version, effective_date, acl,
    source_path, source_sha256, pdf_sha256, content_fingerprint, embedding_model,
    object_key
) ON rag.documents TO rag_ingest;
GRANT UPDATE (
    title, doc_type, product, policy_id, version, effective_date, acl, source_path,
    source_sha256, pdf_sha256, content_fingerprint, embedding_model, object_key,
    updated_at
) ON rag.documents TO rag_ingest;
GRANT SELECT (id, document_id, content_hash, page, ordinal) ON rag.chunks TO rag_ingest;
GRANT INSERT (id, document_id, ordinal, section, clause, page, token_count, content_hash)
    ON rag.chunks TO rag_ingest;
GRANT DELETE ON rag.chunks TO rag_ingest;
GRANT SELECT (id) ON rag.ingestion_runs TO rag_ingest;
GRANT INSERT (id, status, docs_seen) ON rag.ingestion_runs TO rag_ingest;
GRANT UPDATE (status, finished_at, docs_seen, docs_changed, chunks_written, error_category)
    ON rag.ingestion_runs TO rag_ingest;