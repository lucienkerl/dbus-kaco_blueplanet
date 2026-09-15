#!/bin/bash
set -euo pipefail

DRIVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_NAME="dbus-kaco_blueplanet"
SERVICE_LINK="/opt/victronenergy/service/${DRIVER_NAME}"
RC_LOCAL="/data/rc.local"

echo "Installing ${DRIVER_NAME} from ${DRIVER_DIR}"

# 1. velib_python submodule
if [ ! -f "${DRIVER_DIR}/ext/velib_python/vedbus.py" ]; then
    echo "Fetching ext/velib_python submodule..."
    git -C "${DRIVER_DIR}" submodule update --init --recursive
fi

# 2. config.ini bootstrap (never overwrite an existing config)
if [ ! -f "${DRIVER_DIR}/config.ini" ]; then
    echo "No config.ini found, creating one from config.default.ini"
    cp "${DRIVER_DIR}/config.default.ini" "${DRIVER_DIR}/config.ini"
    echo "Edit ${DRIVER_DIR}/config.ini with your inverters' IP/port/position before starting the service."
fi

# 3. permissions
chmod 755 "${DRIVER_DIR}/service/run"
chmod 755 "${DRIVER_DIR}/service/log/run"
chmod 744 "${DRIVER_DIR}/kill_me.sh"

# 4. autostart symlink
mkdir -p /opt/victronenergy/service
ln -sfn "${DRIVER_DIR}/service" "${SERVICE_LINK}"

# 5. persist symlink across firmware updates via rc.local
if [ ! -f "${RC_LOCAL}" ]; then
    echo "#!/bin/bash" > "${RC_LOCAL}"
    chmod 755 "${RC_LOCAL}"
fi
RC_LINE="ln -sfn ${DRIVER_DIR}/service ${SERVICE_LINK}"
grep -qxF "${RC_LINE}" "${RC_LOCAL}" || echo "${RC_LINE}" >> "${RC_LOCAL}"

# 6. restart if already running
if pgrep -f "python ${DRIVER_DIR}/dbus-kaco_blueplanet.py" > /dev/null 2>&1; then
    echo "Restarting running service..."
    "${DRIVER_DIR}/kill_me.sh"
fi

echo "Done. The supervisor will (re)start ${DRIVER_NAME} within a few seconds."
echo "If this is a first-time install, edit ${DRIVER_DIR}/config.ini now, then rerun this script or run kill_me.sh."
