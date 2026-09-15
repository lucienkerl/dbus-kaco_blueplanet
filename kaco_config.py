"""Loads and validates config.ini describing the configured Kaco inverters."""
import configparser
import re
from dataclasses import dataclass

VALID_POSITIONS = {'ac-in': 0, 'ac-out': 1}
REQUIRED_KEYS = ('name', 'host', 'port', 'unit', 'position', 'custom_name')
NAME_PATTERN = re.compile(r'^[A-Za-z0-9_]+$')


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

    _check_duplicate_names(configs)

    return configs


def _check_duplicate_names(configs):
    seen = set()
    for config in configs:
        if config.name in seen:
            raise ConfigError(
                "Duplicate inverter name '{}' - each [INVERTERx] section needs a "
                "unique name.".format(config.name)
            )
        seen.add(config.name)


def _parse_section(section_name, values):
    missing = [key for key in REQUIRED_KEYS if key not in values]
    if missing:
        raise ConfigError(
            "Section [{}] is missing required key(s): {}".format(
                section_name, ", ".join(missing)
            )
        )

    name = values['name']
    host = values['host']
    position = values['position']
    custom_name = values['custom_name']

    try:
        port = values.getint('port')
        unit = values.getint('unit')
    except ValueError as exc:
        raise ConfigError(
            "Section [{}]: 'port' and 'unit' must be integers: {}".format(section_name, exc)
        ) from exc

    if not NAME_PATTERN.match(name):
        raise ConfigError(
            "Section [{}] has invalid name '{}'. Use only letters, digits and "
            "underscore.".format(section_name, name)
        )

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
