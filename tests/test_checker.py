import configparser
import datetime
import re
import statistics
import uuid
from pathlib import Path
from unittest import mock

import kafka.errors
import pytest
import trio
from aiven_monitor import Measure, VERSION
from aiven_monitor.checker import (
    KafkaRecorder,
    Probe,
    REQUEST_TIMEOUT_SECS,
    RESPONSE_MAX_BYTES,
    Schedule,
    Scheduler,
    create_kafka_recorder,
)


def test_create_probe():
    probe = Probe('https://example.org', 10.3)
    assert probe.url == 'https://example.org'
    assert probe.interval_secs == 10.3
    assert probe.expected_pattern is None


def test_create_probe_with_expected_pattern():
    probe = Probe('https://example.org', 10.3, r'\bHello\b')
    assert probe.expected_pattern == re.compile(r'\bHello\b')


def test_probe_repr_is_probe_definition():
    probe = Probe('https://example.org', 10.3, r'\bHello\b')
    # The expected pattern doesn't use the r prefix to limit backslash
    # repetitions but it's still valid code and still equivalent to the input
    # parameter.
    assert (
            probe.__repr__()
            == r"Probe('https://example.org', interval_secs=10.3, expected_pattern='\\bHello\\b')"
    )


def test_probe_repr_without_expected_pattern_is_probe_definition():
    probe = Probe('https://example.org', 10.3, None)
    assert (
            probe.__repr__()
            == r"Probe('https://example.org', interval_secs=10.3, expected_pattern=None)"
    )


def test_probe_interval_must_be_strictly_positive():
    for value in 0, -1, -10:
        with pytest.raises(ValueError):
            Probe('https://example.org', value)


async def test_probe_check(httpx_mock):
    httpx_mock.add_response()
    probe = Probe('https://example.org', 10.3, None)
    recorder = mock.MagicMock(spec_set=KafkaRecorder)
    pre_start = datetime.datetime.utcnow()

    def record(measure: Measure):
        assert measure.url == 'https://example.org'
        assert measure.endpoint == 'test-endpoint'
        assert measure.protocol == 'HTTP/1.1'
        assert measure.status_code == 200
        assert pre_start < measure.start_time < datetime.datetime.utcnow()
        assert (
                0
                < measure.response_time_secs
                < (datetime.datetime.utcnow() - pre_start).total_seconds()
        )
        assert measure.expected_pattern is None
        assert measure.pattern_was_found is None
        assert measure.checker_version == VERSION

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_http2(httpx_mock):
    httpx_mock.add_response(http_version='HTTP/2')
    probe = Probe('https://example.org', 10.3, None)
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.protocol == 'HTTP/2'

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_pattern_found(httpx_mock):
    httpx_mock.add_response(data=b'hello world !')
    probe = Probe('https://example.org', 10.3, 'w.rld')
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.expected_pattern == 'w.rld'
        assert measure.pattern_was_found

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_pattern_found_chunked(autojump_clock, httpx_mock):
    async def stream_response():
        yield b'wait for'
        await trio.sleep(1)
        yield b' it'

    httpx_mock.add_response(data=stream_response())
    probe = Probe('https://example.org', 10.3, 'wait for it')
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.expected_pattern == 'wait for it'
        assert measure.pattern_was_found

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_pattern_not_found(httpx_mock):
    httpx_mock.add_response(data=b'hello world !')
    probe = Probe('https://example.org', 10.3, 'mo.n')
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.expected_pattern == 'mo.n'
        assert measure.pattern_was_found is False

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_pattern_on_invalid_text(httpx_mock):
    httpx_mock.add_response(
        data=b'\xa0\xa1', headers={'content-type': 'text/plain;charset=utf-8'}
    )
    probe = Probe('https://example.org', 10.3, 'w.rld')
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.expected_pattern == 'w.rld'
        assert measure.pattern_was_found is None

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_check_pattern_found_on_non_200(httpx_mock):
    httpx_mock.add_response(status_code=404, data=b'resource not here :(')
    probe = Probe('https://example.org', 10.3, r'not\s+here')
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.status_code == 404
        assert measure.expected_pattern == r'not\s+here'
        assert measure.pattern_was_found

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


async def test_probe_stops_on_slow_response(autojump_clock, httpx_mock):
    async def slow_block():
        yield b'block'
        await trio.sleep(REQUEST_TIMEOUT_SECS * 10)

    httpx_mock.add_response(data=slow_block())
    probe = Probe('https://example.org', 10.3, None)
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    start_time = trio.current_time()

    def record(measure: Measure):
        assert measure.url == 'https://example.org'
        assert measure.endpoint == 'test-endpoint'
        assert measure.protocol == 'HTTP/1.1'
        assert measure.status_code == 200
        assert measure.response_time_secs is None

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()
    assert trio.current_time() < start_time + REQUEST_TIMEOUT_SECS + 0.1


