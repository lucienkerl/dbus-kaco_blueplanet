import pytest

from kaco_config import InverterConfig
from kaco_orchestrator import build_devices, update_all


GOOD_BAD_CONFIG = """
[INVERTER1]
name = good
host = 10.0.0.1
port = 502
unit = 1
position = ac-in
custom_name = Good

[INVERTER2]
name = bad
host = 10.0.0.2
port = 502
unit = 1
position = ac-out
custom_name = Bad
"""

ALL_BAD_CONFIG = """
[INVERTER1]
name = bad
host = 10.0.0.2
port = 502
unit = 1
position = ac-out
custom_name = Bad
"""


def write_config(tmp_path, content):
    path = tmp_path / "config.ini"
    path.write_text(content)
    return str(path)


def test_build_devices_skips_failing_inverter_and_keeps_others(tmp_path):
    config_path = write_config(tmp_path, GOOD_BAD_CONFIG)
    created = []

    def fake_factory(config, dbus_conn, instance_offset=0):
        if config.name == 'bad':
            raise ConnectionError("simulated failure")
        created.append(config.name)
        return object()

    devices = build_devices(config_path, dbus_conn=object(), device_factory=fake_factory)

    assert len(devices) == 1
    assert created == ['good']


def test_build_devices_exits_when_no_inverter_starts(tmp_path):
    config_path = write_config(tmp_path, ALL_BAD_CONFIG)

    def fake_factory(config, dbus_conn, instance_offset=0):
        raise ConnectionError("simulated failure")

    with pytest.raises(SystemExit):
        build_devices(config_path, dbus_conn=object(), device_factory=fake_factory)


def test_build_devices_exits_on_config_error(tmp_path):
    missing_path = str(tmp_path / "missing.ini")

    with pytest.raises(SystemExit):
        build_devices(missing_path, dbus_conn=object(), device_factory=lambda *a, **k: object())


def test_update_all_continues_after_one_device_raises():
    class RaisingDevice:
        config = InverterConfig(name='bad', host='x', port=502, unit=1,
                                 position='ac-in', position_code=0, custom_name='Bad')

        def update(self):
            raise RuntimeError("boom")

    class OkDevice:
        config = InverterConfig(name='good', host='y', port=502, unit=1,
                                 position='ac-in', position_code=0, custom_name='Good')

        def __init__(self):
            self.updated = False

        def update(self):
            self.updated = True

    ok_device = OkDevice()
    result = update_all([RaisingDevice(), ok_device])

    assert result is True
    assert ok_device.updated is True
