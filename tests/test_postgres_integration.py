import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.postgres import PostgresIngestionRepository


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_postgres_schema_and_source_repository() -> None:
    database_url = os.environ["DATABASE_URL"]

    @contextmanager
    def connection_factory():  # type: ignore[no-untyped-def]
        with psycopg.connect(database_url) as connection:
            yield connection

    source = load_source_registry(Path("config/sources.toml"))[0]
    repository = PostgresIngestionRepository(connection_factory)
    repository.upsert_source(source)

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT authority, access_method, implementation_status
            FROM sources
            WHERE source_id = %s
            """,
            (source.id,),
        )
        assert cursor.fetchone() == (
            source.authority,
            source.access_method.value,
            source.implementation_status.value,
        )
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        assert cursor.fetchone()[0] >= 10
