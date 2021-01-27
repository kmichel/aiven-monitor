from __future__ import annotations

import argparse
import datetime
import json
import logging
from configparser import SectionProxy
from pathlib import Path
from typing import Optional, Union
from uuid import UUID

import kafka
import kafka.errors
import psycopg2
import psycopg2.extras
import trio
from psycopg2 import sql

from .. import ConfigFileNotFound, Measure, load_config, resolve_path

logger = logging.getLogger('aiven-monitor-writer')

DEFAULT_CONFIG = {
    'kafka.bootstrap_servers': 'localhost',
    'kafka.topic': 'aiven_monitor_measure',
    'kafka.connect_interval_secs': '1',
    'postgres.measure_table': 'aiven_monitor_measure',
    'postgres.connect_interval_secs': '1',
}


def main():
    """
    Configures the logging at :attr:`loging.INFO` level and starts the
    :func:`async_main` function using `trio`.
    """
    try:
        parser = argparse.ArgumentParser(
            description='''Collects measures generated by aiven-monitor-checker
    into a Kafka topic and records them in a Postgres database.'''
        )
        parser.add_argument(
            '--config',
            type=str,
            default='writer.ini',
            help='''path to the config file.
            absolute or relative to the current working directory.
            defaults to "writer.ini".''',
        )
        arguments = parser.parse_args()
        logging.basicConfig(level=logging.INFO)
        config_path = Path(arguments.config).absolute()
        logger.info(f'Using config file: {str(config_path)!r}')
        try:
            config = load_writer_config(config_path)
        except ConfigFileNotFound as e:
            logger.error(str(e))
            return -1
        else:
            trio.run(async_main, config_path.parent, config)
    except KeyboardInterrupt:
        return 0


def load_writer_config(config_path: Union[str, Path]) -> SectionProxy:
    return load_config('writer', DEFAULT_CONFIG, config_path)


def create_kafka_source(base_path: Path, config: SectionProxy) -> KafkaSource:
    return KafkaSource(
        config['kafka.bootstrap_servers'],
        config['kafka.topic'],
        resolve_path(base_path, config.get('kafka.ssl.cafile')),
        resolve_path(base_path, config.get('kafka.ssl.certfile')),
        resolve_path(base_path, config.get('kafka.ssl.keyfile')),
        config.getfloat('kafka.connect_interval_secs'),
    )


def create_postgres_recorder(
        base_path: Path, config: SectionProxy
) -> PostgresRecorder:
    password_file = resolve_path(base_path, config.get('postgres.passwordfile'))
    if password_file is not None:
        with open(password_file) as password_file:
            postgres_password = password_file.read().rstrip('\n')
    else:
        postgres_password = None
    return PostgresRecorder(
        config['postgres.measure_table'],
        config.get('postgres.host'),
        config.getint('postgres.port'),
        config.get('postgres.user'),
        postgres_password,
        config.get('postgres.database'),
        resolve_path(base_path, config.get('postgres.ssl.rootcertfile')),
        config.getfloat('postgres.connect_interval_secs'),
    )


async def async_main(base_path: Path, config: SectionProxy):
    """
    Runs a :class:`KafkaSource` and a :class:`PostgresRecorder` together.

    :param base_path: The reference directory used to resolve relative paths
     in the configuration.
    :param config: The configuration for the :class:`KafkaSource` and the
     :class:`PostgresRecorder`.
    """
    source = create_kafka_source(base_path, config)
    recorder = create_postgres_recorder(base_path, config)
    async with trio.open_nursery() as nursery:
        # We're only doing async here to handle (re)connections easily,
        # the message polling and recording itself is still sync so don't
        # expect this to work very nicely in collaboration with other code.
        nursery.start_soon(source.start)
        nursery.start_soon(recorder.start)
        while True:
            measure = await source.get_measure()
            await recorder.record(measure)


