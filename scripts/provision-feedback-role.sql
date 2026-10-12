BEGIN;

DO $$
BEGIN
    CREATE ROLE claims_feedback LOGIN;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

ALTER ROLE claims_feedback LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

DO $$
DECLARE
    membership RECORD;
BEGIN
    FOR membership IN
        SELECT parent.rolname
        FROM pg_auth_members AS auth_members
        JOIN pg_roles AS parent ON parent.oid = auth_members.roleid
        WHERE auth_members.member = 'claims_feedback'::regrole
    LOOP
        EXECUTE format('REVOKE %I FROM claims_feedback', membership.rolname);
    END LOOP;
END
$$;

SELECT format('GRANT CONNECT ON DATABASE %I TO claims_feedback', current_database()) \gexec
SELECT format('REVOKE CREATE, TEMP ON DATABASE %I FROM claims_feedback', current_database()) \gexec

CREATE SCHEMA IF NOT EXISTS ai_feedback;
ALTER SCHEMA ai_feedback OWNER TO CURRENT_USER;
REVOKE ALL ON SCHEMA ai_feedback FROM PUBLIC, claims_feedback;
GRANT USAGE ON SCHEMA ai_feedback TO claims_feedback;

CREATE TABLE IF NOT EXISTS ai_feedback.feedback (
    feedback_id UUID PRIMARY KEY,
    rating TEXT NOT NULL CHECK (rating IN ('useful', 'needs_review', 'unable_to_assess')),
    reason_tags TEXT[] NOT NULL DEFAULT '{}' CHECK (
        cardinality(reason_tags) <= 5
        AND reason_tags <@ ARRAY['grounding', 'completeness', 'relevance', 'safety', 'other']::TEXT[]
        AND array_position(reason_tags, NULL) IS NULL
        AND array_ndims(reason_tags) IS NOT DISTINCT FROM
            CASE WHEN cardinality(reason_tags) = 0 THEN NULL::INTEGER ELSE 1 END
    ),
    note TEXT CHECK (char_length(note) <= 500),
    workflow_id UUID,
    trace_id TEXT CHECK (
        trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (workflow_id IS NULL OR trace_id IS NULL),
    CHECK (
        cardinality(reason_tags) =
            (CASE WHEN 'grounding' = ANY(reason_tags) THEN 1 ELSE 0 END) +
            (CASE WHEN 'completeness' = ANY(reason_tags) THEN 1 ELSE 0 END) +
            (CASE WHEN 'relevance' = ANY(reason_tags) THEN 1 ELSE 0 END) +
            (CASE WHEN 'safety' = ANY(reason_tags) THEN 1 ELSE 0 END) +
            (CASE WHEN 'other' = ANY(reason_tags) THEN 1 ELSE 0 END)
    )
);

ALTER TABLE ai_feedback.feedback OWNER TO CURRENT_USER;
CREATE INDEX IF NOT EXISTS feedback_created_at_idx ON ai_feedback.feedback (created_at);
REVOKE ALL ON TABLE ai_feedback.feedback FROM PUBLIC, claims_feedback;
GRANT SELECT, INSERT, DELETE ON TABLE ai_feedback.feedback TO claims_feedback;

COMMIT;