"""Fixtures for database integration tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for testing (testcontainers)."""
    # Import here to avoid hard dependency if not in CI
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    container = PostgresContainer("postgres:16").with_bind_ports(5432, 5432)

    # Start container
    container.start()

    # Get connection string
    dsn = container.get_connection_url()

    yield dsn

    # Cleanup
    container.stop()


@pytest.fixture
def db_with_schema(postgres_container):
    """Create database connection and run schema migrations."""
    import psycopg

    dsn = postgres_container

    # Connect and create tables
    conn = psycopg.connect(dsn)
    cursor = conn.cursor()

    # Read and execute schema from sql/schema.sql
    schema_path = "sql/schema.sql"
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            cursor.execute(f.read())
    conn.commit()

    yield conn

    # Cleanup
    conn.close()
