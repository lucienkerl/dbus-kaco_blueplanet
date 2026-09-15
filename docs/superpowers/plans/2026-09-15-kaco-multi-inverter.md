# Multi-Inverter Kaco Blueplanet Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `dbus-kaco_blueplanet` so one driver process can bridge several Kaco Blueplanet inverters (each with its own IP, Modbus port, unit ID, and AC position) to Venus OS's D-Bus, configured via `config.ini` instead of hardcoded constants.

**Architecture:** A `KacoInverterDevice` class owns one physical inverter's Modbus connection plus its `pvinverter`/`temperature` D-Bus services and knows how to `update()` itself without affecting other inverters. An orchestrator loads `config.ini`, builds one `KacoInverterDevice` per `[INVERTERx]` section, and drives them all from a single GLib timer. Pure logic (register decoding, config parsing, device-instance allocation, orchestration fault-isolation) is split into small, dependency-injectable modules so it is unit-testable on a plain dev machine without `dbus-python`/`pymodbus`/Venus OS installed — only `vedbus`/`pymodbus`/real D-Bus are touched behind lazy imports, exercised for real only on the GX device.

**Tech Stack:** Python 3 (Venus OS), `pymodbus` (sync client, `pymodbus.client.sync.ModbusTcpClient`), `velib_python` (`vedbus.VeDbusService`, `settingsdevice.SettingsDevice`) vendored as a git submodule, `pytest` for the dev-machine unit test suite, `configparser` (stdlib) for `config.ini`.

## Global Constraints

- `velib_python` is vendored as a git submodule at `ext/velib_python` (per spec §"Multi-instance / multi-device pattern"), imported via `sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))`.
- `config.ini` sections are discovered by the `INVERTER` name prefix, not a fixed count — any number of inverters is supported (spec: "several", not hardcoded to 3).
- `position` accepts exactly `ac-in` (→ `/Position = 0`) or `ac-out` (→ `/Position = 1`); no other value, no silent fallback (spec §"config.ini schema").
- D-Bus service names: `com.victronenergy.pvinverter.{name}` and `com.victronenergy.temperature.{name}_temp` (spec §"D-Bus service naming").
- `/DeviceInstance` for both sub-services is obtained via `SettingsDevice` against `/Settings/Devices/{name or name_temp}/ClassAndVrmInstance`, never hardcoded, so Venus OS resolves collisions against any other device on the system (spec §"D-Bus service naming and device-instance allocation").
- A Modbus fault on one inverter must not stop the process or the other configured inverters (spec §"Architecture", "Fault isolation").
- `install.sh` never overwrites an existing `config.ini` (spec §"Install script").
- Out of scope (do not implement): SetupHelper/Package-Manager packaging, network auto-discovery of inverters, `/Position = 2` (AC input 2), the already-unused `grid`/`limit_pvinverter` service types (spec §"Out of scope").

---

## File Structure

```
kaco_registers.py           # NEW - pure SunSpec register decode helpers
kaco_config.py               # NEW - config.ini loading & validation
kaco_instance.py             # NEW - collision-free device-instance allocation
kaco_inverter.py             # NEW - KacoInverterDevice class
kaco_orchestrator.py         # NEW - build_devices()/update_all()/main(), D-Bus plumbing
dbus-kaco_blueplanet.py      # MODIFY (full rewrite) - thin entry point, unchanged filename/path
config.default.ini           # NEW - versioned config template
config.ini                   # created by install.sh at install time, gitignored
install.sh                   # NEW - permissions, config bootstrap, autostart, restart
requirements-dev.txt         # NEW - pytest, for local unit testing only
pytest.ini                   # NEW - pytest config (rootdir on sys.path)
.gitignore                   # MODIFY - add config.ini, .venv/, __pycache__/, .pytest_cache/
README.md                    # MODIFY - multi-inverter config.ini workflow, install.sh
tests/test_kaco_registers.py       # NEW
tests/test_kaco_config.py          # NEW
tests/test_kaco_instance.py        # NEW
tests/test_kaco_inverter_update.py # NEW
tests/test_kaco_inverter_create.py # NEW
tests/test_kaco_orchestrator.py    # NEW
kill_me.sh, service/run, service/log/run   # unchanged
```

`kaco_orchestrator.py` exists (rather than folding its contents into
`dbus-kaco_blueplanet.py`) purely so the orchestration logic
(`build_devices`, `update_all`) is importable from tests — a file named
`dbus-kaco_blueplanet.py` (hyphen) cannot be `import`ed as a normal Python
module. `dbus-kaco_blueplanet.py` itself stays the fixed entry point that
`service/run` invokes.

---

### Task 1: Test environment setup

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Modify: `.gitignore`

**Interfaces:**
- Produces: a working `pytest` command (`.venv/bin/pytest`) that later tasks' tests run under, with repo root importable (`pythonpath = .`).

- [ ] **Step 1: Create `requirements-dev.txt`**

```
pytest>=7.4
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: Update `.gitignore`**

Add to the existing `.gitignore` (keep the existing `**.DS_Store` line):

```
**.DS_Store
config.ini
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Create the virtualenv and install dev dependencies**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```
Expected: pip reports `Successfully installed pytest-...`.

- [ ] **Step 5: Verify pytest runs with zero tests collected**

Run: `.venv/bin/pytest`
Expected: `no tests ran` (exit code 5) — this is correct, `tests/` doesn't exist yet.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt pytest.ini .gitignore
git commit -m "Add pytest dev tooling for unit-testable driver logic

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Register decode helpers (`kaco_registers.py`)

**Files:**
- Create: `kaco_registers.py`
- Test: `tests/test_kaco_registers.py`

**Interfaces:**
- Produces: `decode_string(registers: list[int]) -> str`, `signed_short(value: int) -> int`,
  `scale_factor(value: int) -> float`, `victron_pv_state(state: int) -> int`. Used by
  `kaco_inverter.py` (Task 5/6).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_registers.py`:

```python
import pytest

from kaco_registers import decode_string, signed_short, scale_factor, victron_pv_state


def test_decode_string_two_chars_per_register():
    assert decode_string([(0x41 << 8) | 0x42]) == "AB"


def test_decode_string_skips_zero_bytes():
    assert decode_string([0x0041]) == "A"
    assert decode_string([0x4100]) == "A"
    assert decode_string([0x0000]) == ""


def test_decode_string_multiple_registers():
    registers = [(0x4B << 8) | 0x61, (0x63 << 8) | 0x6F]  # "Ka" + "co"
    assert decode_string(registers) == "Kaco"


def test_signed_short_positive():
    assert signed_short(1) == 1


def test_signed_short_negative():
    assert signed_short(0xFFFF) == -1
    assert signed_short(0xFFFD) == -3


def test_scale_factor_positive_exponent():
    assert scale_factor(2) == 100


def test_scale_factor_negative_exponent():
    assert scale_factor(0xFFFF) == pytest.approx(0.1)


@pytest.mark.parametrize("state,expected", [
    (1, 0),
    (3, 1),
    (4, 11),
    (5, 12),
    (7, 10),
    (2, 8),
    (6, 8),
    (99, 8),
])
def test_victron_pv_state_mapping(state, expected):
    assert victron_pv_state(state) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_registers.py -v`
