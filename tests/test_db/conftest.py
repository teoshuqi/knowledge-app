"""Fixtures for database integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for testing (testcontainers)."""
    # Import here to avoid hard dependency if not in CI
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    # No fixed host port: testcontainers assigns a free one and
    # get_connection_url() below returns it - a hardcoded 5432 conflicts
    # with any other local Postgres already using that port.
    container = PostgresContainer("postgres:16")

    # Start container
    container.start()

    # driver=None: plain postgresql:// URL. The default includes a
    # SQLAlchemy-style "+psycopg2" driver suffix that psycopg3's connect()
    # (used everywhere else in this codebase) can't parse.
    dsn = container.get_connection_url(driver=None)

    # Apply the schema once here, not per-test: db_with_schema is
    # function-scoped but this container is session-scoped, and
    # CREATE TABLE isn't idempotent - re-running it per test against the
    # same container raises DuplicateTable on the second test.
    import psycopg

    with psycopg.connect(dsn) as conn, open("sql/migrations/001_initial_schema.sql") as f:
        conn.execute(f.read())

    yield dsn

    # Cleanup
    container.stop()


@pytest.fixture
def db_with_schema(postgres_container):
    """Connection to the schema-loaded test database (see postgres_container)."""
    import psycopg

    conn = psycopg.connect(postgres_container)
    yield conn
    conn.close()
