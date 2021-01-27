import configparser
import datetime
import json
import tempfile
import uuid
from pathlib import Path
from unittest import mock

import kafka.errors
import psycopg2
import trio
from aiven_monitor import Measure
from aiven_monitor.writer import (
    KafkaSource,
    PostgresRecorder,
    create_kafka_source,
    create_postgres_recorder,
)


def test_create_kafka_source():
    kafka_source = KafkaSource(
        'localhost', 'topic', '/tmp/cafile', '/tmp/certfile', '/tmp/keyfile'
    )
    assert kafka_source.bootstrap_servers == 'localhost'
    assert kafka_source.topic == 'topic'
    assert kafka_source.ssl_cafile == '/tmp/cafile'
    assert kafka_source.ssl_certfile == '/tmp/certfile'
    assert kafka_source.ssl_keyfile == '/tmp/keyfile'


def test_create_kafka_source_from_config():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            'test': {
                'kafka.bootstrap_servers': 'localhost',
                'kafka.topic': 'topic',
                'kafka.ssl.cafile': 'relative/cafile',
                'kafka.ssl.certfile': '/absolute/certfile',
                'kafka.ssl.keyfile': '../bare_keyfile',
                'kafka.connect_interval_secs': '5'
            }
        }
    )
    kafka_source = create_kafka_source(Path('/foo/bar'), config['test'])
    assert kafka_source.bootstrap_servers == 'localhost'
    assert kafka_source.topic == 'topic'
    assert kafka_source.ssl_cafile == Path('/foo/bar/relative/cafile')
    assert kafka_source.ssl_certfile == Path('/absolute/certfile')
    assert kafka_source.ssl_keyfile == Path('/foo/bar/../bare_keyfile')
    assert kafka_source.connect_interval_secs == 5.0


def test_create_kafka_source_from_partial_config():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            'test': {
                'kafka.bootstrap_servers': 'localhost',
                'kafka.topic': 'topic',
            }
        }
    )
    kafka_source = create_kafka_source(Path('/foo/bar'), config['test'])
    assert kafka_source.bootstrap_servers == 'localhost'
    assert kafka_source.topic == 'topic'
    assert kafka_source.ssl_cafile is None
    assert kafka_source.ssl_certfile is None
    assert kafka_source.ssl_keyfile is None
    assert kafka_source.connect_interval_secs is None


async def test_kafka_source_start_creates_consumer():
    kafka_source = KafkaSource('localhost', 'topic', None, None, None)
    kafka_source._consumer_factory = mock.MagicMock(
        spec_set=kafka_source._consumer_factory
    )
    await kafka_source.start()
    assert kafka_source.consumer == kafka_source._consumer_factory.return_value


async def test_source_start_retries_on_error(autojump_clock):
    kafka_source = KafkaSource('localhost', 'topic-measures', None, None, None)
    kafka_source._consumer_factory = mock.MagicMock()
    kafka_source._consumer_factory.side_effect = (
        kafka.errors.NoBrokersAvailable()
    )
    with trio.move_on_after(kafka_source.connect_interval_secs * 5):
        await kafka_source.start()
    assert kafka_source._consumer_factory.call_count == 5


async def test_kafka_source_get_measure():
    kafka_source = KafkaSource('localhost', 'topic', None, None, None)
    kafka_source.consumer = mock.MagicMock()
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        None,
    )
    encoded_measure = json.dumps(measure.to_dict()).encode()
    kafka_source.consumer.__next__.return_value.value = encoded_measure
    measure = await kafka_source.get_measure()
    assert measure.measure_id == measure.measure_id


async def test_kafka_source_get_measure_waits_for_consumer(autojump_clock):
    kafka_source = KafkaSource('localhost', 'topic', None, None, None)
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        None,
    )
    encoded_measure = json.dumps(measure.to_dict()).encode()
    start_time = trio.current_time()

    kafka_source._consumer_factory = mock.MagicMock()
    kafka_source._consumer_factory.return_value.__next__.return_value.value = (
        encoded_measure
    )

    async def wait_and_start():
        await trio.sleep(10)
        await kafka_source.start()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_and_start)
        await kafka_source.get_measure()
    assert trio.current_time() >= start_time + 10
    kafka_source.consumer.__next__.assert_called_once()


def test_create_postgres_recorder():
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    assert postgres_recorder.measure_table == 'measure_table'
    assert postgres_recorder.host == 'host'
    assert postgres_recorder.port == 5432
    assert postgres_recorder.user == 'user'
    assert postgres_recorder.password == 'password'
    assert postgres_recorder.database == 'database'
    assert postgres_recorder.ssl_rootcertfile == '/tmp/rootcert'


