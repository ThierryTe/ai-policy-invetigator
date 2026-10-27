#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv owner_password OWNER_DB_PASSWORD
\getenv app_password APP_DB_PASSWORD
CREATE ROLE investigator_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE investigator_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'owner_password';
CREATE ROLE investigator_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_password';
GRANT investigator_runtime TO investigator_app;
ALTER DATABASE investigator OWNER TO investigator_owner;
ALTER SCHEMA public OWNER TO investigator_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION vector;
CREATE EXTENSION pgcrypto;
SQL
