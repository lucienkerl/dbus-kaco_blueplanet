import pytest

from kaco_config import InverterConfig
from kaco_orchestrator import build_devices, retry_pending, update_all


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


def test_build_devices_starts_good_inverter_and_queues_bad_one_for_retry(tmp_path):
    config_path = write_config(tmp_path, GOOD_BAD_CONFIG)
    created = []

    def fake_factory(config, dbus_conn, instance_offset=0):
        if config.name == 'bad':
            raise ConnectionError("simulated failure")
        created.append(config.name)
        return object()

    active, pending = build_devices(config_path, dbus_conn=object(), device_factory=fake_factory)

    assert len(active) == 1
    assert created == ['good']
    assert len(pending) == 1
    pending_config, pending_offset = pending[0]
    assert pending_config.name == 'bad'
    assert pending_offset == 1


def test_build_devices_does_not_exit_when_zero_devices_start(tmp_path):
    config_path = write_config(tmp_path, ALL_BAD_CONFIG)

    def fake_factory(config, dbus_conn, instance_offset=0):
        raise ConnectionError("simulated failure")

    active, pending = build_devices(config_path, dbus_conn=object(), device_factory=fake_factory)

    assert active == []
    assert len(pending) == 1
    assert pending[0][0].name == 'bad'


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


def test_retry_pending_moves_recovered_config_into_active_devices():
    config = InverterConfig(name='kaco_1', host='10.0.0.5', port=502, unit=1,
                             position='ac-in', position_code=0, custom_name='Kaco 1')
    pending = [(config, 0)]
    active_devices = []
    recovered_device = object()

    def fake_factory(cfg, dbus_conn, instance_offset=0):
        return recovered_device

    result = retry_pending(pending, active_devices, dbus_conn=object(), device_factory=fake_factory)

    assert result is True
    assert active_devices == [recovered_device]
    assert pending == []


def test_retry_pending_keeps_still_failing_config_pending():
    config = InverterConfig(name='kaco_1', host='10.0.0.5', port=502, unit=1,
                             position='ac-in', position_code=0, custom_name='Kaco 1')
    pending = [(config, 0)]
    active_devices = []

    def fake_factory(cfg, dbus_conn, instance_offset=0):
        raise ConnectionError("still unreachable")

    result = retry_pending(pending, active_devices, dbus_conn=object(), device_factory=fake_factory)

    assert result is True
    assert active_devices == []
    assert pending == [(config, 0)]


def test_retry_pending_handles_mixed_recovery():
    recovered_config = InverterConfig(name='recovered', host='10.0.0.5', port=502, unit=1,
                                       position='ac-in', position_code=0, custom_name='Recovered')
    still_down_config = InverterConfig(name='still_down', host='10.0.0.6', port=502, unit=1,
                                        position='ac-out', position_code=1, custom_name='Still Down')
    pending = [(recovered_config, 0), (still_down_config, 1)]
    active_devices = []
    recovered_device = object()

    def fake_factory(cfg, dbus_conn, instance_offset=0):
        if cfg.name == 'recovered':
            return recovered_device
        raise ConnectionError("still unreachable")

    retry_pending(pending, active_devices, dbus_conn=object(), device_factory=fake_factory)

    assert active_devices == [recovered_device]
    assert pending == [(still_down_config, 1)]