Expected: `ModuleNotFoundError: No module named 'kaco_registers'`

- [ ] **Step 3: Write `kaco_registers.py`**

```python
"""Pure register-decoding helpers for the Kaco Blueplanet SunSpec Modbus map.

No external dependencies: safe to import and unit-test on any machine.
"""
import ctypes


def decode_string(registers):
    numbers = []
    for value in registers:
        high_byte = (value >> 8) & 0xFF
        low_byte = value & 0xFF
        if high_byte != 0:
            numbers.append(high_byte)
        if low_byte != 0:
            numbers.append(low_byte)
    return "".join(chr(n) for n in numbers)


def signed_short(value):
    return ctypes.c_short(value).value


def scale_factor(value):
    return 10 ** signed_short(value)


def victron_pv_state(state):
    if state == 1:      # Device is not operating
        return 0
    if state == 3:       # Device is starting up
        return 1
    if state == 4:        # Device is auto tracking maximum power
        return 11
    if state == 5:        # Device is operating at reduced power output
        return 12
    if state == 7:        # One or more faults exist
        return 10
    return 8               # Device is in standby mode (includes sleep/shutdown states)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_registers.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add kaco_registers.py tests/test_kaco_registers.py
git commit -m "Extract Kaco SunSpec register decode helpers into testable module

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Config loading and validation (`kaco_config.py`)

**Files:**
- Create: `kaco_config.py`
- Test: `tests/test_kaco_config.py`

**Interfaces:**
- Produces: `InverterConfig` (frozen dataclass: `name: str, host: str, port: int, unit: int,
  position: str, position_code: int, custom_name: str`), `ConfigError(Exception)`,
  `load_inverter_configs(path: str) -> list[InverterConfig]`. Used by `kaco_orchestrator.py`
  (Task 7) and by `kaco_inverter.py`'s tests (Task 5/6).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_config.py -v`
Expected: `ModuleNotFoundError: No module named 'kaco_config'`

- [ ] **Step 3: Write `kaco_config.py`**

```python
"""Loads and validates config.ini describing the configured Kaco inverters."""
import configparser
from dataclasses import dataclass

VALID_POSITIONS = {'ac-in': 0, 'ac-out': 1}


class ConfigError(Exception):
    """Raised when config.ini is missing or contains an invalid/incomplete inverter section."""


@dataclass(frozen=True)
class InverterConfig:
    name: str
    host: str
    port: int
    unit: int
    position: str
    position_code: int
    custom_name: str


def load_inverter_configs(path):
    parser = configparser.ConfigParser()
    read_files = parser.read(path)
    if not read_files:
        raise ConfigError("Config file not found: {}".format(path))

    configs = [
        _parse_section(section, parser[section])
        for section in parser.sections()
        if section.startswith('INVERTER')
    ]

    if not configs:
        raise ConfigError(
            "No [INVERTERx] sections found in {}. "
            "Add at least one inverter section before starting the service.".format(path)
        )

    return configs


def _parse_section(section_name, values):
    try:
        name = values['name']
        host = values['host']
        port = values.getint('port')
        unit = values.getint('unit')
        position = values['position']
        custom_name = values['custom_name']
    except KeyError as exc:
        raise ConfigError(
            "Section [{}] is missing required key: {}".format(section_name, exc)
        ) from exc

    if position not in VALID_POSITIONS:
        raise ConfigError(
            "Section [{}] has invalid position '{}'. Must be one of: {}".format(
                section_name, position, ", ".join(sorted(VALID_POSITIONS))
            )
        )

    return InverterConfig(
        name=name,
        host=host,
        port=port,
        unit=unit,
        position=position,
        position_code=VALID_POSITIONS[position],
        custom_name=custom_name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_config.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add kaco_config.py tests/test_kaco_config.py
git commit -m "Add config.ini loader for multiple inverter sections

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Device-instance allocation (`kaco_instance.py`)

**Files:**
- Create: `kaco_instance.py`
- Test: `tests/test_kaco_instance.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `allocate_device_instance(dbus_conn, name: str, default_instance: int,
  service_type: str = 'pvinverter', settings_device_factory=None) -> int`. Used by
  `kaco_inverter.py`'s `KacoInverterDevice.create()` (Task 6).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_instance.py`:

```python
from kaco_instance import allocate_device_instance


def test_allocate_device_instance_requests_expected_setting_and_parses_result():
    calls = []

    def fake_settings_device_factory(dbus_conn, supported_settings, eventCallback=None):
        calls.append((dbus_conn, supported_settings, eventCallback))
        path, default_value, _min, _max = supported_settings['instance']
        # simulate Venus OS resolving a conflict to a different instance
        resolved_value = default_value.rsplit(':', 1)[0] + ':34'
        return {'instance': resolved_value}

    result = allocate_device_instance(
        dbus_conn='fake-bus', name='kaco_1', default_instance=20,
        service_type='pvinverter', settings_device_factory=fake_settings_device_factory,
    )

    assert result == 34
    dbus_conn, supported_settings, event_cb = calls[0]
    assert dbus_conn == 'fake-bus'
    assert supported_settings == {
        'instance': ['/Settings/Devices/kaco_1/ClassAndVrmInstance', 'pvinverter:20', 0, 0],
    }
    assert event_cb is None


def test_allocate_device_instance_uses_requested_default_when_not_taken():
    def fake_settings_device_factory(dbus_conn, supported_settings, eventCallback=None):
        path, default_value, _min, _max = supported_settings['instance']
        return {'instance': default_value}

    result = allocate_device_instance(
        dbus_conn='fake-bus', name='kaco_2', default_instance=21,
        service_type='temperature', settings_device_factory=fake_settings_device_factory,
    )

    assert result == 21
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_instance.py -v`
Expected: `ModuleNotFoundError: No module named 'kaco_instance'`

- [ ] **Step 3: Write `kaco_instance.py`**

