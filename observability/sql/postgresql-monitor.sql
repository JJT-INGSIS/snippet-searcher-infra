\set ON_ERROR_STOP on
\getenv monitor_password OBS_MONITOR_PASSWORD
CREATE ROLE nri_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'monitor_password';
GRANT CONNECT ON DATABASE :"database" TO nri_monitor;
GRANT pg_read_all_stats TO nri_monitor;
ALTER ROLE nri_monitor SET default_transaction_read_only = on;
ALTER ROLE nri_monitor SET statement_timeout = '2s';
