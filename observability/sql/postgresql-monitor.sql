-- Compatibility candidate: PostgreSQL statistics-role choice is pending Thiago.
-- Run only in isolated QA until that decision and the environment review are complete.
-- Execute explicitly as the database operator, once per separate PostgreSQL instance.
-- psql -v database=snippets (or permissions), password supplied only in environment.
\set ON_ERROR_STOP on
\getenv monitor_password OBS_MONITOR_PASSWORD
CREATE ROLE nri_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'monitor_password';
GRANT CONNECT ON DATABASE :"database" TO nri_monitor;
GRANT pg_read_all_stats TO nri_monitor;
ALTER ROLE nri_monitor SET default_transaction_read_only = on;
ALTER ROLE nri_monitor SET statement_timeout = '2s';
-- No SELECT on application tables, extensions, query monitoring or DDL privileges.
-- Existing credentials are not silently rotated. Rotation is a separate explicit ALTER ROLE.