```python
"""Collision-free, persistent D-Bus device-instance allocation.

Wraps velib_python's SettingsDevice so that each configured inverter gets a
stable /DeviceInstance that Venus OS's local settings service resolves
against every other device already registered on the system, keyed by a
caller-supplied stable identifier (not the physical device's IP address).

`settings_device_factory` defaults to the real `SettingsDevice` from
velib_python, imported lazily so this module has zero import-time
dependency on `dbus` (and stays unit-testable without it).
"""


def allocate_device_instance(dbus_conn, name, default_instance,
                              service_type='pvinverter', settings_device_factory=None):
    if settings_device_factory is None:
        from settingsdevice import SettingsDevice
        settings_device_factory = SettingsDevice

    setting_path = '/Settings/Devices/{}/ClassAndVrmInstance'.format(name)
    default_value = '{}:{}'.format(service_type, default_instance)

    settings = settings_device_factory(
        dbus_conn,
        {'instance': [setting_path, default_value, 0, 0]},
        eventCallback=None,
    )

    stored_value = settings['instance']
    return int(stored_value.split(':')[1])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_instance.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add kaco_instance.py tests/test_kaco_instance.py
git commit -m "Add collision-free device-instance allocation via Venus OS settings

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `KacoInverterDevice.update()` core logic

**Files:**
- Create: `kaco_inverter.py`
- Test: `tests/test_kaco_inverter_update.py`

**Interfaces:**
- Consumes: `decode_string, signed_short, scale_factor, victron_pv_state` from
  `kaco_registers` (Task 2); `InverterConfig` from `kaco_config` (Task 3).
- Produces: `KacoInverterDevice.__init__(self, config, pv_service, temp_service,
  modbus_client)` and `KacoInverterDevice.update(self) -> None`, which sets
  `pv_service['/Connected']`, `pv_service['/Ac/...']`, `pv_service['/StatusCode']`,
  `pv_service['/ErrorCode']`, `temp_service['/Connected']`, `temp_service['/Temperature']`
  via `__setitem__`, or sets both `/Connected` values to `0` and returns without raising
  on any Modbus error. `pv_service`/`temp_service` are duck-typed: anything supporting
  `__setitem__`. `modbus_client` is duck-typed: anything with
  `read_holding_registers(address, count, unit) -> object with .isError() and .registers`.
  Used by `KacoInverterDevice.create()` (Task 6) and `kaco_orchestrator.update_all()`
  (Task 7).

This task only implements `__init__` and `update()`; `create()` is added in Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_inverter_update.py`:

```python
import pytest

from kaco_config import InverterConfig
from kaco_inverter import KacoInverterDevice


class FakeRegisterResult:
    def __init__(self, registers, error=False):
        self.registers = registers
        self._error = error

    def isError(self):
        return self._error


class FakeModbusClient:
    def __init__(self, registers=None, error=False):
        self._registers = registers
        self._error = error

    def read_holding_registers(self, address, count, unit):
        return FakeRegisterResult(self._registers, error=self._error)


class FakeService(dict):
    def add_path(self, path, value, **kwargs):
        self[path] = value


def make_config():
    return InverterConfig(
        name='kaco_1', host='10.0.0.1', port=502, unit=2,
        position='ac-in', position_code=0, custom_name='Kaco One',
    )


def make_update_registers():
    registers = [0] * 50
    registers[4] = 0xFFFF   # current scale exponent -1 -> factor 0.1
    registers[1], registers[2], registers[3] = 100, 110, 120
    registers[11] = 0xFFFF  # voltage scale exponent -1 -> factor 0.1
    registers[8], registers[9], registers[10] = 2300, 2310, 2320
    registers[13] = 0       # power scale exponent 0 -> factor 1
    registers[12] = 5000
    registers[24] = 0xFFFD  # energy scale exponent -3 -> factor 0.001
    registers[22], registers[23] = 0, 123456
    registers[35] = 0xFFFF  # temperature scale exponent -1 -> factor 0.1
    registers[31] = 250
    registers[36] = 4
    registers[37] = 7
    return registers


def test_update_applies_decoded_values_to_both_services():
    pv_service = FakeService()
    temp_service = FakeService()
    device = KacoInverterDevice(
        make_config(), pv_service, temp_service,
        FakeModbusClient(registers=make_update_registers()),
    )

    device.update()

    assert pv_service['/Connected'] == 1
    assert pv_service['/Ac/L1/Current'] == 10.0
    assert pv_service['/Ac/L2/Current'] == 11.0
    assert pv_service['/Ac/L3/Current'] == 12.0
    assert pv_service['/Ac/Current'] == 33.0
    assert pv_service['/Ac/L1/Voltage'] == 230.0
    assert pv_service['/Ac/L2/Voltage'] == 231.0
    assert pv_service['/Ac/L3/Voltage'] == 232.0
    assert pv_service['/Ac/Power'] == 5000
    assert pv_service['/Ac/L1/Power'] == pytest.approx(1666.67)
    assert pv_service['/Ac/L2/Power'] == pytest.approx(1666.67)
    assert pv_service['/Ac/L3/Power'] == pytest.approx(1666.67)
    assert pv_service['/Ac/Energy/Forward'] == pytest.approx(0.123)
    assert pv_service['/Ac/L1/Energy/Forward'] == pytest.approx(0.041)
    assert pv_service['/StatusCode'] == 11
    assert pv_service['/ErrorCode'] == 7

    assert temp_service['/Connected'] == 1
    assert temp_service['/Temperature'] == 25.0


def test_update_marks_disconnected_on_modbus_error():
    pv_service = FakeService()
    temp_service = FakeService()
    device = KacoInverterDevice(
        make_config(), pv_service, temp_service,
        FakeModbusClient(registers=[0] * 50, error=True),
    )

    device.update()

    assert pv_service['/Connected'] == 0
    assert temp_service['/Connected'] == 0
    assert '/Ac/Power' not in pv_service
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_inverter_update.py -v`
Expected: `ModuleNotFoundError: No module named 'kaco_inverter'`

- [ ] **Step 3: Write `kaco_inverter.py`**

