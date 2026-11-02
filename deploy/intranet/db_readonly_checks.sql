-- Run against the configured production database; every query is read-only.
BEGIN READ ONLY;
SET LOCAL search_path TO drone, public;
SELECT current_database() AS database, current_user AS account,
       current_schema() AS schema, current_setting('search_path') AS search_path;
SELECT current_database() = 'ycx_prod' AS expected_database,
       current_user = 'sysdba' AS expected_account,
       current_schema() = 'drone' AS expected_schema;
SELECT nspname,
       has_schema_privilege(current_user, oid, 'USAGE') AS can_use,
       has_schema_privilege(current_user, oid, 'CREATE') AS can_create
FROM pg_namespace WHERE nspname = 'drone';
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name IN ('timescaledb', 'postgis');
SELECT extname, extversion FROM pg_extension WHERE extname IN ('timescaledb', 'postgis');
SELECT c.relname, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='drone' AND left(c.relname,4)='uav_'
ORDER BY c.relname;
SELECT to_regclass('drone.uav_alembic_version') AS canonical_version_table,
       to_regclass('drone.uav_replay_v2_alembic_version') AS replay_version_table;
COMMIT;
