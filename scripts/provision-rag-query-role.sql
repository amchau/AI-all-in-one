DO $$
BEGIN
    CREATE ROLE rag_query LOGIN;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

ALTER ROLE rag_query LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

DO $$
DECLARE
    membership RECORD;
BEGIN
    FOR membership IN
        SELECT parent.rolname
        FROM pg_auth_members AS auth_members
        JOIN pg_roles AS parent ON parent.oid = auth_members.roleid
        WHERE auth_members.member = 'rag_query'::regrole
    LOOP
        EXECUTE format('REVOKE %I FROM rag_query', membership.rolname);
    END LOOP;
END
$$;

SELECT format('GRANT CONNECT ON DATABASE %I TO rag_query', current_database()) \gexec
-- This dedicated platform database only permits explicitly provisioned logins.
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('REVOKE CREATE ON DATABASE %I FROM rag_query', current_database()) \gexec
SELECT format('REVOKE TEMP ON DATABASE %I FROM rag_query', current_database()) \gexec
-- This dedicated platform database does not need PUBLIC schema-creation access.
SELECT format('REVOKE CREATE ON DATABASE %I FROM PUBLIC', current_database()) \gexec
-- This dedicated platform database does not need PUBLIC temporary-table access.
SELECT format('REVOKE TEMP ON DATABASE %I FROM PUBLIC', current_database()) \gexec
-- Application data is schema-qualified under rag; no runtime role needs public access.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM rag_query;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_shdepend
        WHERE refclassid = 'pg_authid'::regclass
          AND refobjid = 'rag_query'::regrole::oid
          AND deptype = 'o'
          AND (
              dbid = 0
              OR dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
          )
    ) THEN
        RAISE EXCEPTION 'rag_query must not own objects in the current database';
    END IF;
END
$$;

REVOKE ALL ON SCHEMA rag FROM rag_query;
REVOKE ALL ON SCHEMA rag FROM PUBLIC;
GRANT USAGE ON SCHEMA rag TO rag_query;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA rag FROM rag_query;
-- The RAG database is dedicated to this platform; clear inherited relation grants too.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA rag FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA rag FROM rag_query;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA rag FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL ROUTINES IN SCHEMA rag FROM rag_query;
REVOKE ALL PRIVILEGES ON ALL ROUTINES IN SCHEMA rag FROM PUBLIC;
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON TABLES FROM PUBLIC',
    current_user
) \gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON SEQUENCES FROM PUBLIC',
    current_user
) \gexec
SELECT format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE EXECUTE ON ROUTINES FROM PUBLIC',
    current_user
) \gexec
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest
    REVOKE EXECUTE ON ROUTINES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag REVOKE EXECUTE ON ROUTINES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest IN SCHEMA rag
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest IN SCHEMA rag
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rag_ingest IN SCHEMA rag
    REVOKE EXECUTE ON ROUTINES FROM PUBLIC;
DO $$
DECLARE
    relation_column RECORD;
    column_privilege TEXT;
BEGIN
    FOR relation_column IN
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'rag'
    LOOP
        FOREACH column_privilege IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']
        LOOP
            EXECUTE format(
                'REVOKE %s (%I) ON TABLE rag.%I FROM rag_query',
                column_privilege,
                relation_column.column_name,
                relation_column.table_name
            );
            EXECUTE format(
                'REVOKE %s (%I) ON TABLE rag.%I FROM PUBLIC',
                column_privilege,
                relation_column.column_name,
                relation_column.table_name
            );
        END LOOP;
    END LOOP;
END
$$;
GRANT SELECT (id, title, doc_type, product, policy_id, effective_date, version, acl)
    ON rag.documents TO rag_query;