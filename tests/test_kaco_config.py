import pytest

from kaco_config import load_inverter_configs, ConfigError, InverterConfig


def write_config(tmp_path, content):
    path = tmp_path / "config.ini"
    path.write_text(content)
    return str(path)


def test_loads_single_inverter_section(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
position = ac-in
custom_name = Kaco One
""")
    configs = load_inverter_configs(path)
    assert configs == [
        InverterConfig(
            name='kaco_1', host='192.168.1.10', port=502, unit=2,
            position='ac-in', position_code=0, custom_name='Kaco One',
        )
    ]


def test_loads_multiple_sections_in_file_order(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
position = ac-in
custom_name = Kaco One

[INVERTER2]
name = kaco_2
host = 192.168.1.11
port = 502
unit = 3
position = ac-out
custom_name = Kaco Two
""")
    configs = load_inverter_configs(path)
    assert [c.name for c in configs] == ['kaco_1', 'kaco_2']
    assert configs[1].position_code == 1


def test_ignores_non_inverter_sections(tmp_path):
    path = write_config(tmp_path, """
[GLOBAL]
some_key = value

[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
position = ac-in
custom_name = Kaco One
""")
    configs = load_inverter_configs(path)
    assert len(configs) == 1
    assert configs[0].name == 'kaco_1'


def test_missing_file_raises_configerror(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.ini")
    with pytest.raises(ConfigError, match="not found"):
        load_inverter_configs(missing_path)


def test_no_inverter_sections_raises_configerror(tmp_path):
    path = write_config(tmp_path, "[GLOBAL]\nsome_key = value\n")
    with pytest.raises(ConfigError, match=r"No \[INVERTERx\] sections"):
        load_inverter_configs(path)


def test_missing_required_key_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
custom_name = Kaco One
""")
    with pytest.raises(ConfigError, match="position"):
        load_inverter_configs(path)


def test_invalid_position_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
position = sideways
custom_name = Kaco One
""")
    with pytest.raises(ConfigError, match="invalid position"):
        load_inverter_configs(path)


def test_missing_port_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
unit = 2
position = ac-in
custom_name = Kaco One
""")
    with pytest.raises(ConfigError, match="port"):
        load_inverter_configs(path)


def test_missing_unit_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
position = ac-in
custom_name = Kaco One
""")
    with pytest.raises(ConfigError, match="unit"):
        load_inverter_configs(path)


def test_non_numeric_port_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = abc
unit = 2
position = ac-in
custom_name = Kaco One
""")
    with pytest.raises(ConfigError):
        load_inverter_configs(path)


def test_invalid_name_charset_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco 1
host = 192.168.1.10
port = 502
unit = 2
position = ac-in
custom_name = Kaco One
""")
    with pytest.raises(ConfigError, match="invalid name"):
        load_inverter_configs(path)


def test_duplicate_name_raises_configerror(tmp_path):
    path = write_config(tmp_path, """
[INVERTER1]
name = kaco_1
host = 192.168.1.10
port = 502
unit = 2
position = ac-in
custom_name = Kaco One

[INVERTER2]
name = kaco_1
host = 192.168.1.11
port = 502
unit = 3
position = ac-out
custom_name = Kaco Two
""")
    with pytest.raises(ConfigError, match="Duplicate"):
        load_inverter_configs(path)
