"""Collision-free, persistent D-Bus device-instance allocation.

Wraps velib_python's SettingsDevice so that each configured inverter gets a
stable /DeviceInstance that Venus OS's local settings service resolves
against every other device already registered on the system, keyed by a
caller-supplied stable identifier (not the physical device's IP address).

`settings_device_factory` defaults to the real `SettingsDevice` from
velib_python, imported lazily so this module has zero import-time
dependency on `dbus` (and stays unit-testable without it).
"""


def allocate_device_instance(dbus_conn, name, default_instance,
                              service_type='pvinverter', settings_device_factory=None):
    if settings_device_factory is None:
        from settingsdevice import SettingsDevice
        settings_device_factory = SettingsDevice

    setting_path = '/Settings/Devices/{}/ClassAndVrmInstance'.format(name)
    default_value = '{}:{}'.format(service_type, default_instance)

    settings = settings_device_factory(
        dbus_conn,
        {'instance': [setting_path, default_value, 0, 0]},
        eventCallback=None,
    )

    stored_value = settings['instance']
    return int(stored_value.split(':')[1])
