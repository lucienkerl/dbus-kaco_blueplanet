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
