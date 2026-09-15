"""D-Bus connection helper.

dbus-python registers a dbus.service.Object's handler for a given object
path on the raw Connection instance it is given - not scoped per bus name.
VeDbusService always exports an object at '/' (VeDbusRootExport), so two
VeDbusService instances that share one Connection collide with "Can't
register the object-path handler for '/': there is already a handler" as
soon as the second one is constructed.

Each VeDbusService therefore needs its own, genuinely separate connection
to the bus. dbus.SystemBus()/dbus.SessionBus() return a cached, shared
connection singleton, which is exactly what must be avoided here - so this
instantiates dbus.bus.BusConnection directly (bypassing that cache) and
returns a brand new connection every call, matching the pattern used by the
single-inverter version of this driver and by Victron's own multi-device
drivers.
"""
import os


def new_dbus_connection():
    """Return a brand new, private connection to the system (or session) bus."""
    import dbus.bus

    class _SystemBus(dbus.bus.BusConnection):
        def __new__(cls):
            return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

    class _SessionBus(dbus.bus.BusConnection):
        def __new__(cls):
            return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

    return _SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else _SystemBus()
