"""Per-inverter Modbus <-> D-Bus bridge.

KacoInverterDevice owns one physical Kaco inverter's Modbus TCP connection
and its two D-Bus services (pvinverter, temperature). A Modbus fault on this
inverter is contained inside update() and never propagates - callers driving
several KacoInverterDevice instances can keep updating the others.
"""
import logging

from kaco_instance import allocate_device_instance
from kaco_registers import decode_string, signed_short, scale_factor, victron_pv_state

log = logging.getLogger("DbusKaco")

VERSION = "0.1"
PRODUCT_ID_PVINVERTER = 41284  # value used in ac_sensor_bridge.cpp of dbus-cgwacs
DEFAULT_PV_INSTANCE_BASE = 20
DEFAULT_TEMP_INSTANCE_BASE = 26
MODBUS_TIMEOUT_SECONDS = 2

_KWH = lambda p, v: (str(v) + 'kWh')
_A = lambda p, v: (str(v) + 'A')
_W = lambda p, v: (str(v) + 'W')
_V = lambda p, v: (str(v) + 'V')
_C = lambda p, v: (str(v) + 'C')

_STALE_ON_DISCONNECT_PATHS = (
    '/Ac/Power',
    '/Ac/L1/Power', '/Ac/L2/Power', '/Ac/L3/Power',
    '/Ac/Current', '/Ac/L1/Current', '/Ac/L2/Current', '/Ac/L3/Current',
    '/Ac/L1/Voltage', '/Ac/L2/Voltage', '/Ac/L3/Voltage',
    '/StatusCode', '/ErrorCode',
)


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

    @classmethod
    def create(cls, config, dbus_conn, modbus_client_factory=None,
               vedbus_service_factory=None, instance_allocator=allocate_device_instance,
               dbus_connection_factory=None, instance_offset=0):
        if modbus_client_factory is None:
            from pymodbus.client.sync import ModbusTcpClient
            modbus_client_factory = ModbusTcpClient
        if vedbus_service_factory is None:
            from vedbus import VeDbusService
            vedbus_service_factory = VeDbusService
        if dbus_connection_factory is None:
            from kaco_dbus import new_dbus_connection
            dbus_connection_factory = new_dbus_connection

        modbus_client = modbus_client_factory(
            config.host, port=config.port, timeout=MODBUS_TIMEOUT_SECONDS)
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

        # Each VeDbusService must get its own, separate connection: dbus-python
        # registers the mandatory '/' object export per-Connection, so two
        # services sharing one connection collide on the second registration.
        pv_service = vedbus_service_factory(
            'com.victronenergy.pvinverter.{}'.format(config.name),
            dbus_connection_factory(), register=False)
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
            'com.victronenergy.temperature.{}_temp'.format(config.name),
            dbus_connection_factory(), register=False)
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

        try:
            pv_service.register()
            temp_service.register()
        except Exception:
            pv_service.__del__()
            temp_service.__del__()
            raise

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

    def update(self):
        try:
            registers = _read_registers(self.modbus_client, self.config.unit, 40072, 50)
            self._apply_registers(registers)
        except Exception as exc:
            log.error("inverter '%s': update failed: %s", self.config.name, exc)
            self.pv_service['/Connected'] = 0
            for path in _STALE_ON_DISCONNECT_PATHS:
                self.pv_service[path] = None
            self.temp_service['/Connected'] = 0
            self.temp_service['/Temperature'] = None

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
