def test_kaco_dbus_module_imports_without_dbus_installed():
    # kaco_dbus must not import the real `dbus` package at module scope, so
    # that it (and anything importing it) stays usable on a machine without
    # dbus-python installed - only calling new_dbus_connection() should need
    # the real `dbus` package.
    import kaco_dbus

    assert hasattr(kaco_dbus, 'new_dbus_connection')