async def test_probe_stops_on_large_response(httpx_mock):
    async def infinite_blocks():
        while True:
            yield b'b' * 1024

    httpx_mock.add_response(data=infinite_blocks())
    probe = Probe('https://example.org', 10.3, None)
    recorder = mock.MagicMock(spec_set=KafkaRecorder)

    def record(measure: Measure):
        assert measure.url == 'https://example.org'
        assert measure.endpoint == 'test-endpoint'
        assert measure.protocol == 'HTTP/1.1'
        assert measure.checker_version == VERSION
        assert measure.response_size_bytes == RESPONSE_MAX_BYTES

    recorder.record.side_effect = record
    await probe.check(recorder, 'test-endpoint')
    recorder.record.assert_called_once()


def test_create_scheduler():
    scheduler = Scheduler()
    assert len(scheduler.queue) == 0


async def test_add_scheduler():
    scheduler = Scheduler()
    probe = Probe('https://example.org', 20)
    await scheduler.add([probe])
    assert len(scheduler.queue) == 1
    assert probe in scheduler.index
    assert scheduler.index[probe] == scheduler.queue[0]


async def test_remove_scheduler():
    scheduler = Scheduler()
    probe = Probe('https://example.org', 20)
    await scheduler.add([probe])
    await scheduler.remove([probe])
    assert scheduler.queue[0].removed
    assert probe not in scheduler.index


async def test_remove_absent_scheduler_is_ok():
    scheduler = Scheduler()
    probe = Probe('https://example.org', 20)
    await scheduler.remove([probe])
    assert probe not in scheduler.index


async def test_get_next_just_waits_if_no_probe(autojump_clock):
    scheduler = Scheduler()
    start_time = trio.current_time()
    with trio.move_on_after(10):
        await scheduler.get_next()
    assert trio.current_time() >= start_time + 10


async def test_get_next_always_returns_single_probe(autojump_clock):
    scheduler = Scheduler()
    probe = Probe('https://example.org', 20)
    await scheduler.add([probe])
    for i in range(10):
        assert await scheduler.get_next() == probe


async def test_get_next_returns_probe_at_specified_interval_on_average(
        autojump_clock,
):
    scheduler = Scheduler()
    probes = [
        Probe('https://example.org', 20),
        Probe('https://example.com', 50),
        Probe('https://example.com', 5),
    ]
    await scheduler.add(probes)
    probe_times = {probe: [] for probe in probes}
    measures = 2000
    for i in range(measures):
        probe = await scheduler.get_next()
        time = trio.current_time()
        probe_times[probe].append(time)
    for probe, times in probe_times.items():
        delta_times = [times[i] - times[i - 1] for i in range(1, len(times))]
        # Check the interval between two consecutive measures of this probe
        assert statistics.mean(delta_times) == pytest.approx(
            probe.interval_secs, rel=0.01
        )
        # Check that among all the measures, the number of measures for this
        # probe is consistent with the relative frequency of all added probes.
        assert len(delta_times) == pytest.approx(
            (measures - 1)
            / probe.interval_secs
            / sum([1 / p.interval_secs for p in probes]),
            abs=2,
        )


async def test_scheduler_can_be_quicky_reconfigured(autojump_clock):
    scheduler = Scheduler()
    probe_slow = Probe('https://example.org', 3600)
    probe_fast = Probe('https://example.org', 5)
    await scheduler.add([probe_slow])
    start_time = trio.current_time()
    elected_probe = None

    async def get_next():
        nonlocal elected_probe
        elected_probe = await scheduler.get_next()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(get_next)
        await scheduler.add([probe_fast])
    assert elected_probe == probe_fast
    assert trio.current_time() < start_time + probe_fast.interval_secs + 0.1


async def test_scheduler_does_not_fail_if_elected_is_removed(autojump_clock):
    scheduler = Scheduler()
    probe = Probe('https://example.org', 3600)
    await scheduler.add([probe])
    start_time = trio.current_time()
    with trio.move_on_after(10):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(scheduler.get_next)
            await trio.sleep(5)
            await scheduler.remove([probe])
    assert trio.current_time() >= start_time + 10


async def test_scheduler_does_not_elect_already_removed(autojump_clock):
    scheduler = Scheduler()
    probe = Probe('https://example.org', 1)
    await scheduler.add([probe])
    await scheduler.remove([probe])
    start_time = trio.current_time()
    with trio.move_on_after(10):
        await scheduler.get_next()
    # It was not elected and just kept waiting
    assert trio.current_time() >= start_time + 10


def test_create_schedule():
    probe = Probe('https://example.org', 20)
    schedule = Schedule(probe, 123456)
    assert schedule.probe == probe
    assert schedule.base_time == 123456
    assert (
            schedule.base_time
            <= schedule.next_time
            < schedule.base_time + probe.interval_secs
    )