```python
"""Per-inverter Modbus <-> D-Bus bridge.

KacoInverterDevice owns one physical Kaco inverter's Modbus TCP connection
and its two D-Bus services (pvinverter, temperature). A Modbus fault on this
inverter is contained inside update() and never propagates - callers driving
several KacoInverterDevice instances can keep updating the others.
"""
import logging

from kaco_registers import decode_string, signed_short, scale_factor, victron_pv_state

log = logging.getLogger("DbusKaco")


class ModbusReadError(Exception):
    """Raised when a Modbus register read returns an error response."""


def _read_registers(modbus_client, unit, address, count):
    result = modbus_client.read_holding_registers(address, count, unit=unit)
    if result.isError():
        raise ModbusReadError(
            "error reading {} registers at {}: {}".format(count, address, result)
        )
    return result.registers


class KacoInverterDevice:
    def __init__(self, config, pv_service, temp_service, modbus_client):
        self.config = config
        self.pv_service = pv_service
        self.temp_service = temp_service
        self.modbus_client = modbus_client

    def update(self):
        try:
            registers = _read_registers(self.modbus_client, self.config.unit, 40072, 50)
            self._apply_registers(registers)
        except Exception as exc:
            log.error("inverter '%s': update failed: %s", self.config.name, exc)
            self.pv_service['/Connected'] = 0
            self.temp_service['/Connected'] = 0

    def _apply_registers(self, registers):
        sf = scale_factor(registers[4])
        raw_l1_current = registers[1] * sf
        raw_l2_current = registers[2] * sf
        raw_l3_current = registers[3] * sf

        sf = scale_factor(registers[11])
        l1_voltage = round(registers[8] * sf, 2)
        l2_voltage = round(registers[9] * sf, 2)
        l3_voltage = round(registers[10] * sf, 2)

        sf = scale_factor(registers[13])
        ac_power = signed_short(registers[12]) * sf
        phase_power = round(signed_short(registers[12]) * sf / 3, 2)

        sf = scale_factor(registers[24])
        raw_energy = float((registers[22] << 16) + registers[23])
        energy_forward = round(raw_energy * sf / 1000, 3)
        phase_energy_forward = round(raw_energy * sf / 3 / 1000, 3)

        sf = scale_factor(registers[35])
        temperature = round(registers[31] * sf, 2)

        self.pv_service['/Connected'] = 1
        self.pv_service['/Ac/L1/Current'] = round(raw_l1_current, 2)
        self.pv_service['/Ac/L2/Current'] = round(raw_l2_current, 2)
        self.pv_service['/Ac/L3/Current'] = round(raw_l3_current, 2)
        self.pv_service['/Ac/Current'] = round(raw_l1_current + raw_l2_current + raw_l3_current, 2)
        self.pv_service['/Ac/L1/Voltage'] = l1_voltage
        self.pv_service['/Ac/L2/Voltage'] = l2_voltage
        self.pv_service['/Ac/L3/Voltage'] = l3_voltage
        self.pv_service['/Ac/Power'] = ac_power
        self.pv_service['/Ac/L1/Power'] = phase_power
        self.pv_service['/Ac/L2/Power'] = phase_power
        self.pv_service['/Ac/L3/Power'] = phase_power
        self.pv_service['/Ac/Energy/Forward'] = energy_forward
        self.pv_service['/Ac/L1/Energy/Forward'] = phase_energy_forward
        self.pv_service['/Ac/L2/Energy/Forward'] = phase_energy_forward
        self.pv_service['/Ac/L3/Energy/Forward'] = phase_energy_forward
        self.pv_service['/StatusCode'] = victron_pv_state(registers[36])
        self.pv_service['/ErrorCode'] = registers[37]

        self.temp_service['/Connected'] = 1
        self.temp_service['/Temperature'] = temperature
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_inverter_update.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add kaco_inverter.py tests/test_kaco_inverter_update.py
git commit -m "Add KacoInverterDevice.update() with per-inverter fault isolation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `KacoInverterDevice.create()` bootstrap

**Files:**
- Modify: `kaco_inverter.py` (add `create()` classmethod and supporting constants/helpers)
- Test: `tests/test_kaco_inverter_create.py`

**Interfaces:**
- Consumes: `allocate_device_instance` from `kaco_instance` (Task 4); `decode_string` from
  `kaco_registers` (Task 2); `InverterConfig` from `kaco_config` (Task 3).
- Produces: `KacoInverterDevice.create(cls, config, dbus_conn, modbus_client_factory=None,
  vedbus_service_factory=None, instance_allocator=allocate_device_instance,
  instance_offset=0) -> KacoInverterDevice`. `modbus_client_factory` defaults to
  `pymodbus.client.sync.ModbusTcpClient` (lazy import) and is called as
  `modbus_client_factory(host, port)`. `vedbus_service_factory` defaults to
  `vedbus.VeDbusService` (lazy import) and is called as
  `vedbus_service_factory(service_name, dbus_conn)`, returning an object with
  `add_path(path, value, **kwargs)` and `__setitem__`. Raises `ConnectionError` if the
  Modbus connection cannot be opened. Used by `kaco_orchestrator.build_devices()`
  (Task 7).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_inverter_create.py`:

```python
import pytest

from kaco_config import InverterConfig
from kaco_inverter import KacoInverterDevice


class FakeRegisterResult:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):
        return False


class FakeModbusClient:
    def __init__(self, host, port, static_registers=None):
        self.host = host
        self.port = port
        self.auto_open = False
        self._static_registers = static_registers or [0] * 56

    def is_socket_open(self):
        return False

    def connect(self):
        return True

    def read_holding_registers(self, address, count, unit):
        return FakeRegisterResult(self._static_registers[:count])


class FailingModbusClient:
    def __init__(self, host, port):
        self.auto_open = False

    def is_socket_open(self):
        return False

    def connect(self):
        return False


class FakeVeDbusService:
    def __init__(self, service_name, dbus_conn):
        self.service_name = service_name
        self.dbus_conn = dbus_conn
        self.paths = {}

    def add_path(self, path, value, **kwargs):
        self.paths[path] = value

    def __setitem__(self, path, value):
        self.paths[path] = value


def make_fake_vedbus_factory():
    created = []

    def factory(service_name, dbus_conn):
        service = FakeVeDbusService(service_name, dbus_conn)
        created.append(service)
        return service

    factory.created = created
    return factory


def make_config():
    return InverterConfig(
        name='kaco_1', host='192.168.1.50', port=502, unit=2,
        position='ac-in', position_code=0, custom_name='Kaco Test',
    )


def make_static_registers():
    registers = [0] * 56
    registers[0] = (ord('K') << 8) | ord('a')    # -> "Ka" in ProductName part 1
    registers[16] = (ord('c') << 8) | ord('o')   # -> "co" in ProductName part 2
    registers[40] = (ord('v') << 8) | ord('1')   # -> "v1" FirmwareVersion
    registers[48] = (ord('S') << 8) | ord('N')   # -> "SN" Serial
    return registers


def test_create_wires_config_into_pv_and_temp_services():
    modbus_client = FakeModbusClient('192.168.1.50', 502, static_registers=make_static_registers())
    vedbus_factory = make_fake_vedbus_factory()
    instance_calls = []

    def fake_allocator(dbus_conn, name, default_instance, service_type='pvinverter'):
        instance_calls.append((name, default_instance, service_type))
        return default_instance

    device = KacoInverterDevice.create(
        make_config(), dbus_conn=object(),
        modbus_client_factory=lambda host, port: modbus_client,
        vedbus_service_factory=vedbus_factory,
        instance_allocator=fake_allocator,
        instance_offset=1,
    )

    pv_service, temp_service = vedbus_factory.created

    assert pv_service.service_name == 'com.victronenergy.pvinverter.kaco_1'
    assert pv_service.paths['/ProductName'] == 'Ka co'
    assert pv_service.paths['/FirmwareVersion'] == 'v1'
    assert pv_service.paths['/Serial'] == 'SN'
    assert pv_service.paths['/CustomName'] == 'Kaco Test'
    assert pv_service.paths['/Position'] == 0
    assert pv_service.paths['/DeviceInstance'] == 21

    assert temp_service.service_name == 'com.victronenergy.temperature.kaco_1_temp'
    assert temp_service.paths['/CustomName'] == 'Kaco Test Temperature'
    assert temp_service.paths['/DeviceInstance'] == 27

    assert instance_calls == [
        ('kaco_1', 21, 'pvinverter'),
        ('kaco_1_temp', 27, 'temperature'),
    ]
    assert device.modbus_client is modbus_client
    assert device.pv_service is pv_service
    assert device.temp_service is temp_service


def test_create_raises_when_modbus_connect_fails():
    with pytest.raises(ConnectionError):
        KacoInverterDevice.create(
            make_config(), dbus_conn=object(),
            modbus_client_factory=lambda host, port: FailingModbusClient(host, port),
            vedbus_service_factory=make_fake_vedbus_factory(),
            instance_allocator=lambda *a, **k: 20,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_inverter_create.py -v`
