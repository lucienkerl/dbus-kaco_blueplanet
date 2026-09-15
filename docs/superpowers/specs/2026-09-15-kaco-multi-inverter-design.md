# Multi-Inverter Support for dbus-kaco_blueplanet

## Problem

The driver currently supports exactly one Kaco Blueplanet inverter, configured via
hardcoded constants (`SERVER_HOST`, `SERVER_PORT`, `UNIT`) at the top of
`dbus-kaco_blueplanet.py`. The user has 3 physical inverters and wants a single
plugin/process that connects to all of them over Modbus TCP, each with its own
IP address, Modbus port, and AC position (`ac-in` vs `ac-out`).

The existing `vedbus`/`velib_python` import path
(`/opt/victronenergy/dbus-modem`) does not exist on current Venus OS and is
dead code inherited from the project this driver was originally copied from.

## Research: current Venus OS conventions

- **velib_python**: current official pattern (used by Victron's own
  `dbus-modbus-client`, the reference multi-device Modbus driver bundled in
  Venus OS) is to vendor `velib_python` as a git submodule at
  `ext/velib_python` and import `vedbus`/`settingsdevice` from there, rather
  than relying on another package's install path on the target device.
- **Multi-device pattern**: `dbus-modbus-client` creates one `VeDbusService`
  per physical device inside a single process, with the D-Bus service name
  built from a stable per-device identifier
  (`com.victronenergy.<role>.<ident>`), and obtains its `/DeviceInstance` via
  the local settings mechanism (`/Settings/Devices/<ident>/ClassAndVrmInstance`
  through `SettingsDevice`), which allocates a collision-free instance number
  system-wide and persists it against the identifier.
- **`/Position`** on `com.victronenergy.pvinverter` is documented (Venus OS
  D-Bus API wiki, matched against `gui-v2`'s `enums.h`) as `0 = AC input`,
  `1 = AC output`, `2 = AC input 2`. This maps directly to the requested
  `ac-in`/`ac-out` per-inverter setting.
- **GUI v2** reads pvinverter data purely from the standard D-Bus paths
  (`/CustomName`, `/Connected`, `/Position`, `/Ac/*`); multiple services with
  distinct `/CustomName` values show as distinct devices automatically, with
  no GUI-v2-specific integration work required.
- **Packaging**: SetupHelper (kwindrem) remains the de facto standard for
  Package-Manager-installable drivers, but is significant additional scope
  (PackageInfo, dependency declarations, FileSets) not justified for this
  project. A simpler, self-contained `install.sh` (inspired by, but far
  smaller than, `mr-manuel/venus-os_dbus-serialbattery`'s installer) covers
  the actual need: permissions, config bootstrap, autostart symlink,
  `rc.local` persistence across firmware updates, service restart.

## Design

### Architecture

Replace the single global Modbus client and global `dbusservice` dict with a
`KacoInverterDevice` class (new file `kaco_inverter.py`) that owns, per
physical inverter:

- its own `ModbusTcpClient` connection (own host/port/unit)
- its own `com.victronenergy.pvinverter.<name>` `VeDbusService`
- its own `com.victronenergy.temperature.<name>_temp` `VeDbusService`
- an `update()` method that reads registers and updates both services'
  D-Bus paths for that inverter only

The main script (`dbus-kaco_blueplanet.py`) becomes an orchestrator: it loads
`config.ini`, iterates over every `[INVERTER*]` section (count is not
hardcoded — "several" stays arbitrary, not fixed at 3), instantiates one
`KacoInverterDevice` per section, and registers a single shared GLib timer
that calls `update()` on every configured device once per second.

**Fault isolation**: a Modbus error on one inverter (timeout, connection
refused, register read error) must not take down the whole process (today's
`sys.exit()` on any Modbus error). Each `KacoInverterDevice.update()` catches
its own exceptions, logs them, sets `/Connected = 0` on its own services, and
retries on the next cycle (`auto_open=True` on the Modbus client handles
reconnection) — independently of the other configured inverters.

### File layout

```
dbus-kaco_blueplanet.py     # orchestrator: load config.ini, build devices, run mainloop
kaco_inverter.py            # KacoInverterDevice class
config.default.ini          # versioned template with example section(s) + comments
config.ini                  # actual user config (gitignored), created from template by install.sh
install.sh                  # permissions, config bootstrap, autostart symlink, rc.local, restart
kill_me.sh                  # unchanged, manual restart helper
ext/velib_python/           # git submodule (vedbus.py, settingsdevice.py)
service/run, service/log/run
README.md                   # rewritten for multi-inverter config.ini workflow
```

### config.ini schema

One `[INVERTERx]` section per physical inverter, `x` arbitrary/unused by code
(sections are discovered by prefix, not by a fixed count):

```ini
[INVERTER1]
; Short, unique, stable identifier. Used to build the D-Bus service name and
; the persisted device-instance mapping. Do not change after first start, or
; a new device instance will be allocated.
name = kaco_1
host = 192.168.178.80
port = 502
unit = 2
; ac-in  = inverter feeds in before the grid connection point (Position 0)
; ac-out = inverter feeds in after the grid connection point (Position 1)
position = ac-in
custom_name = Kaco Blueplanet 10.0 TL3
```

`position` must be exactly `ac-in` or `ac-out`; any other value is a fatal
startup error with a clear message (no silent fallback).

### D-Bus service naming and device-instance allocation

- Service names: `com.victronenergy.pvinverter.{name}` and
  `com.victronenergy.temperature.{name}_temp`.
- Device instance: on startup, each `KacoInverterDevice` requests its
  `/DeviceInstance` via `SettingsDevice` against
  `/Settings/Devices/{name}/ClassAndVrmInstance`, proposing a default
  (`pvinverter:20`, incrementing per section order in the config file, e.g.
  21, 22, ...). Venus OS's settings service resolves collisions against any
  other device already registered on the system (any manufacturer/driver) and
  persists the resulting instance against `name`, independent of IP address
  or config file ordering.

### Install script (`install.sh`)

Run once after `git clone` into `/data/dbus-kaco_blueplanet`:

1. Initialize the `ext/velib_python` submodule if missing
   (`git submodule update --init`).
2. Create `config.ini` from `config.default.ini` only if `config.ini` does
   not already exist (never overwrites user config on update/`git pull`).
3. Set executable permissions on `service/run`, `service/log/run`,
   `kill_me.sh`.
4. Create/refresh the autostart symlink:
   `ln -sf /data/dbus-kaco_blueplanet/service /opt/victronenergy/service/dbus-kaco_blueplanet`.
5. Idempotently add the symlink command to `/data/rc.local` so it survives
   firmware upgrades (matching today's manual README step).
6. Restart the service if already running (equivalent of `kill_me.sh`; the
   daemontools supervisor restarts it automatically).

Explicitly out of scope: SetupHelper/Package-Manager packaging, release-tarball
download, Bluetooth/CAN/MQTT-style transport switching — none of that is
needed for this driver.

### README

Rewritten to reflect: `git clone` + `./install.sh` instead of manual file
copying; `config.ini` with a multi-inverter example instead of editing Python
constants; a short explanation of `position = ac-in` / `ac-out`.

## Out of scope

- SetupHelper/Package Manager packaging.
- Automatic discovery of inverters on the network.
- Support for AC input 2 (`/Position = 2`) — not requested; only `ac-in` /
  `ac-out` are supported. Can be added later as a third accepted `position`
  value if needed.
- Replicating the currently-unused, already-commented-out `grid` and
  `limit_pvinverter` service types.
