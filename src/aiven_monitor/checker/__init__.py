from __future__ import annotations

import datetime
import heapq
import json
import logging
import os
import random
import re
from configparser import ConfigParser, SectionProxy
from pathlib import Path
from typing import Iterable, Optional, Union
from uuid import uuid4

import httpx
import kafka
import kafka.errors
import trio
from httpx._decoders import TextDecoder

from .. import Measure, VERSION, resolve_path

USER_AGENT = f'aiven-monitor/${VERSION}'
REQUEST_TIMEOUT_SECS = 60.0
RESPONSE_MAX_BYTES = 1024 * 1024

DEFAULT_CONFIG = {
    'endpoint': 'default',
    'kafka.bootstrap_servers': 'localhost',
    'kafka.topic': 'aiven_monitor_measure',
    'kafka.connect_interval_secs': '1',
}

logger = logging.getLogger('aiven-monitor-checker')


def main():
    """
    Configures the logging at :attr:`logging.INFO` level and starts the
    :func:`async_main` function using `trio`.

    The configuration path is read from the
    **AIVEN_MONITOR_CHECKER_CONFIG_PATH** environment variable, with a default
    value of '/run/secrets/checker.ini'.
    """
    logging.basicConfig(level=logging.INFO)
    config_path = Path(
        os.environ.get(
            'AIVEN_MONITOR_CHECKER_CONFIG_PATH', '/run/secrets/checker.ini'
        )
    )
    config = load_checker_config(config_path)
    trio.run(async_main, config_path.parent, config)


def load_checker_config(config_path: Union[str, Path]) -> SectionProxy:
    config = ConfigParser()
    config.read_dict({'checker': DEFAULT_CONFIG})
    config.read(config_path)
    return config['checker']


def create_kafka_recorder(
        base_path: Path, config: SectionProxy
) -> KafkaRecorder:
    return KafkaRecorder(
        config['kafka.bootstrap_servers'],
        config['kafka.topic'],
        resolve_path(base_path, config.get('kafka.ssl.cafile')),
        resolve_path(base_path, config.get('kafka.ssl.certfile')),
        resolve_path(base_path, config.get('kafka.ssl.keyfile')),
        config.getfloat('kafka.connect_interval_secs'),
    )


async def async_main(base_path: Path, config: SectionProxy):
    """
    Starts a :class:`Scheduler` and a :class:`KafkaRecorder` together.

    :param base_path: The reference path used to resolve relative paths
     in the configuration.
    :param config: The configuration for the :class:`KafkaRecorder`.
    """
    scheduler = Scheduler()
    recorder = create_kafka_recorder(base_path, config)
    async with trio.open_nursery() as nursery:
        try:
            # TODO: what should be the source of the 'config' ?
            await scheduler.add(
                [
                    Probe(
                        'https://www.aiven.io',
                        20,
                        r'Perf.?rmant|\bFree\b|Scalable',
                    ),
                    Probe('https://www.google.fr', 20, 'Lucky'),
                    Probe('https://www.github.com', 20),
                ]
            )
            nursery.start_soon(recorder.start)
            while True:
                probe = await scheduler.get_next()
                nursery.start_soon(
                    probe.check, recorder, config.get('endpoint')
                )
        finally:
            recorder.flush()