Expected: `AttributeError: type object 'KacoInverterDevice' has no attribute 'create'`

- [ ] **Step 3: Add `create()` to `kaco_inverter.py`**

Add these imports at the top of `kaco_inverter.py` (alongside the existing ones):

```python
from kaco_instance import allocate_device_instance
```

Add these module-level constants after the `log = logging.getLogger("DbusKaco")` line:

```python
VERSION = "0.1"
PRODUCT_ID_PVINVERTER = 41284  # value used in ac_sensor_bridge.cpp of dbus-cgwacs
DEFAULT_PV_INSTANCE_BASE = 20
DEFAULT_TEMP_INSTANCE_BASE = 26

_KWH = lambda p, v: (str(v) + 'kWh')
_A = lambda p, v: (str(v) + 'A')
_W = lambda p, v: (str(v) + 'W')
_V = lambda p, v: (str(v) + 'V')
_C = lambda p, v: (str(v) + 'C')
```

Add the `create()` classmethod and a `_add_management_paths` static helper to the
`KacoInverterDevice` class (after `__init__`, before `update`):

```python
    @classmethod
    def create(cls, config, dbus_conn, modbus_client_factory=None,
               vedbus_service_factory=None, instance_allocator=allocate_device_instance,
               instance_offset=0):
        if modbus_client_factory is None:
            from pymodbus.client.sync import ModbusTcpClient
            modbus_client_factory = ModbusTcpClient
        if vedbus_service_factory is None:
            from vedbus import VeDbusService
            vedbus_service_factory = VeDbusService

        modbus_client = modbus_client_factory(config.host, port=config.port)
        modbus_client.auto_open = True
        if not modbus_client.is_socket_open() and not modbus_client.connect():
            raise ConnectionError(
                "unable to connect to {}:{} (inverter '{}')".format(
                    config.host, config.port, config.name
                )
            )

        connection = "ModbusTCP {}:{}, UNIT {}".format(config.host, config.port, config.unit)
        registers = _read_registers(modbus_client, config.unit, 40004, 56)
        product_name = decode_string(registers[0:15]) + " " + decode_string(registers[16:31])
        firmware_version = decode_string(registers[40:43])
        serial = decode_string(registers[48:55])

        pv_instance = instance_allocator(
            dbus_conn, config.name, DEFAULT_PV_INSTANCE_BASE + instance_offset,
            service_type='pvinverter',
        )
        temp_instance = instance_allocator(
            dbus_conn, '{}_temp'.format(config.name), DEFAULT_TEMP_INSTANCE_BASE + instance_offset,
            service_type='temperature',
        )

        pv_service = vedbus_service_factory(
            'com.victronenergy.pvinverter.{}'.format(config.name), dbus_conn)
        cls._add_management_paths(pv_service)
        pv_service.add_path('/DeviceInstance', pv_instance)
        pv_service.add_path('/FirmwareVersion', firmware_version)
        pv_service.add_path('/DataManagerVersion', VERSION)
        pv_service.add_path('/Serial', serial)
        pv_service.add_path('/Mgmt/Connection', connection)
        pv_service.add_path('/ProductId', PRODUCT_ID_PVINVERTER)
        pv_service.add_path('/ProductName', product_name)
        pv_service.add_path('/CustomName', config.custom_name)
        pv_service.add_path('/Position', config.position_code)
        pv_service.add_path('/Ac/Energy/Forward', None, gettextcallback=_KWH)
        pv_service.add_path('/Ac/Power', None, gettextcallback=_W)
        pv_service.add_path('/Ac/L1/Current', None, gettextcallback=_A)
        pv_service.add_path('/Ac/L2/Current', None, gettextcallback=_A)
        pv_service.add_path('/Ac/L3/Current', None, gettextcallback=_A)
        pv_service.add_path('/Ac/Current', None, gettextcallback=_A)
        pv_service.add_path('/Ac/L1/Energy/Forward', None, gettextcallback=_KWH)
        pv_service.add_path('/Ac/L2/Energy/Forward', None, gettextcallback=_KWH)
        pv_service.add_path('/Ac/L3/Energy/Forward', None, gettextcallback=_KWH)
        pv_service.add_path('/Ac/L1/Power', None, gettextcallback=_W)
        pv_service.add_path('/Ac/L2/Power', None, gettextcallback=_W)
        pv_service.add_path('/Ac/L3/Power', None, gettextcallback=_W)
        pv_service.add_path('/Ac/L1/Voltage', None, gettextcallback=_V)
        pv_service.add_path('/Ac/L2/Voltage', None, gettextcallback=_V)
        pv_service.add_path('/Ac/L3/Voltage', None, gettextcallback=_V)
        pv_service.add_path('/Ac/MaxPower', None, gettextcallback=_W)
        pv_service.add_path('/ErrorCode', None)
        pv_service.add_path('/StatusCode', None)

        temp_service = vedbus_service_factory(
            'com.victronenergy.temperature.{}_temp'.format(config.name), dbus_conn)
        cls._add_management_paths(temp_service)
        temp_service.add_path('/DeviceInstance', temp_instance)
        temp_service.add_path('/FirmwareVersion', firmware_version)
        temp_service.add_path('/DataManagerVersion', VERSION)
        temp_service.add_path('/Serial', serial)
        temp_service.add_path('/Mgmt/Connection', connection)
        temp_service.add_path('/ProductName', product_name)
        temp_service.add_path('/ProductId', 0)
        temp_service.add_path('/CustomName', '{} Temperature'.format(config.custom_name))
        temp_service.add_path('/Temperature', None, gettextcallback=_C)
        temp_service.add_path('/Status', 0)
        temp_service.add_path('/TemperatureType', 0, writeable=True)

        return cls(config, pv_service, temp_service, modbus_client)

    @staticmethod
    def _add_management_paths(service):
        import platform
        service.add_path('/Mgmt/ProcessName', __file__)
        service.add_path(
            '/Mgmt/ProcessVersion',
            'Unknown version, and running on Python ' + platform.python_version(),
        )
        service.add_path('/Connected', 1)
        service.add_path('/HardwareVersion', 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_inverter_create.py tests/test_kaco_inverter_update.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run the full test suite so far**

Run: `.venv/bin/pytest -v`
Expected: all tests from Tasks 2-6 PASS

- [ ] **Step 6: Commit**

```bash
git add kaco_inverter.py tests/test_kaco_inverter_create.py
git commit -m "Add KacoInverterDevice.create() bootstrap with injectable factories

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Orchestrator (`kaco_orchestrator.py`)

