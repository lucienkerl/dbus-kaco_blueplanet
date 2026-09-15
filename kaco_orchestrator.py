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
