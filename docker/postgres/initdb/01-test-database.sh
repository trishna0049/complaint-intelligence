#!/bin/sh
# Runs once, when the data volume is first created. Creates the database used by the backend test suite.
# (Extensions such as pgvector and pg_trgm are created by the Alembic migrations, so both databases get them.)
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ${POSTGRES_DB}_test OWNER "$POSTGRES_USER";
EOSQL
