import datetime
from configparser import ConfigParser, SectionProxy
from pathlib import Path
from typing import Dict, Optional, Union
from uuid import UUID

from .version import VERSION


class Measure:
    """
    Results of a monitoring :class:`aiven_monitor.checker.Probe` check.
    """

    def __init__(
            self,
            url: str,
            measure_id: UUID,
            endpoint: str,
            start_time: datetime.datetime,
            expected_pattern: Optional[str],
            checker_version: str = VERSION,
    ):
        self.url: str = url
        """The Url that was checked."""
        self.measure_id: UUID = measure_id
        """The unique Id of the measure."""
        self.endpoint: str = endpoint
        """The name of the location from where the measure was done."""
        self.start_time: datetime.datetime = start_time
        """The UTC datetime of the start of the measure."""
        self.protocol: Optional[str] = None
        """The protocol of the request, usually 'HTTP/1.1' or 'HTTP/2'."""
        self.response_time_secs: Optional[float] = None
        """The response time in seconds, including all redirections.
        
        This will be `None` if the request failed. 
        """
        self.response_size_bytes: Optional[int] = None
        """The response size in bytes.
        
        This will be `None` if the request failed.
        """
        self.status_code: Optional[int] = None
        """The status code.
        
        This will be `None` if the request failed.
        """
        self.expected_pattern: Optional[str] = expected_pattern
        """An optional regular expression searched in the response."""
        self.pattern_was_found: Optional[bool] = None
        """Whether the expected pattern was found in the response.
        
        This will be `None` if the request failed.
        
        This is searched even if the HTTP status code is not 200 (OK).
        """
        self.checker_version = checker_version
        """The version of the code used to generate the measure."""

    @classmethod
    def from_dict(cls, values):
        """
        Recreates a :class:`Measure` object from a dictionary.

        :param values: A dictionary produced by :func:`to_dict`.
        """
        measure = cls(
            url=values['url'],
            measure_id=UUID(values['measure_id']),
            endpoint=values['endpoint'],
            start_time=datetime.datetime.fromisoformat(
                values['start_time'].rstrip('Z')
            ),
            expected_pattern=values['expected_pattern'],
            checker_version=values['checker_version'],
        )
        measure.protocol = values['protocol']
        measure.response_time_secs = values['response_time_secs']
        measure.response_size_bytes = values['response_size_bytes']
        measure.status_code = values['status_code']
        measure.pattern_was_found = values['pattern_was_found']
        return measure

    def to_dict(self) -> Dict[str, Optional[Union[str, float]]]:
        """
        Serializes the :class:`Measure` object into a dictionary.

        The `start_time` is serialized as an ISO8601 string with the 'Z' suffix
        to denote the UTC 'timezone'.

        :returns: A json-compatible dictionary with all the members of the
         measure as strings, floats or None.
        """
        return {
            'url': self.url,
            'measure_id': str(self.measure_id),
            'endpoint': self.endpoint,
            'start_time': self.start_time.isoformat() + 'Z',
            'protocol': self.protocol,
            'response_time_secs': self.response_time_secs,
            'response_size_bytes': self.response_size_bytes,
            'status_code': self.status_code,
            'expected_pattern': self.expected_pattern,
            'pattern_was_found': self.pattern_was_found,
            'checker_version': self.checker_version,
        }


def load_config(section_name: str, default_config: dict,
                config_path: Union[str, Path]) -> SectionProxy:
    config = ConfigParser()
    config.read_dict({section_name: default_config})
    found_files = config.read(config_path)
    if len(found_files) == 0:
        raise ConfigFileNotFound(
            f'Configuration file not found: {str(config_path)!r}',
        )
    return config[section_name]


class ConfigFileNotFound(Exception):
    pass


def resolve_path(head: Path, optional_tail: Optional[str]):
    if optional_tail is not None:
        return head.joinpath(optional_tail)
