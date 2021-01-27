import datetime
import os
import uuid
from pathlib import Path

import pytest
import trio
from aiven_monitor import Measure
from aiven_monitor.writer import create_postgres_recorder, load_writer_config
from psycopg2 import sql

"""
These tests require a running Postgres server
and the relevant configuration from writer.ini
"""

writer_config_path = Path(__file__).parent / 'writer.ini'
if os.environ.get('AIVEN_TEST_WRITER_CONFIG_PATH'):
    writer_config_path = Path(os.environ.get('AIVEN_TEST_WRITER_CONFIG_PATH'))

requires_postgres = pytest.mark.skipif(
    not writer_config_path.exists(),
    reason="Postgres must be configured with AIVEN_TEST_WRITER_CONFIG_PATH",
)


@requires_postgres
async def test_postgres_connection():
    base_path = writer_config_path.parent
    writer_config = load_writer_config(writer_config_path)
    recorder = create_postgres_recorder(base_path, writer_config)
    with trio.fail_after(10):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(recorder.start)
            await recorder.wait_for_cursor()
            recorder.cursor.execute('select 1')
            assert recorder.cursor.fetchone() == (1,)


@requires_postgres
async def test_postgres_create_table():
    base_path = writer_config_path.parent
    writer_config = load_writer_config(writer_config_path)
    recorder = create_postgres_recorder(base_path, writer_config)
    with trio.fail_after(10):
        async with trio.open_nursery() as nursery:
            drop_measure_table(recorder)
            nursery.start_soon(recorder.start)
            await recorder.wait_for_cursor()
            recorder.cursor.execute(
                '''
                select count(*) from pg_tables
                where tablename  = %s
                ''',
                (recorder.measure_table,),
            )
            assert recorder.cursor.fetchone() == (1,)


def drop_measure_table(recorder):
    with recorder.create_cursor() as cursor:
        cursor.execute(
            sql.SQL('drop table if exists {measure_table}').format(
                measure_table=sql.Identifier(recorder.measure_table)
            )
        )


@requires_postgres
async def test_postgres_create_measure():
    base_path = writer_config_path.parent
    writer_config = load_writer_config(writer_config_path)
    recorder = create_postgres_recorder(base_path, writer_config)
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2, 3, 4, 5, 6),
        'expected',
        checker_version='1.2.3',
    )
    measure.response_time_secs = 1.23
    measure.response_size_bytes = 456
    measure.status_code = 200
    measure.pattern_was_found = True
    measure.protocol = 'HTTP/2'
    with trio.fail_after(10):
        async with trio.open_nursery() as nursery:
            drop_measure_table(recorder)
            nursery.start_soon(recorder.start)
            await recorder.wait_for_cursor()
            await recorder.record(measure)
            recorder.cursor.close()
            nursery.start_soon(recorder.start)
            await recorder.wait_for_cursor()
            recorder.cursor.execute(
                sql.SQL(
                    '''
                select 
                    measure_id, url, endpoint, start_time,
                    response_time_secs, response_size_bytes, status_code,
                    expected_pattern, pattern_was_found,
                    protocol, checker_version
                from {measure_table}
                '''
                ).format(measure_table=sql.Identifier(recorder.measure_table))
            )
            rows = recorder.cursor.fetchall()
            assert list(map(tuple, rows)) == [
                (
                    measure.measure_id,
                    measure.url,
                    measure.endpoint,
                    measure.start_time,
                    measure.response_time_secs,
                    measure.response_size_bytes,
                    measure.status_code,
                    measure.expected_pattern,
                    measure.pattern_was_found,
                    measure.protocol,
                    measure.checker_version,
                )
            ]
