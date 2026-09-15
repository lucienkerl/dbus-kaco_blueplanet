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