class Probe:
    """
    The monitoring configuration for a single Url.
    """

    def __init__(
            self,
            url: str,
            interval_secs: float,
            expected_pattern: Optional[str] = None,
    ):
        if not interval_secs > 0:
            raise ValueError(
                f'interval_secs must be strictly positive, not {interval_secs!r}'
            )
        self.url: str = url
        """The Url this :class:`Probe` will check."""
        self.interval_secs: float = interval_secs
        """The approximate interval between two checks.
        
        This must be strictly positive.
        
        See :class:`Schedule` for details about the scheduling logic."""
        self.expected_pattern: Optional[re.Pattern] = (
            None if expected_pattern is None else re.compile(expected_pattern)
        )
        """ An optional regular expression to search in the response."""

    def __repr__(self):
        interval_secs = self.interval_secs
        expected_pattern = (
            None
            if self.expected_pattern is None
            else self.expected_pattern.pattern
        )
        return f'Probe({self.url!r}, interval_secs={interval_secs!r}, expected_pattern={expected_pattern!r})'

    async def check(self, recorder: KafkaRecorder, endpoint: str) -> None:
        """
        Runs a new HTTP(s) request on the configured URL and records probing
        results in a :class:`aiven_monitor.Measure`.

        HTTP/1.1 and HTTP/2 are both supported.

        :param recorder: A recorder to handle the Measure.
        :param endpoint: A name for the place from where this check is running.
        """
        # While sharing a Client over many probes would be more efficient, it's
        # probably better to not skew the results by using pooled connections
        # between distinct probes and between runs of the same probe.
        async with httpx.AsyncClient(
                http2=True, headers={'user-agent': USER_AGENT}
        ) as client:
            logger.info('probe-check: %s', self)
            expected_pattern = (
                None
                if self.expected_pattern is None
                else self.expected_pattern.pattern
            )
            measure = Measure(
                self.url,
                uuid4(),
                endpoint,
                datetime.datetime.utcnow(),
                expected_pattern,
            )
            with trio.move_on_after(REQUEST_TIMEOUT_SECS):
                async with client.stream('GET', self.url) as response:
                    measure.protocol = response.http_version
                    measure.status_code = response.status_code
                    chunks = []
                    response_size_bytes = 0
                    async for chunk in response.aiter_bytes():
                        # Make sure trio has the opportunity to check timeouts
                        await trio.sleep(0)
                        # We only record the content if we need it
                        allowed_bytes = RESPONSE_MAX_BYTES - response_size_bytes
                        expects_pattern = self.expected_pattern is not None
                        if expects_pattern and allowed_bytes > 0:
                            # Make sure we stop at RESPONSE_MAX_BYTES without
                            # being affected by the exact size of each chunk.
                            # Beware, we wil cut a multi-byte character in half.
                            chunk = chunk[:allowed_bytes]
                            chunks.append(chunk)
                        response_size_bytes += len(chunk)
                        if response_size_bytes >= RESPONSE_MAX_BYTES:
                            break
                    await response.aclose()
                    redirections_time_secs = sum(
                        r.elapsed.total_seconds() for r in response.history
                    )
                    measure.response_time_secs = (
                            response.elapsed.total_seconds()
                            + redirections_time_secs
                    )
                    measure.response_size_bytes = response_size_bytes
                    if self.expected_pattern is not None:
                        try:
                            # I wish we didn't call protected httpx code here
                            # but it's better than rewriting and testing their
                            # decoder, and this separates the concerns of
                            # handling large vs. malformed responses.
                            text_chunks = []
                            decoder = TextDecoder(encoding=response.encoding)
                            for chunk in chunks:
                                text_chunks.append(decoder.decode(chunk))
                            text_chunks.append(decoder.flush())
                        except ValueError as value_error:
                            # TODO: Put that in the measure instead
                            logger.error('response-error: %s', str(value_error))
                        else:
                            content = ''.join(text_chunks)
                            match = self.expected_pattern.search(content)
                            measure.pattern_was_found = match is not None
            await recorder.record(measure)


class Scheduler:
    """
    Elects which :class:`Probe` object must be run next.

    Internally, each added :class:`Probe` is wrapped in a :class:`Schedule`.
    """

    def __init__(self):
        self.queue = []
        self.index = {}
        self.queue_changed = trio.Condition()

    async def add(self, probes: Iterable[Probe]) -> None:
        """
        Adds a list of probes.

        Each one of them will be scheduled to be run somewhere between
        :func:`trio.current_time` and :func:`trio.current_time` +
        :attr:`Probe.interval_secs`.
        """
        for probe in probes:
            logger.info('probe-add: %s', probe)
            schedule = Schedule(probe, trio.current_time())
            self.index[probe] = schedule
            heapq.heappush(self.queue, schedule)
        async with self.queue_changed:
            self.queue_changed.notify()

    async def remove(self, probes: Iterable[Probe]) -> None:
        """
        Removes a list of probes.

        It is not an error to try to remove a probe that was not previously
        added.
        """
        for probe in probes:
            schedule = self.index.pop(probe, None)
            if schedule is not None:
                logger.info('probe-remove: %s', schedule.probe)
                # We mark a schedule as removed here and ignore it later
                schedule.removed = True
        async with self.queue_changed:
            self.queue_changed.notify()

    async def get_next(self) -> Probe:
        """
        Returns the next probe that must be run immediately.

        If the earliest available probe needs to be run later, this will
        internally wait until it's time to run the probe.

        If the scheduling queue changes while waiting, the earliest scheduled
        probe will be re-elected immediately. This means that you can
        concurrently add and remove probes and not wait until it's time to run
        the previously elected probe.

        If the scheduling queue is empty, this will wait until something is
        added to the queue.
        """
        schedule: Optional[Schedule] = None
        while schedule is None:
            try:
                # Try to get the earliest scheduled probe
                schedule = self.queue[0]
            except IndexError:
                # If there is none, wait for a change
                async with self.queue_changed:
                    await self.queue_changed.wait()
            else:
                # Wait until it's time to run the scheduled probe
                with trio.move_on_at(schedule.next_time):
                    # However, if the queue changes before it's time to run,
                    # we forget the selected schedule to re-elect a new one.
                    async with self.queue_changed:
                        await self.queue_changed.wait()
                    schedule = None
                # Just before running it, check if it's not actually removed
                if schedule is not None and schedule.removed:
                    heapq.heappop(self.queue)
                    schedule = None
        # Immediately reschedule the next run of the selected probe
        schedule.advance()
        heapq.heapreplace(self.queue, schedule)
        # Then let the caller actually run the elected probe
        return schedule.probe


