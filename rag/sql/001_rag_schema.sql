CREATE TABLE IF NOT EXISTS rag.documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL CHECK (doc_type IN ('policy', 'endorsement', 'procedure', 'regulation')),
    product TEXT NOT NULL,
    policy_id TEXT,
    version TEXT NOT NULL,
    effective_date DATE NOT NULL,
    acl TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    pdf_sha256 CHAR(64) NOT NULL,
    content_fingerprint CHAR(64) NOT NULL,
    embedding_model TEXT NOT NULL,
    object_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag.chunks (
    id UUID PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    section TEXT,
    clause TEXT,
    page INTEGER NOT NULL CHECK (page >= 1),
    token_count INTEGER NOT NULL CHECK (token_count > 0),
    content_hash CHAR(64) NOT NULL,
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON rag.chunks(document_id);

CREATE TABLE IF NOT EXISTS rag.ingestion_runs (
    id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    docs_seen INTEGER NOT NULL DEFAULT 0 CHECK (docs_seen >= 0),
    docs_changed INTEGER NOT NULL DEFAULT 0 CHECK (docs_changed >= 0),
    chunks_written INTEGER NOT NULL DEFAULT 0 CHECK (chunks_written >= 0),
    error_category TEXT
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag.documents'::regclass
          AND conname = 'documents_source_sha256_check'
    ) THEN
        ALTER TABLE rag.documents ADD CONSTRAINT documents_source_sha256_check
            CHECK (source_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag.documents'::regclass
          AND conname = 'documents_pdf_sha256_check'
    ) THEN
        ALTER TABLE rag.documents ADD CONSTRAINT documents_pdf_sha256_check
            CHECK (pdf_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag.documents'::regclass
          AND conname = 'documents_content_fingerprint_check'
    ) THEN
        ALTER TABLE rag.documents ADD CONSTRAINT documents_content_fingerprint_check
            CHECK (content_fingerprint ~ '^[0-9a-f]{64}$');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag.chunks'::regclass
          AND conname = 'chunks_content_hash_check'
    ) THEN
        ALTER TABLE rag.chunks ADD CONSTRAINT chunks_content_hash_check
            CHECK (content_hash ~ '^[0-9a-f]{64}$');
    END IF;
END
$$;
