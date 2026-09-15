# dbus-kaco_blueplanet Service
Victron Venus integration for Kaco blueplanet 3.0 TL3 - 10 TL3 Inverters

### Purpose

This service is meant to be run on a raspberry Pi with Venus OS from Victron or a for example a Cerbo GX device.

The Python script cyclically reads data from one or more Kaco blueplanet Inverters via Sunspec Modbus and publishes information on the dbus, using per-inverter services `com.victronenergy.pvinverter.<name>` and `com.victronenergy.temperature.<name>_temp`. This makes the Venus OS work as if you had one or more physical Victron PV inverters installed, giving information about PV inverter load, temperature, and AC position (grid-side / load-side) for each configured inverter.

![Dashboard shows Energy flow](images/dashboard.png?raw=true "Dashboard")
![Menu shows Entries of the Inverter](images/menu.png?raw=true "Menu")

### Configuration

Configuration lives in `config.ini` (created automatically from `config.default.ini` on first install, never overwritten by later updates). Add one `[INVERTERx]` section per physical inverter:

```ini
[INVERTER1]
name = kaco_1
host = 192.168.178.80
port = 502
unit = 2
position = ac-in
custom_name = Kaco Blueplanet 10.0 TL3

[INVERTER2]
name = kaco_2
host = 192.168.178.81
port = 502
unit = 2
position = ac-in
custom_name = Kaco Blueplanet 8.6 TL3
```

- `name`: short, unique, stable identifier. Used to build the D-Bus service name and the persisted device-instance mapping. Don't change it after the first start.
- `host` / `port` / `unit`: this inverter's Modbus TCP address, port, and unit/slave ID.
- `position`: `ac-in` (feeds in before the grid connection point) or `ac-out` (feeds in after it).
- `custom_name`: display name shown in the Venus OS device list.

Any number of `[INVERTERx]` sections is supported; the suffix doesn't need to be sequential.

### Installation

1. You need root access to your GX Device (https://www.victronenergy.com/live/ccgx:root_access)

2. Clone this repository into `/data`:

   ```
   git clone --recurse-submodules https://github.com/lucienkerl/dbus-kaco_blueplanet /data/dbus-kaco_blueplanet
   ```

3. Run the installer:

   ```
   /data/dbus-kaco_blueplanet/install.sh
   ```

   This creates `config.ini` from the template (if it doesn't exist yet), sets file permissions, and registers the service for autostart, including across firmware updates.

4. Edit `/data/dbus-kaco_blueplanet/config.ini` with your inverters' IP address, port, position, and display name, then re-run `install.sh` (or `kill_me.sh`) to restart the service with the new configuration.

The supervisor should automatically start this service within seconds, if not simply reboot your system.

### Upgrading

```
cd /data/dbus-kaco_blueplanet
git pull
git submodule update --init --recursive
./install.sh
```

Your `config.ini` is preserved across upgrades.

### Debugging

You can check the status of the service with svstat:

`svstat /service/dbus-kaco_blueplanet`

It will show something like this:

`/service/dbus-kaco_blueplanet: up (pid 8179) 746 seconds`

If the number of seconds is always 0 or 1 or any other small number, it means that the service crashes and gets restarted all the time.

You could also take a look at the log-file:

`tail -f /var/log/dbus-kaco_blueplanet/current`

and see if there are any error messages. A single inverter being unreachable no longer stops the whole service — the affected inverter's D-Bus services report `/Connected = 0` and it keeps retrying every cycle, while the other configured inverters keep updating normally. If an inverter is offline when the service *starts* (e.g. a GX device reboot at night, when Kaco inverters have powered off), it's queued and retried automatically every 60 seconds until it comes back online — no manual restart needed, and the service won't exit or crash-loop just because every inverter happens to be offline at boot.

When you think that the script crashes, start it directly from the command line:

`python /data/dbus-kaco_blueplanet/dbus-kaco_blueplanet.py`

and see if it throws any error messages.

If the script stops with a `dbus.exceptions.NameExistsException` for one of the `com.victronenergy.pvinverter.*` or `com.victronenergy.temperature.*` names, it means that the service is still running or another service is using that name — check for duplicate `name` values across your `[INVERTERx]` sections in `config.ini`.

If you see a connection error for one of your inverters' IP addresses in the log, that inverter is unreachable. This can be a misconfiguration or another client already connected. Each inverter only accepts one concurrent Modbus client; if you need more than one client connection to the same inverter, use a modbus proxy like https://pypi.org/project/modbus-proxy/

#### Restart the script

If you want to restart the script, for example after changing `config.ini`, just run the following command:

`/data/dbus-kaco_blueplanet/kill_me.sh`

The supervisor will restart the script within a few seconds.

### Running the tests

The pure configuration/decoding/orchestration logic has a unit test suite that runs on any machine (no Venus OS, D-Bus, or Modbus hardware required):

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

### Hardware

In my installation at home, I am using the following Hardware:

- Kaco blueplanet 8.6 TL 3
- Kaco blueplanet 10.0 TL 3
- 1x Victron MultiPlus-II - Battery Inverter (one phase)
- Cerbo GX (tested Firmware version: v2.87 and v2.92)
- DIY Battery 16x 280AH Lifepo EVE Cells with BMS from Batrium

### Credits

I have shamelessly copied and adapted the code from https://github.com/h4ckst0ck/dbus-solaredge/blob/main/dbus-solaredge.py and the readme.
