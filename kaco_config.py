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
