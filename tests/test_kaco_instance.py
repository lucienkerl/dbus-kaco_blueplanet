from kaco_instance import allocate_device_instance


def test_allocate_device_instance_requests_expected_setting_and_parses_result():
    calls = []

    def fake_settings_device_factory(dbus_conn, supported_settings, eventCallback=None):
        calls.append((dbus_conn, supported_settings, eventCallback))
        path, default_value, _min, _max = supported_settings['instance']
        # simulate Venus OS resolving a conflict to a different instance
        resolved_value = default_value.rsplit(':', 1)[0] + ':34'
        return {'instance': resolved_value}

    result = allocate_device_instance(
        dbus_conn='fake-bus', name='kaco_1', default_instance=20,
        service_type='pvinverter', settings_device_factory=fake_settings_device_factory,
    )

    assert result == 34
    dbus_conn, supported_settings, event_cb = calls[0]
    assert dbus_conn == 'fake-bus'
    assert supported_settings == {
        'instance': ['/Settings/Devices/kaco_1/ClassAndVrmInstance', 'pvinverter:20', 0, 0],
    }
    assert event_cb is None


def test_allocate_device_instance_uses_requested_default_when_not_taken():
    def fake_settings_device_factory(dbus_conn, supported_settings, eventCallback=None):
        path, default_value, _min, _max = supported_settings['instance']
        return {'instance': default_value}

    result = allocate_device_instance(
        dbus_conn='fake-bus', name='kaco_2', default_instance=21,
        service_type='temperature', settings_device_factory=fake_settings_device_factory,
    )

    assert result == 21
