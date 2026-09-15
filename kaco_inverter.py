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