**Files:**
- Create: `kaco_orchestrator.py`
- Test: `tests/test_kaco_orchestrator.py`

**Interfaces:**
- Consumes: `load_inverter_configs, ConfigError` from `kaco_config` (Task 3);
  `KacoInverterDevice` (specifically `KacoInverterDevice.create`) from `kaco_inverter`
  (Task 6).
- Produces: `build_devices(config_path: str, dbus_conn, device_factory=KacoInverterDevice.create)
  -> list[KacoInverterDevice]` (calls `sys.exit(1)` if config is invalid or zero devices
  start); `update_all(devices: list) -> bool` (always returns `True`, catches and logs
  per-device exceptions, used directly as a GLib timeout callback); `main() -> None`
  (real D-Bus/GLib wiring, not unit tested). Used by `dbus-kaco_blueplanet.py` (Task 8).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kaco_orchestrator.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kaco_orchestrator.py -v`
Expected: `ModuleNotFoundError: No module named 'kaco_orchestrator'`

- [ ] **Step 3: Write `kaco_orchestrator.py`**

```python
"""Wires config.ini, KacoInverterDevice instances and the GLib mainloop together.

build_devices() and update_all() take their D-Bus connection / device list as
parameters and are unit-testable without a real D-Bus session. main() does the
real D-Bus/GLib setup and is exercised only when the service actually runs.
"""
import logging
import os
import sys

from kaco_config import load_inverter_configs, ConfigError
from kaco_inverter import KacoInverterDevice

log = logging.getLogger("DbusKaco")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')


def build_devices(config_path, dbus_conn, device_factory=KacoInverterDevice.create):
    try:
        configs = load_inverter_configs(config_path)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        sys.exit(1)

    devices = []
    for offset, config in enumerate(configs):
        try:
            device = device_factory(config, dbus_conn, instance_offset=offset)
        except Exception as exc:
            log.error("inverter '%s': failed to start, skipping: %s", config.name, exc)
            continue
        log.info(
            "inverter '%s' online at %s:%s (position=%s)",
            config.name, config.host, config.port, config.position,
        )
        devices.append(device)

    if not devices:
        log.error("no inverters could be started, exiting")
        sys.exit(1)

    return devices


def update_all(devices):
    for device in devices:
        try:
            device.update()
        except Exception as exc:
            log.error(
                "inverter '%s': unexpected error during update: %s", device.config.name, exc
            )
    return True


def _configure_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)


def main():
    _configure_logging()
    log.info("Startup, loading configuration from %s", CONFIG_PATH)

    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    try:
        import gobject  # Python 2.x
    except ImportError:
        from gi.repository import GLib as gobject  # Python 3.x

    DBusGMainLoop(set_as_default=True)

    class SystemBus(dbus.bus.BusConnection):
        def __new__(cls):
            return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

    class SessionBus(dbus.bus.BusConnection):
        def __new__(cls):
            return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

    dbus_conn = SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

    devices = build_devices(CONFIG_PATH, dbus_conn)

    gobject.timeout_add(1000, update_all, devices)

    log.info("Connected to dbus, and switching over to GLib.MainLoop() (= event based)")
    mainloop = gobject.MainLoop()
    mainloop.run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kaco_orchestrator.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: all tests from Tasks 2-7 PASS

- [ ] **Step 6: Commit**

```bash
git add kaco_orchestrator.py tests/test_kaco_orchestrator.py
git commit -m "Add orchestrator wiring config, devices and GLib mainloop

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Entry point rewrite (`dbus-kaco_blueplanet.py`)

**Files:**
- Modify: `dbus-kaco_blueplanet.py` (full rewrite, replacing the entire current contents)

**Interfaces:**
- Consumes: `main` from `kaco_orchestrator` (Task 7).
- Produces: nothing importable — this is the process entry point invoked by
  `service/run` as `python /data/dbus-kaco_blueplanet/dbus-kaco_blueplanet.py`
  (path/filename unchanged).

- [ ] **Step 1: Replace the entire contents of `dbus-kaco_blueplanet.py`**

```python
#!/usr/bin/env python
"""Entry point for the Kaco Blueplanet multi-inverter Venus OS driver.

The daemontools service (see service/run) invokes this file directly by its
fixed path, so it stays a thin wrapper - the actual implementation lives in
the importable kaco_*.py modules alongside it (kaco_config, kaco_registers,
kaco_instance, kaco_inverter, kaco_orchestrator).
"""
import os
import sys

sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))

from kaco_orchestrator import main

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Verify it compiles**

Run: `python3 -m py_compile dbus-kaco_blueplanet.py kaco_orchestrator.py kaco_inverter.py kaco_config.py kaco_instance.py kaco_registers.py`
Expected: no output, exit code 0

