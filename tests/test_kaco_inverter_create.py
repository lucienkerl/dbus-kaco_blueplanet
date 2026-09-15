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
    def __init__(self, host, port, **kwargs):
        self.auto_open = False

    def is_socket_open(self):
        return False

    def connect(self):
        return False


class FakeVeDbusService:
    def __init__(self, service_name, dbus_conn, register=None):
        self.service_name = service_name
        self.dbus_conn = dbus_conn
        self.register_requested = register
        self.paths = {}
        self.registered = False
        self.deleted = False

    def add_path(self, path, value, **kwargs):
        self.paths[path] = value

    def __setitem__(self, path, value):
        self.paths[path] = value

    def register(self):
        self.registered = True

    def __del__(self):
        self.deleted = True


def make_fake_vedbus_factory():
    created = []

    def factory(service_name, dbus_conn, register=None):
        service = FakeVeDbusService(service_name, dbus_conn, register=register)
        created.append(service)
        return service

    factory.created = created
    return factory


def make_fake_dbus_connection_factory():
    created = []

    def factory():
        connection = object()
        created.append(connection)
        return connection

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

    connection_factory = make_fake_dbus_connection_factory()

    device = KacoInverterDevice.create(
        make_config(), dbus_conn=object(),
        modbus_client_factory=lambda host, port, **kwargs: modbus_client,
        vedbus_service_factory=vedbus_factory,
        instance_allocator=fake_allocator,
        dbus_connection_factory=connection_factory,
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

    assert pv_service.register_requested is False
    assert pv_service.registered is True
    assert temp_service.registered is True

    # Root-cause regression check: each VeDbusService must get its OWN
    # connection. dbus-python registers the mandatory '/' object export
    # per-Connection, so sharing one connection across both services makes
    # the second VeDbusService construction fail with "Can't register the
    # object-path handler for '/': there is already a handler".
    assert len(connection_factory.created) == 2
    assert pv_service.dbus_conn is not temp_service.dbus_conn


def test_create_raises_when_modbus_connect_fails():
    with pytest.raises(ConnectionError):
        KacoInverterDevice.create(
            make_config(), dbus_conn=object(),
            modbus_client_factory=lambda host, port, **kwargs: FailingModbusClient(host, port),
            vedbus_service_factory=make_fake_vedbus_factory(),
            instance_allocator=lambda *a, **k: 20,
            dbus_connection_factory=make_fake_dbus_connection_factory(),
        )


def test_create_cleans_up_pv_service_when_temp_service_registration_fails():
    modbus_client = FakeModbusClient('192.168.1.50', 502, static_registers=make_static_registers())
    created = []

    def vedbus_factory(service_name, dbus_conn, register=None):
        service = FakeVeDbusService(service_name, dbus_conn, register=register)
        if 'temperature' in service_name:
            def failing_register():
                raise RuntimeError("simulated registration failure")
            service.register = failing_register
        created.append(service)
        return service

    with pytest.raises(RuntimeError):
        KacoInverterDevice.create(
            make_config(), dbus_conn=object(),
            modbus_client_factory=lambda host, port, **kwargs: modbus_client,
            vedbus_service_factory=vedbus_factory,
            instance_allocator=lambda *a, **k: 20,
            dbus_connection_factory=make_fake_dbus_connection_factory(),
        )

    pv_service, temp_service = created
    assert pv_service.deleted is True
