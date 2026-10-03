DO $$
BEGIN
    CREATE ROLE rag_ingest LOGIN;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

ALTER ROLE rag_ingest LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

DO $$
DECLARE
    membership RECORD;
BEGIN
    FOR membership IN
        SELECT parent.rolname
        FROM pg_auth_members AS auth_members
        JOIN pg_roles AS parent ON parent.oid = auth_members.roleid
        WHERE auth_members.member = 'rag_ingest'::regrole
    LOOP
        EXECUTE format('REVOKE %I FROM rag_ingest', membership.rolname);
    END LOOP;
END
$$;

SELECT format('GRANT CONNECT ON DATABASE %I TO rag_ingest', current_database()) \gexec
SELECT format('REVOKE CREATE ON DATABASE %I FROM rag_ingest', current_database()) \gexec
SELECT format('REVOKE TEMP ON DATABASE %I FROM rag_ingest', current_database()) \gexec
-- This is a dedicated platform database; remove the default temp privilege from PUBLIC.
SELECT format('REVOKE TEMP ON DATABASE %I FROM PUBLIC', current_database()) \gexec

CREATE SCHEMA IF NOT EXISTS rag;
ALTER SCHEMA rag OWNER TO CURRENT_USER;