def test_create_postgres_recorder_from_config():
    with tempfile.NamedTemporaryFile() as password_file:
        password_file.write(b'hello\n')
        password_file.flush()
        config = configparser.ConfigParser()
        config.read_dict(
            {
                'test': {
                    'postgres.measure_table': 'measure_table',
                    'postgres.host': 'host',
                    'postgres.port': 1234,
                    'postgres.user': 'admin',
                    'postgres.passwordfile': password_file.name,
                    'postgres.database': 'defaultdb',
                    'postgres.ssl.rootcertfile': 'certfile',
                    'postgres.connect_interval_secs': '5'
                }
            }
        )
        postgres_recorder = create_postgres_recorder(
            Path('/foo/bar'), config['test']
        )
        assert postgres_recorder.measure_table == 'measure_table'
        assert postgres_recorder.host == 'host'
        assert postgres_recorder.port == 1234
        assert postgres_recorder.user == 'admin'
        assert postgres_recorder.password == 'hello'
        assert postgres_recorder.database == 'defaultdb'
        assert postgres_recorder.ssl_rootcertfile == Path('/foo/bar/certfile')
        assert postgres_recorder.connect_interval_secs == 5.0


def test_create_postgres_recorder_from_partial_config():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            'test': {
                'postgres.measure_table': 'measure_table',
            }
        }
    )
    postgres_recorder = create_postgres_recorder(
        Path('/foo/bar'), config['test']
    )
    assert postgres_recorder.measure_table == 'measure_table'
    assert postgres_recorder.host is None
    assert postgres_recorder.port is None
    assert postgres_recorder.user is None
    assert postgres_recorder.password is None
    assert postgres_recorder.database is None
    assert postgres_recorder.ssl_rootcertfile is None
    assert postgres_recorder.connect_interval_secs is None


async def test_postgres_recorder_start_creates_cursor(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    cursor = mock.MagicMock()
    cursor.closed = False
    connection = mock.MagicMock()
    connection.cursor.return_value = cursor
    postgres_recorder._connection_factory = mock.MagicMock()
    postgres_recorder._connection_factory.return_value = connection
    async with trio.open_nursery() as nursery:
        nursery.start_soon(postgres_recorder.start)
        with trio.fail_after(1):
            while postgres_recorder.cursor is None:
                async with postgres_recorder.has_cursor:
                    await postgres_recorder.has_cursor.wait()
        postgres_recorder._connection_factory.assert_called_once_with(
            sslmode='verify-full',
            sslrootcert='/tmp/rootcert',
            host='host',
            port=5432,
            user='user',
            password='password',
            dbname='database',
        )
        assert postgres_recorder.cursor == cursor


async def test_postgres_recorder_start_retries_on_error(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    postgres_recorder._connection_factory = mock.MagicMock()
    postgres_recorder._connection_factory.side_effect = (
        psycopg2.OperationalError()
    )
    with trio.move_on_after(postgres_recorder.connect_interval_secs * 6):
        await postgres_recorder.start()
    assert postgres_recorder._connection_factory.call_count == 6


async def test_postgres_recorder_start_creates_table(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    cursor = mock.MagicMock()
    cursor.closed = False
    connection = mock.MagicMock()
    connection.cursor.return_value = cursor
    postgres_recorder._connection_factory = mock.MagicMock()
    postgres_recorder._connection_factory.return_value = connection
    postgres_recorder.create_measure_table = mock.MagicMock()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(postgres_recorder.start)
        with trio.fail_after(1):
            while postgres_recorder.cursor is None:
                async with postgres_recorder.has_cursor:
                    await postgres_recorder.has_cursor.wait()
        postgres_recorder.create_measure_table.assert_called_once()


async def test_postgres_recorder_record_inserts_measure(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    postgres_recorder.cursor = mock.MagicMock()
    postgres_recorder.cursor.closed = False
    postgres_recorder.add_measure = mock.MagicMock()
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        r'pattern',
    )
    measure.response_time_secs = 0.2
    measure.response_size_bytes = 123
    measure.status_code = 200
    measure.pattern_was_found = False
    measure.protocol = 'HTTP/2'
    await postgres_recorder.record(measure)
    postgres_recorder.add_measure.assert_called_once_with(
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


async def test_postgres_recorder_record_waits_for_cursor(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    postgres_recorder.add_measure = mock.MagicMock()
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        None,
    )
    start_time = trio.current_time()

    async def wait_and_start():
        await trio.sleep(10)
        postgres_recorder.cursor = mock.MagicMock()
        postgres_recorder.cursor.closed = False
        async with postgres_recorder.has_cursor:
            postgres_recorder.has_cursor.notify_all()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_and_start)
        await postgres_recorder.record(measure)
    assert trio.current_time() >= start_time + 10
    postgres_recorder.add_measure.assert_called_once()


async def test_postgres_recorder_record_retries_on_error(autojump_clock):
    # That's very basic, more in-depth tests are done with a real database
    postgres_recorder = PostgresRecorder(
        'measure_table',
        'host',
        5432,
        'user',
        'password',
        'database',
        '/tmp/rootcert',
    )
    cursor = mock.MagicMock()
    cursor.closed = False
    connection = mock.MagicMock()
    connection.cursor.return_value = cursor
    postgres_recorder._connection_factory = mock.MagicMock()
    postgres_recorder._connection_factory.return_value = connection
    counter = 4

    def fail_four_times(*args):
        nonlocal counter
        if counter > 0:
            counter -= 1
            raise psycopg2.DatabaseError()

    postgres_recorder.add_measure = mock.MagicMock()
    postgres_recorder.add_measure.side_effect = fail_four_times
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        None,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(postgres_recorder.start)
        await postgres_recorder.record(measure)
    assert postgres_recorder.add_measure.call_count == 5
