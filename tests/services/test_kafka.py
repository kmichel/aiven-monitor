import datetime
import logging
import os
import uuid
from pathlib import Path

import pytest
import trio
from aiven_monitor import Measure
from aiven_monitor.checker import create_kafka_recorder, load_checker_config
from aiven_monitor.writer import create_kafka_source, load_writer_config

"""
These tests require a running Kafka server
and the relevant configuration from checker.ini and writer.ini
"""

checker_config_path = Path(__file__).parent / 'checker.ini'
if os.environ.get('AIVEN_TEST_CHECKER_CONFIG_PATH'):
    checker_config_path = Path(os.environ.get('AIVEN_TEST_CHECKER_CONFIG_PATH'))

writer_config_path = Path(__file__).parent / 'writer.ini'
if os.environ.get('AIVEN_TEST_WRITER_CONFIG_PATH'):
    writer_config_path = Path(os.environ.get('AIVEN_TEST_WRITER_CONFIG_PATH'))

requires_kafka = pytest.mark.skipif(
    not checker_config_path.exists() or not writer_config_path.exists(),
    reason="Kafka must be configured with AIVEN_TEST_CHECKER_CONFIG_PATH and AIVEN_TEST_WRITER_CONFIG_PATH"
)


@requires_kafka
async def test_kafka_roundtrip():
    logging.basicConfig(level=logging.DEBUG)
    checker_base_path = checker_config_path.parent
    checker_config = load_checker_config(checker_config_path)
    recorder = create_kafka_recorder(checker_base_path, checker_config)
    writer_base_path = writer_config_path.parent
    writer_config = load_writer_config(writer_config_path)
    source = create_kafka_source(writer_base_path, writer_config)

    with trio.fail_after(10):
        async with trio.open_nursery() as nursery:
            await recorder.start()
            await source.start()
            measure = Measure(
                'https://example.org',
                uuid.uuid4(),
                'test-endpoint',
                datetime.datetime(2020, 1, 2, 3, 4, 5, 6),
                None
            )

            async def wait_and_send():
                await trio.sleep(0)
                await recorder.record(measure)

            nursery.start_soon(wait_and_send)
            new_measure = await source.get_measure()
            assert new_measure.measure_id == measure.measure_id
        nursery.cancel_scope.cancel()
