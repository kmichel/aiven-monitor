import datetime
import uuid

from aiven_monitor import Measure, VERSION


def test_create_measure():
    measure_id = uuid.uuid4()
    measure = Measure(
        'https://example.org',
        measure_id,
        'endpoint-01',
        datetime.datetime(2020, 1, 2, 3, 4, 5, 6),
        expected_pattern=r'foo.bar',
    )
    assert measure.url == 'https://example.org'
    assert measure.measure_id == measure_id
    assert measure.endpoint == 'endpoint-01'
    assert measure.start_time == datetime.datetime(2020, 1, 2, 3, 4, 5, 6)
    # The probe converts the expected_pattern to a re.Pattern
    # object but the measure does not.
    assert measure.expected_pattern == r'foo.bar'
    assert measure.checker_version == VERSION
    assert measure.protocol is None
    assert measure.response_time_secs is None
    assert measure.response_size_bytes is None
    assert measure.status_code is None
    assert measure.pattern_was_found is None


def test_create_measure_without_pattern():
    measure_id = uuid.uuid4()
    measure = Measure(
        'https://example.org',
        measure_id,
        'endpoint-01',
        datetime.datetime(2020, 1, 2, 3, 4, 5, 6),
        expected_pattern=None,
    )
    assert measure.expected_pattern is None


def test_create_measure_from_dict():
    measure_id = uuid.uuid4()
    measure = Measure.from_dict(
        {
            'url': 'https://example.org',
            'measure_id': str(measure_id),
            'endpoint': 'endpoint-02',
            'start_time': '2020-01-02T03:04:05.000006Z',
            'expected_pattern': r'foo.bar',
            'checker_version': '1.2.3',
            'protocol': 'HTTP/2',
            'response_time_secs': 12.3,
            'response_size_bytes': 3456,
            'status_code': 404,
            'pattern_was_found': False,
            # Unknown keys are ignored to allow for extensions
            'safely_ignored': 'ignored_value',
        }
    )
    assert measure.url == 'https://example.org'
    assert measure.measure_id == measure_id
    assert measure.endpoint == 'endpoint-02'
    assert measure.start_time == datetime.datetime(2020, 1, 2, 3, 4, 5, 6)
    assert measure.expected_pattern == r'foo.bar'
    assert measure.checker_version == '1.2.3'
    assert measure.protocol == 'HTTP/2'
    assert measure.response_time_secs == 12.3
    assert measure.response_size_bytes == 3456
    assert measure.status_code == 404
    assert measure.pattern_was_found is False