def test_schedule_are_compared_by_next_time():
    probe_a = Probe('https://example.org', 10)
    schedule_a = Schedule(probe_a, 1000)
    schedule_a.next_time = 1020
    probe_b = Probe('https://example.org', 10)
    schedule_b = Schedule(probe_b, 1010)
    schedule_b.next_time = 1015
    assert schedule_b < schedule_a


def test_schedule_advances_by_interval_secs():
    probe = Probe('https://example.org', 10)
    schedule = Schedule(probe, 1000)
    schedule.advance()
    assert schedule.base_time == 1010
    assert (
            schedule.base_time
            <= schedule.next_time
            < schedule.base_time + probe.interval_secs
    )


def test_create_kafka_recorder():
    kafka_recorder = KafkaRecorder(
        'localhost', 'measures', '/tmp/cafile', '/tmp/certfile', '/tmp/keyfile'
    )
    assert kafka_recorder.bootstrap_servers == 'localhost'
    assert kafka_recorder.topic == 'measures'
    assert kafka_recorder.ssl_cafile == '/tmp/cafile'
    assert kafka_recorder.ssl_certfile == '/tmp/certfile'
    assert kafka_recorder.ssl_keyfile == '/tmp/keyfile'


def test_create_kafka_recorder_from_config():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            'test': {
                'kafka.bootstrap_servers': 'localhost',
                'kafka.topic': 'topic',
                'kafka.ssl.cafile': 'relative/cafile',
                'kafka.ssl.certfile': '/absolute/certfile',
                'kafka.ssl.keyfile': '../bare_keyfile',
                'kafka.connect_interval_secs': '5',
            }
        }
    )
    kafka_recorder = create_kafka_recorder(Path('/foo/bar'), config['test'])
    assert kafka_recorder.bootstrap_servers == 'localhost'
    assert kafka_recorder.topic == 'topic'
    assert kafka_recorder.ssl_cafile == Path('/foo/bar/relative/cafile')
    assert kafka_recorder.ssl_certfile == Path('/absolute/certfile')
    assert kafka_recorder.ssl_keyfile == Path('/foo/bar/../bare_keyfile')
    assert kafka_recorder.connect_interval_secs == 5.0


def test_create_kafka_recorder_from_partial_config():
    config = configparser.ConfigParser()
    config.read_dict(
        {
            'test': {
                'kafka.bootstrap_servers': 'localhost',
                'kafka.topic': 'topic',
            }
        }
    )
    kafka_recorder = create_kafka_recorder(Path('/foo/bar'), config['test'])
    assert kafka_recorder.bootstrap_servers == 'localhost'
    assert kafka_recorder.topic == 'topic'
    assert kafka_recorder.ssl_cafile is None
    assert kafka_recorder.ssl_certfile is None
    assert kafka_recorder.ssl_keyfile is None
    assert kafka_recorder.connect_interval_secs is None


async def test_kafka_recorder_start_creates_producer():
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
    kafka_recorder._producer_factory = mock.MagicMock()
    await kafka_recorder.start()
    assert (
            kafka_recorder.producer == kafka_recorder._producer_factory.return_value
    )


async def test_kafka_recorder_start_retries_on_error(autojump_clock):
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
    kafka_recorder._producer_factory = mock.MagicMock()
    kafka_recorder._producer_factory.side_effect = (
        kafka.errors.NoBrokersAvailable()
    )
    with trio.move_on_after(kafka_recorder.connect_interval_secs * 7):
        await kafka_recorder.start()
    assert kafka_recorder._producer_factory.call_count == 7


async def test_kafka_recorder_record_sends_dict_to_topic():
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
    kafka_recorder.producer = mock.MagicMock(
        spec_set=kafka_recorder._producer_factory
    )
    measure = Measure(
        'https://example.org',
        uuid.uuid4(),
        'test-endpoint',
        datetime.datetime(2020, 1, 2),
        None,
    )
    await kafka_recorder.record(measure)
    kafka_recorder.producer.send.assert_called_once_with(
        'topic-measures', measure.to_dict()
    )


async def test_kafka_recorder_record_waits_for_producer(autojump_clock):
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
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
        kafka_recorder._producer_factory = mock.MagicMock()
        await kafka_recorder.start()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_and_start)
        await kafka_recorder.record(measure)
    assert trio.current_time() >= start_time + 10
    kafka_recorder.producer.send.assert_called_once_with(
        'topic-measures', measure.to_dict()
    )


def test_kafka_recorder_flush_producer():
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
    kafka_recorder.producer = mock.MagicMock(
        spec_set=kafka_recorder._producer_factory
    )
    kafka_recorder.flush()
    kafka_recorder.producer.flush.assert_called_once_with()


def test_kafka_recorder_flush_without_producer():
    kafka_recorder = KafkaRecorder(
        'localhost', 'topic-measures', None, None, None
    )
    kafka_recorder.flush()