- [ ] **Step 3: Verify the full unit test suite still passes**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS (this step doesn't touch anything tested, but confirms the
rewrite didn't break an import path)

- [ ] **Step 4: Commit**

```bash
git add dbus-kaco_blueplanet.py
git commit -m "Rewrite entry point as a thin wrapper around kaco_orchestrator

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: velib_python submodule and config template

**Files:**
- Create: `.gitmodules` (via `git submodule add`)
- Create: `ext/velib_python/` (submodule checkout)
- Create: `config.default.ini`

**Interfaces:**
- Produces: `ext/velib_python/vedbus.py` and `ext/velib_python/settingsdevice.py`,
  importable by `kaco_inverter.py`'s `create()` and `kaco_instance.py`'s
  `allocate_device_instance()` default paths (Task 6, Task 4) when running for real.
  `config.default.ini` is the template `install.sh` (Task 10) copies to `config.ini`
  when none exists.

- [ ] **Step 1: Add the velib_python submodule**

Run:
```bash
git submodule add https://github.com/victronenergy/velib_python.git ext/velib_python
```
Expected: `ext/velib_python` populated, `.gitmodules` created with:
```
[submodule "ext/velib_python"]
	path = ext/velib_python
	url = https://github.com/victronenergy/velib_python.git
```

- [ ] **Step 2: Verify `vedbus.py` and `settingsdevice.py` are present**

Run: `ls ext/velib_python/vedbus.py ext/velib_python/settingsdevice.py`
Expected: both paths printed, no error

- [ ] **Step 3: Create `config.default.ini`**

```ini
# dbus-kaco_blueplanet inverter configuration
#
# One [INVERTERx] section per physical Kaco inverter. The section name's
# suffix ("1", "2", ...) does not need to be sequential or match anything
# elsewhere - the driver picks up every section whose name starts with
# "INVERTER".
#
# name        - short, unique, stable identifier (letters/digits/underscore).
#               Used to build the D-Bus service name and the persisted
#               device-instance mapping. Do not change after first start, or
#               a new device instance will be allocated.
# host        - inverter's IP address or hostname
# port        - Modbus TCP port (usually 502)
# unit        - Modbus unit/slave ID configured on the inverter
# position    - "ac-in"  = inverter feeds in before the grid connection point
#               "ac-out" = inverter feeds in after the grid connection point
# custom_name - display name shown in the Venus OS device list

[INVERTER1]
name = kaco_1
host = 192.168.178.80
port = 502
unit = 2
position = ac-in
custom_name = Kaco Blueplanet 10.0 TL3

#[INVERTER2]
#name = kaco_2
#host = 192.168.178.81
#port = 502
#unit = 2
#position = ac-in
#custom_name = Kaco Blueplanet 8.6 TL3

#[INVERTER3]
#name = kaco_3
#host = 192.168.178.82
#port = 502
#unit = 2
#position = ac-out
#custom_name = Kaco Blueplanet 5.0 TL3
```

- [ ] **Step 4: Verify `config.default.ini` parses with `kaco_config.py`**

Run:
```bash
.venv/bin/python -c "
from kaco_config import load_inverter_configs
configs = load_inverter_configs('config.default.ini')
print([c.name for c in configs])
"
```
Expected: `['kaco_1']` (the commented-out sections are correctly ignored)

- [ ] **Step 5: Commit**

```bash
git add .gitmodules ext/velib_python config.default.ini
git commit -m "Vendor velib_python as a submodule, add config.ini template

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Install script (`install.sh`)

**Files:**
- Create: `install.sh`

**Interfaces:**
- Produces: an executable script with no importable interface, run manually on the
  GX device after `git clone`.

- [ ] **Step 1: Create `install.sh`**

```bash
#!/bin/bash
set -euo pipefail

DRIVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_NAME="dbus-kaco_blueplanet"
SERVICE_LINK="/opt/victronenergy/service/${DRIVER_NAME}"
RC_LOCAL="/data/rc.local"

echo "Installing ${DRIVER_NAME} from ${DRIVER_DIR}"

# 1. velib_python submodule
if [ ! -f "${DRIVER_DIR}/ext/velib_python/vedbus.py" ]; then
    echo "Fetching ext/velib_python submodule..."
    git -C "${DRIVER_DIR}" submodule update --init --recursive
fi

# 2. config.ini bootstrap (never overwrite an existing config)
if [ ! -f "${DRIVER_DIR}/config.ini" ]; then
    echo "No config.ini found, creating one from config.default.ini"
    cp "${DRIVER_DIR}/config.default.ini" "${DRIVER_DIR}/config.ini"
    echo "Edit ${DRIVER_DIR}/config.ini with your inverters' IP/port/position before starting the service."
fi

# 3. permissions
chmod 755 "${DRIVER_DIR}/service/run"
chmod 755 "${DRIVER_DIR}/service/log/run"
chmod 744 "${DRIVER_DIR}/kill_me.sh"

# 4. autostart symlink
mkdir -p /opt/victronenergy/service
ln -sfn "${DRIVER_DIR}/service" "${SERVICE_LINK}"

# 5. persist symlink across firmware updates via rc.local
if [ ! -f "${RC_LOCAL}" ]; then
    echo "#!/bin/bash" > "${RC_LOCAL}"
    chmod 755 "${RC_LOCAL}"
fi
RC_LINE="ln -sfn ${DRIVER_DIR}/service ${SERVICE_LINK}"
grep -qxF "${RC_LINE}" "${RC_LOCAL}" || echo "${RC_LINE}" >> "${RC_LOCAL}"

# 6. restart if already running
if pgrep -f "python ${DRIVER_DIR}/dbus-kaco_blueplanet.py" > /dev/null 2>&1; then
    echo "Restarting running service..."
    "${DRIVER_DIR}/kill_me.sh"
fi

echo "Done. The supervisor will (re)start ${DRIVER_NAME} within a few seconds."
echo "If this is a first-time install, edit ${DRIVER_DIR}/config.ini now, then rerun this script or run kill_me.sh."
```

- [ ] **Step 2: Make it executable**

Run: `chmod 755 install.sh`

- [ ] **Step 3: Syntax-check it**

Run: `bash -n install.sh`
Expected: no output, exit code 0

- [ ] **Step 4: Lint it if shellcheck is available (best-effort, non-blocking)**

Run: `command -v shellcheck >/dev/null 2>&1 && shellcheck install.sh || echo "shellcheck not installed, skipping"`
Expected: either shellcheck reports no issues, or the "not installed" message — the
script's paths (`/opt/victronenergy/...`, `/data/rc.local`) only exist on a real Venus
OS device, so full functional testing of `install.sh` happens in Task 12's manual
hardware verification, not here.

- [ ] **Step 5: Commit**

```bash
git add install.sh
git commit -m "Add install.sh: permissions, config bootstrap, autostart, restart

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: README rewrite

**Files:**
- Modify: `README.md` (full rewrite)

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Replace the entire contents of `README.md`**

```markdown
# dbus-kaco_blueplanet Service
Victron Venus integration for Kaco blueplanet 3.0 TL3 - 10 TL3 Inverters

### Purpose

This service is meant to be run on a raspberry Pi with Venus OS from Victron or a for example a Cerbo GX device.

The Python script cyclically reads data from one or more Kaco blueplanet Inverters via Sunspec Modbus and publishes information on the dbus, using per-inverter services `com.victronenergy.pvinverter.<name>` and `com.victronenergy.temperature.<name>_temp`. This makes the Venus OS work as if you had one or more physical Victron PV inverters installed, giving information about PV inverter load, temperature, and AC position (grid-side / load-side) for each configured inverter.

![Dashboard shows Energy flow](images/dashboard.png?raw=true "Dashboard")
![Menu shows Entries of the Inverter](images/menu.png?raw=true "Menu")

### Configuration

Configuration lives in `config.ini` (created automatically from `config.default.ini` on first install, never overwritten by later updates). Add one `[INVERTERx]` section per physical inverter:

```ini
[INVERTER1]
name = kaco_1
host = 192.168.178.80
port = 502
unit = 2
position = ac-in
custom_name = Kaco Blueplanet 10.0 TL3

[INVERTER2]
name = kaco_2
host = 192.168.178.81
port = 502
unit = 2
position = ac-in
custom_name = Kaco Blueplanet 8.6 TL3
```

- `name`: short, unique, stable identifier. Used to build the D-Bus service name and the persisted device-instance mapping. Don't change it after the first start.
- `host` / `port` / `unit`: this inverter's Modbus TCP address, port, and unit/slave ID.
- `position`: `ac-in` (feeds in before the grid connection point) or `ac-out` (feeds in after it).
- `custom_name`: display name shown in the Venus OS device list.

Any number of `[INVERTERx]` sections is supported; the suffix doesn't need to be sequential.

### Installation

1. You need root access to your GX Device (https://www.victronenergy.com/live/ccgx:root_access)

2. Clone this repository into `/data`:

   ```
   git clone --recurse-submodules https://github.com/lucienkerl/dbus-kaco_blueplanet /data/dbus-kaco_blueplanet
   ```

3. Run the installer:

   ```
   /data/dbus-kaco_blueplanet/install.sh
   ```

   This creates `config.ini` from the template (if it doesn't exist yet), sets file permissions, and registers the service for autostart, including across firmware updates.

4. Edit `/data/dbus-kaco_blueplanet/config.ini` with your inverters' IP address, port, position, and display name, then re-run `install.sh` (or `kill_me.sh`) to restart the service with the new configuration.

The supervisor should automatically start this service within seconds, if not simply reboot your system.

### Upgrading

```
cd /data/dbus-kaco_blueplanet
git pull
git submodule update --init --recursive
./install.sh
```

Your `config.ini` is preserved across upgrades.

### Debugging

You can check the status of the service with svstat:

`svstat /service/dbus-kaco_blueplanet`

It will show something like this:

`/service/dbus-kaco_blueplanet: up (pid 8179) 746 seconds`

If the number of seconds is always 0 or 1 or any other small number, it means that the service crashes and gets restarted all the time.

You could also take a look at the log-file:

`tail -f /var/log/dbus-kaco_blueplanet/current`

and see if there are any error messages. A single inverter being unreachable no longer stops the whole service — the affected inverter's D-Bus services report `/Connected = 0` and it keeps retrying every cycle, while the other configured inverters keep updating normally.

When you think that the script crashes, start it directly from the command line:

`python /data/dbus-kaco_blueplanet/dbus-kaco_blueplanet.py`

and see if it throws any error messages.

If the script stops with a `dbus.exceptions.NameExistsException` for one of the `com.victronenergy.pvinverter.*` or `com.victronenergy.temperature.*` names, it means that the service is still running or another service is using that name — check for duplicate `name` values across your `[INVERTERx]` sections in `config.ini`.

If you see a connection error for one of your inverters' IP addresses in the log, that inverter is unreachable. This can be a misconfiguration or another client already connected. Each inverter only accepts one concurrent Modbus client; if you need more than one client connection to the same inverter, use a modbus proxy like https://pypi.org/project/modbus-proxy/

#### Restart the script

If you want to restart the script, for example after changing `config.ini`, just run the following command:

`/data/dbus-kaco_blueplanet/kill_me.sh`

The supervisor will restart the script within a few seconds.

### Running the tests

The pure configuration/decoding/orchestration logic has a unit test suite that runs on any machine (no Venus OS, D-Bus, or Modbus hardware required):

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

### Hardware

In my installation at home, I am using the following Hardware:

- Kaco blueplanet 8.6 TL 3
- Kaco blueplanet 10.0 TL 3
- 1x Victron MultiPlus-II - Battery Inverter (one phase)
- Cerbo GX (tested Firmware version: v2.87 and v2.92)
- DIY Battery 16x 280AH Lifepo EVE Cells with BMS from Batrium

### Credits

I have shamelessly copied and adapted the code from https://github.com/h4ckst0ck/dbus-solaredge/blob/main/dbus-solaredge.py and the readme.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Rewrite README for config.ini-based multi-inverter setup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Final verification

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Run the full unit test suite**

Run: `.venv/bin/pytest -v`
Expected: all tests from Tasks 2-7 PASS, 0 failures

- [ ] **Step 2: Compile-check every Python file**

Run: `python3 -m py_compile dbus-kaco_blueplanet.py kaco_orchestrator.py kaco_inverter.py kaco_config.py kaco_instance.py kaco_registers.py`
Expected: no output, exit code 0

- [ ] **Step 3: Confirm no stray references to the old single-inverter globals remain**

Run: `grep -rn "SERVER_HOST\|SERVER_PORT\|dbusservice\[" --include='*.py' .`
Expected: no matches (these were part of the old monolithic script, fully replaced by
`config.ini` + `KacoInverterDevice`)

- [ ] **Step 4: Manual hardware verification (document results, not automatable from here)**

This step can only be performed on the actual GX device with real inverters, so record
the outcome in the PR description / commit message rather than in an automated test:

1. `git clone --recurse-submodules` the branch onto a test GX device (or `git pull` +
   `git submodule update --init --recursive` on an existing checkout), matching the
   README's Installation/Upgrading instructions.
2. Run `install.sh`, edit the generated `config.ini` with real inverter IPs/ports/positions.
3. Re-run `install.sh` (or `kill_me.sh`), then `svstat /service/dbus-kaco_blueplanet` to
   confirm the service is up and not crash-looping.
4. Check `tail -f /var/log/dbus-kaco_blueplanet/current` for one update cycle per
   configured inverter with no unexpected errors.
5. In the Venus OS device list (GUI v1 or GUI v2), confirm each inverter appears as a
   separate device with its configured `custom_name` and the correct AC position
   (`ac-in`/`ac-out`).
6. Temporarily unplug/block one inverter's network path and confirm: that inverter's
   `/Connected` goes to 0 in the log/GUI, while the other configured inverters keep
   updating normally (this is the fault-isolation requirement from the spec).
7. Reboot the GX device and confirm the service autostarts (validates the `rc.local`
   entry from `install.sh`).

- [ ] **Step 5: Final commit (only if any fixes were needed in Step 4)**

If hardware verification in Step 4 surfaces an issue, fix it, re-run the affected
task's tests, and commit the fix with a message describing what hardware testing found.
