-- The test suite drops and rebuilds the `public` schema at session start, so it must run
-- against its own database, never the dev one (POSTGRES_DB). Runs once, on first container init.
CREATE DATABASE acme_test;