class Schedule:
    """
    Maintains the scheduling state of each :class:`Probe` inside a
    :class:`Scheduler`.

    The :class:`Scheduler` picks the :class:`Schedule` with the least
    :attr:`next_time` first.
    """

    def __init__(self, probe: Probe, base_time: float):
        self.probe: Probe = probe
        """The scheduled :class:`Probe`."""
        self.base_time: float = base_time
        """The earliest time the :class:`Probe` is allowed to be scheduled.
        
        This changes each time :func:`advance` is called."""
        self.next_time: float = self._generate_next_time()
        """The actual time the :class:`Probe` is scheduled.
        
        This is always between :attr:`base_time` and
        :attr:`base_time` + :attr:`Probe.interval_secs`."""
        # This is used by the Scheduler to lazily remove Probes.
        self.removed: bool = False

    def __lt__(self, other: Schedule) -> bool:
        """
        Returns True if `self` should be scheduled before `other` and False
        otherwise.

        Schedule are only compared according to their :attr:`next_time`
        property.
        """
        return self.next_time.__lt__(other.next_time)

    def advance(self) -> None:
        """
        - Advances :attr:`base_time` by :attr:`Probe.interval_secs`.
        - Updates :attr:`next_time` to stay between :attr:`base_time`  and
          :attr:`base_time` + :attr:`Probe.interval_secs`.
        """
        self.base_time += self.probe.interval_secs
        self.next_time = self._generate_next_time()

    def _generate_next_time(self):
        return self.base_time + self.probe.interval_secs * random.uniform(0, 1)


class KafkaRecorder:
    """
    A Kafka producer that takes :class:`aiven_monitor.Measure` objects,
    and sends them to Kafka as utf-8 json serialized dicts.

    :param bootstrap_servers: A comma-separated list of Kafka servers.
    :param topic: The Kafka topic receiving the :class:`aiven_monitor.Measure`
     objects.
    :param ssl_cafile: The path to the PEM certificate of the certificate
     authority used to authenticate the Kafka servers.
    :param ssl_certfile: The path to the PEM certificate used to authenticate
     this producer.
    :param ssl_keyfile: The path to the PEM private key used to authenticate
     this producer.
    :param connect_interval_secs: The number of seconds before retrying to
     connect.
    """

    _producer_factory = kafka.KafkaProducer

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
        self.producer = None
        self.has_producer = trio.Condition()

    async def start(self) -> None:
        """
        Starts the Kafka producer.

        If the connection cannot be established, it will endlessly retry while
        waiting `connect_interval_secs` between each attempt.
        """
        while self.producer is None:
            try:
                self.producer = self._producer_factory(
                    bootstrap_servers=self.bootstrap_servers,
                    ssl_cafile=self.ssl_cafile,
                    ssl_certfile=self.ssl_certfile,
                    ssl_keyfile=self.ssl_keyfile,
                    security_protocol='SSL',
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                )
            except kafka.errors.NoBrokersAvailable:
                await trio.sleep(self.connect_interval_secs)
            else:
                logger.info('kafka-ready: %s', self.producer)
                async with self.has_producer:
                    self.has_producer.notify_all()

    async def record(self, measure: Measure) -> None:
        """
        Records a :class:`aiven_monitor.Measure` in Kafka.

        This does not wait for the measure to be actually sent.

        Because this requires a working Kafka connection, this function will
        not return until :func:`start` has completed.

        It is not an error to call :func:`record` before or while calling
        :func:`start`. However, this means that if :func:`record` is called as a
        coroutine and not directly awaited, pending measures and coroutines can
        accumulate in memory until the connection is established.

        """
        logger.info('measure-record: %s', measure.to_dict())
        async with self.has_producer:
            while self.producer is None:
                await self.has_producer.wait()
        self.producer.send(self.topic, measure.to_dict())

    def flush(self) -> None:
        """
        Synchronously waits for all pending events to be sent.
        """
        if self.producer is not None:
            self.producer.flush()