class KafkaSource:
    """
    A Kafka consumer that produces :class:`aiven_monitor.Measure` objects.

    The measures found in the Kafka topic are expected to be  serialized as
    UTF-8 encoded Json dicts. See :func:`aiven_monitor.Measure.to_dict` for the
    exact format.

    :param bootstrap_servers: A comma-separated list of Kafka servers.
    :param topic: The Kafka topic from which the :class:`aiven_monitor.Measure``
     objects are read.
    :param ssl_cafile: The path to the PEM certificate of the certificate
     authority used to authenticate the Kafka servers.
    :param ssl_certfile: The path to the PEM certificate used to authenticate
     this consumer.
    :param ssl_keyfile: The path to the PEM private key used to authenticate
     this consumer.
    :param connect_interval_secs: The number of seconds before retrying to
     connect.
    """

    _consumer_factory = kafka.KafkaConsumer

    def __init__(
            self,
            bootstrap_servers: str,
            topic: str,
            ssl_cafile: Optional[Union[str, Path]],
            ssl_certfile: Optional[Union[str, Path]],
            ssl_keyfile: Optional[Union[str, Path]],
            connect_interval_secs: float = 1.0,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.ssl_cafile = ssl_cafile
        self.ssl_certfile = ssl_certfile
        self.ssl_keyfile = ssl_keyfile
        self.connect_interval_secs = connect_interval_secs
        self.consumer = None
        self.has_consumer = trio.Condition()

    async def start(self) -> None:
        """
        Starts the Kafka consumer.

        If the connection cannot be established, it will endlessly retry while
        waiting `connect_interval_secs`  between each attempt.
        """
        while self.consumer is None:
            try:
                self.consumer = self._consumer_factory(
                    self.topic,
                    bootstrap_servers=self.bootstrap_servers,
                    ssl_cafile=self.ssl_cafile,
                    ssl_certfile=self.ssl_certfile,
                    ssl_keyfile=self.ssl_keyfile,
                    security_protocol='SSL',
                    # This isn't pretty but it doesn't actually changes the
                    # internal polling done by python-kafka , it only allows
                    # the timeout to surface up to get_measure()
                    consumer_timeout_ms=500,
                )
            except kafka.errors.NoBrokersAvailable:
                await trio.sleep(self.connect_interval_secs)
            else:
                async with self.has_consumer:
                    self.has_consumer.notify_all()

    async def get_measure(self) -> Measure:
        """
        Fetches a single measure from Kafka.

        Because this requires a working Kafka connection, this function will
        not return until the connection is established.

        It is not an error to call :func:`get_measure` before or while calling
        :func:`start` . However, this means that if :func:`get_measure` is
        called as a coroutine and not directly awaited, pending measures
        and coroutines can accumulate in memory until the connection is
        established.
        """
        async with self.has_consumer:
            while self.consumer is None:
                await self.has_consumer.wait()
        logger.info('measure-get')
        while True:
            try:
                raw_value = self.consumer.__next__().value
            except StopIteration:
                # That's where we use the consumer_timeout_ms we previously
                # set on the kafka.KafkaConsumer to allow us to "regularly"
                # yield control to another coroutine. This confirms that doing
                # async code with sync libraries was a great idea.
                await trio.sleep(0)
            else:
                return Measure.from_dict(json.loads(raw_value.decode('utf-8')))


class PostgresRecorder:
    """
    Takes :class:`aiven_monitor.Measure` objects and records them in a Postgres
    `measure_table`.

    :param measure_table: The name of the table where measures are stored.
    :param host: The hostname of the Postgres server.
    :param port: The port of the Postgres server.
    :param user: The user name to connect to the Postgres server.
    :param password: The password associated with the specified user.
    :param database: The database inside the Postgres server.
    :param ssl_rootcertfile: The path to the PEM certificate of the certificate
     authority used to authenticate the Postgres server.
    :param connect_interval_secs: The number of seconds before retrying to
     connect.
    """

    @staticmethod
    def _connection_factory(*args, **kwargs):
        connection = psycopg2.connect(*args, **kwargs)
        connection.set_session(autocommit=True)
        psycopg2.extras.register_uuid(conn_or_curs=connection)
        return connection

    def __init__(
            self,
            measure_table: str,
            host: Optional[str],
            port: Optional[int],
            user: Optional[str],
            password: Optional[str],
            database: Optional[str],
            ssl_rootcertfile: Optional[Union[str, Path]],
            connect_interval_secs: float = 1.0,
    ):
        self.measure_table = measure_table
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.ssl_rootcertfile = ssl_rootcertfile
        self.connect_interval_secs = connect_interval_secs
        self.cursor = None
        self.has_cursor = trio.Condition()

    async def start(self) -> None:
        """
        Connects to the Postgres database.

        If the connection is lost or cannot be established, it will endlessly
        retry while waiting `connect_interval_secs`  between each attempt.
        """
        while self.cursor is None or self.cursor.closed:
            try:
                logger.info(
                    'postgres-connect: host=%s, user=%s, database=%s',
                    self.host,
                    self.user,
                    self.database,
                )
                self.cursor = self.create_cursor()
                self.create_measure_table(self.cursor)
                logger.info('postgres-ready')
                async with self.has_cursor:
                    self.has_cursor.notify_all()
            except psycopg2.OperationalError as e:
                logger.error('postgres-error: %s', e)
                await trio.sleep(self.connect_interval_secs)

    def create_cursor(self):
        connection = self._connection_factory(
            sslmode='verify-full',
            sslrootcert=self.ssl_rootcertfile,
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
        )
        cursor = connection.cursor()
        cursor.execute('set statement_timeout=5000')
        return cursor

    async def wait_for_cursor(self):
        async with self.has_cursor:
            while self.cursor is None or self.cursor.closed:
                await self.has_cursor.wait()

    async def record(self, measure: Measure) -> None:
        """
        Records a :class:`aiven_monitor.Measure` in Postgres.

        This waits for the measure to be actually recorded.

        Because this requires a working Postgres connection, this function will
        not return until the connection is established.

        It is not an error to call :func:`record` before or while calling
        :func:`start` . However, this means that if :func:`record` is called as
        a coroutine and not directly awaited, pending measures and coroutines
        can accumulate in memory until the connection is established.
        """
        while True:
            try:
                await self.wait_for_cursor()
                logger.info('measure-record: %s', measure.to_dict())
                self.add_measure(
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
            except psycopg2.DatabaseError as e:
                logger.exception('postgres-error: %s', e)
                await trio.sleep(self.connect_interval_secs)
                self.cursor = None
                await self.start()
            else:
                return

    def create_measure_table(self, cursor):
        cursor.execute(
            sql.SQL(
                '''
                create table if not exists {measure_table} (
                    measure_id uuid primary key,
                    url varchar not null,
                    endpoint varchar not null,
                    start_time timestamp without time zone not null,
                    response_time_secs real,
                    response_size_bytes integer,
                    status_code integer,
                    expected_pattern varchar,
                    pattern_was_found boolean,
                    protocol varchar,
                    checker_version varchar
                )
                '''
            ).format(measure_table=sql.Identifier(self.measure_table))
        )
        measure_index = f'{self.measure_table}_url_start_time'
        cursor.execute(
            sql.SQL(
                '''
                create index if not exists {measure_index} on {measure_table}
                (url, start_time)
                '''
            ).format(
                measure_index=sql.Identifier(measure_index),
                measure_table=sql.Identifier(self.measure_table),
            )
        )

    def add_measure(
            self,
            measure_id: UUID,
            url: str,
            endpoint: str,
            start_time: datetime.datetime,
            response_time_secs: Optional[float],
            response_size_bytes: Optional[int],
            status_code: Optional[int],
            expected_pattern: Optional[str],
            pattern_was_found: Optional[bool],
            protocol: Optional[str],
            checker_version: str,
    ):
        self.cursor.execute(
            sql.SQL(
                '''
                insert into {measure_table}
                (measure_id, url, endpoint, start_time,
                response_time_secs, response_size_bytes, status_code,
                expected_pattern, pattern_was_found,
                protocol, checker_version)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict do nothing
                '''
            ).format(measure_table=sql.Identifier(self.measure_table)),
            (
                measure_id,
                url,
                endpoint,
                start_time,
                response_time_secs,
                response_size_bytes,
                status_code,
                expected_pattern,
                pattern_was_found,
                protocol,
                checker_version,
            ),
        )
