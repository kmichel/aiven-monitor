from __future__ import annotations

import configparser
import datetime
import json
import logging
import os
from typing import Optional
from uuid import UUID

import kafka
import kafka.errors
import psycopg2
import psycopg2.extras
import trio
from psycopg2 import sql

from .. import Measure

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

    The config is read from the **AIVEN_MONITOR_CHECKER_CONFIG_PATH**
    environment variable, with a default value of '/run/secrets/writer.ini'.
    """
    logging.basicConfig(level=logging.INFO)
    psycopg2.extras.register_uuid()

    config = configparser.ConfigParser()
    config.read_dict({'writer': DEFAULT_CONFIG})
    config_path = os.environ.get(
        'AIVEN_MONITOR_WRITER_CONFIG_PATH', '/run/secrets/writer.ini'
    )
    config.read(config_path)
    trio.run(async_main, config)


async def async_main(config: configparser.ConfigParser):
    """
    Runs a :class:`KafkaSource` and a :class:`PostgresRecorder` together.

    :param config: The configuration for the :class:`KafkaSource` and the
     :class:`PostgresRecorder`.
    """
    config = config['writer']
    source = KafkaSource(
        config['kafka.bootstrap_servers'],
        config['kafka.topic'],
        config.get('kafka.ssl.cafile'),
        config.get('kafka.ssl.certfile'),
        config.get('kafka.ssl.keyfile'),
        config.getfloat('kafka.connect_interval_secs'),
    )
    password_file = config.get('postgres.passwordfile')
    if password_file is not None:
        with open(password_file) as password_file:
            postgres_password = password_file.read()
    else:
        postgres_password = None
    recorder = PostgresRecorder(
        config['postgres.measure_table'],
        config.get('postgres.host'),
        config.getint('postgres.port'),
        config.get('postgres.user'),
        postgres_password,
        config.get('postgres.database'),
        config.get('postgres.ssl.rootcertfile'),
        config.getfloat('postgres.connect_interval_secs'),
    )
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
            ssl_cafile: Optional[str],
            ssl_certfile: Optional[str],
            ssl_keyfile: Optional[str],
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
        raw_value = self.consumer.__next__().value
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

    _connection_factory = staticmethod(psycopg2.connect)

    def __init__(
            self,
            measure_table: str,
            host: Optional[str],
            port: Optional[int],
            user: Optional[str],
            password: Optional[str],
            database: Optional[str],
            ssl_rootcertfile: Optional[str],
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
        self.connection = None
        self.cursor = None
        self.has_cursor = trio.Condition()
        self.needs_cursor = trio.Condition()

    async def start(self) -> None:
        """
        Connects to the Postgres database.

        If the connection is lost or cannot be established, it will endlessly
        retry while waiting `connect_interval_secs`  between each attempt.
        """
        while True:
            try:
                logger.info(
                    'postgres-connect: host=%s, user=%s, database=%s',
                    self.host,
                    self.user,
                    self.database,
                )
                self.connection = self._connection_factory(
                    sslmode='verify-full',
                    sslrootcert=self.ssl_rootcertfile,
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    dbname=self.database,
                )
                self.cursor = self.connection.cursor()
                self.create_measure_table()
                logger.info('postgres-ready')
                async with self.has_cursor:
                    self.has_cursor.notify_all()
                async with self.needs_cursor:
                    while self.cursor is not None and not self.cursor.closed:
                        await self.needs_cursor.wait()
            except psycopg2.OperationalError:
                logger.exception('postgres-error')
                await trio.sleep(self.connect_interval_secs)

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
                async with self.has_cursor:
                    while self.cursor is None or self.cursor.closed:
                        async with self.needs_cursor:
                            self.needs_cursor.notify_all()
                        await self.has_cursor.wait()
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
            except psycopg2.DatabaseError:
                logger.exception('postgres-error')
                await trio.sleep(self.connect_interval_secs)
                self.cursor = None
            else:
                return

    def create_measure_table(self):
        self.cursor.execute(
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
        self.cursor.execute(
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
