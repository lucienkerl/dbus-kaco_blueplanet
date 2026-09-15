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
    assert pv_service['/Ac/Power'] is None


def test_update_clears_stale_measurements_after_prior_success_then_failure():
    pv_service = FakeService()
    temp_service = FakeService()
    device = KacoInverterDevice(
        make_config(), pv_service, temp_service,
        FakeModbusClient(registers=make_update_registers()),
    )
    device.update()
    assert pv_service['/Ac/Power'] == 5000  # sanity: first update succeeded

    device.modbus_client = FakeModbusClient(registers=[0] * 50, error=True)
    device.update()

    assert pv_service['/Connected'] == 0
    assert pv_service['/Ac/Power'] is None
    assert pv_service['/Ac/L1/Voltage'] is None
    assert pv_service['/StatusCode'] is None
    assert temp_service['/Connected'] == 0
    assert temp_service['/Temperature'] is None
