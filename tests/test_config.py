import tempfile

import pytest
from aiven_monitor import ConfigFileNotFound, load_config


def test_load_config_has_default_values():
    with tempfile.NamedTemporaryFile() as config_file:
        config = load_config(
            'section',
            {'option': 'default'},
            config_file.name,
        )
        assert config['option'] == 'default'


def test_load_config_reads_from_specified_section():
    with tempfile.NamedTemporaryFile() as config_file:
        config_file.write(b'''
[something]
option = not-default
''')
        config_file.flush()
        config = load_config(
            'something',
            {'option': 'default'},
            config_file.name,
        )
        assert config['option'] == 'not-default'


def test_load_config_complains_if_file_is_missing():
    with pytest.raises(ConfigFileNotFound):
        load_config('section', {'option': 'default-value'},
                    '/path/does/not/exists')
