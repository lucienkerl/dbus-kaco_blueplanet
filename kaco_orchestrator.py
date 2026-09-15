"""Wires config.ini, KacoInverterDevice instances and the GLib mainloop together.

build_devices()/retry_pending()/update_all() take their D-Bus connection, device
list and pending-config list as parameters and are unit-testable without a real
D-Bus session. main() does the real D-Bus/GLib setup and is exercised only when
the service actually runs.

Startup fault isolation covers two failure modes: an inverter that goes
unreachable mid-run (handled inside KacoInverterDevice.update()) and an
inverter that is unreachable when the process starts (handled here via
build_devices()/retry_pending() - it's retried on a slower timer instead of
being permanently abandoned, since these inverters commonly power off
overnight and a GX reboot can happen while they're asleep).
"""
import logging
import os
import sys

from kaco_config import load_inverter_configs, ConfigError
from kaco_inverter import KacoInverterDevice

log = logging.getLogger("DbusKaco")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
RETRY_INTERVAL_MS = 60000


def _try_start(config, dbus_conn, instance_offset, device_factory):
    try:
        device = device_factory(config, dbus_conn, instance_offset=instance_offset)
    except Exception as exc:
        log.error("inverter '%s': failed to start, will retry: %s", config.name, exc)
        return None
    log.info(
        "inverter '%s' online at %s:%s (position=%s)",
        config.name, config.host, config.port, config.position,
    )
    return device


def build_devices(config_path, dbus_conn, device_factory=KacoInverterDevice.create):
    """Load config.ini and attempt to start every configured inverter once.

    Returns (active_devices, pending) - `pending` is a list of
    (config, instance_offset) tuples for inverters that failed to start; pass
    it to retry_pending() to keep retrying them. Only raises SystemExit if
    config.ini itself is invalid - an inverter being unreachable at startup
    is not fatal, since it will be retried.
    """
    try:
        configs = load_inverter_configs(config_path)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        sys.exit(1)

    active = []
    pending = []
    for offset, config in enumerate(configs):
        device = _try_start(config, dbus_conn, offset, device_factory)
        if device is not None:
            active.append(device)
        else:
            pending.append((config, offset))

    if not active:
        log.error(
            "no inverters could be started at startup (%d pending retry)", len(pending)
        )

    return active, pending


def retry_pending(pending, active_devices, dbus_conn, device_factory=KacoInverterDevice.create):
    """GLib timer callback: retry every inverter still in `pending`.

    Mutates both `pending` and `active_devices` in place so the caller's
    references stay valid across repeated calls. Always returns True to keep
    the GLib timer repeating.
    """
    still_pending = []
    for config, offset in pending:
        device = _try_start(config, dbus_conn, offset, device_factory)
        if device is not None:
            active_devices.append(device)
        else:
            still_pending.append((config, offset))
    pending[:] = still_pending
    return True


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

    active_devices, pending = build_devices(CONFIG_PATH, dbus_conn)

    gobject.timeout_add(1000, update_all, active_devices)
    gobject.timeout_add(RETRY_INTERVAL_MS, retry_pending, pending, active_devices, dbus_conn)

    log.info("Connected to dbus, and switching over to GLib.MainLoop() (= event based)")
    mainloop = gobject.MainLoop()
    mainloop.run()
