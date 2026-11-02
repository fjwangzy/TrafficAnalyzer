#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    --set=app_schema="${APP_DB_SCHEMA:?APP_DB_SCHEMA is required}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS :"app_schema" AUTHORIZATION CURRENT_USER;
SQL
