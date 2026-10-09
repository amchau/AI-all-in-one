DO $$
BEGIN
    CREATE ROLE claims_workflow LOGIN;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

ALTER ROLE claims_workflow LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

DO $$
DECLARE
    membership RECORD;
BEGIN
    FOR membership IN
        SELECT parent.rolname
        FROM pg_auth_members AS auth_members
        JOIN pg_roles AS parent ON parent.oid = auth_members.roleid
        WHERE auth_members.member = 'claims_workflow'::regrole
    LOOP
        EXECUTE format('REVOKE %I FROM claims_workflow', membership.rolname);
    END LOOP;
END
$$;

SELECT format('GRANT CONNECT ON DATABASE %I TO claims_workflow', current_database()) \gexec
SELECT format('REVOKE CREATE ON DATABASE %I FROM claims_workflow', current_database()) \gexec
SELECT format('REVOKE TEMP ON DATABASE %I FROM claims_workflow', current_database()) \gexec

CREATE SCHEMA IF NOT EXISTS claims_workflow;
ALTER SCHEMA claims_workflow OWNER TO CURRENT_USER;
REVOKE ALL ON SCHEMA claims_workflow FROM PUBLIC;
GRANT USAGE ON SCHEMA claims_workflow TO claims_workflow;

CREATE TABLE IF NOT EXISTS claims_workflow.workflows (
    workflow_id UUID PRIMARY KEY,
    claim_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'created', 'investigating', 'awaiting_human_review',
            'needs_more_information', 'completed', 'failed', 'cancelled'
        )
    ),
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    request_payload JSONB,
    result JSONB,
    error_code TEXT CHECK (
        error_code IN ('stage6_dependency_failed', 'stage6_response_invalid', 'worker_interrupted')
        OR error_code IS NULL
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE claims_workflow.workflows ALTER COLUMN request_payload DROP NOT NULL;

CREATE INDEX IF NOT EXISTS claims_workflow_state_created_idx
    ON claims_workflow.workflows (created_at)
    WHERE state = 'created';

CREATE TABLE IF NOT EXISTS claims_workflow.events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES claims_workflow.workflows(workflow_id),
    from_state TEXT,
    state TEXT NOT NULL,
    action TEXT NOT NULL,
    disposition TEXT CHECK (disposition IN ('continue', 'request_info', 'stop') OR disposition IS NULL),
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    trace_id CHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE claims_workflow.events ADD COLUMN IF NOT EXISTS trace_id CHAR(32);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'claims_workflow.events'::regclass
          AND conname = 'claims_workflow_events_trace_id_check'
    ) THEN
        ALTER TABLE claims_workflow.events
            ADD CONSTRAINT claims_workflow_events_trace_id_check
            CHECK (trace_id ~ '^[0-9a-f]{32}$' OR trace_id IS NULL);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS claims_workflow_events_history_idx
    ON claims_workflow.events (workflow_id, event_id);

CREATE TABLE IF NOT EXISTS claims_workflow.idempotency (
    workflow_id UUID NOT NULL REFERENCES claims_workflow.workflows(workflow_id),
    idempotency_key TEXT NOT NULL,
    fingerprint CHAR(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workflow_id, idempotency_key)
);

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA claims_workflow FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA claims_workflow FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON claims_workflow.workflows TO claims_workflow;
GRANT SELECT, INSERT ON claims_workflow.events TO claims_workflow;
GRANT SELECT, INSERT ON claims_workflow.idempotency TO claims_workflow;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA claims_workflow TO claims_workflow;