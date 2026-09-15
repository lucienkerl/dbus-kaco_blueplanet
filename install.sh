#!/bin/bash
#
# One-paste installer for dbus-kaco_blueplanet.
#
# Venus OS/GX devices don't ship git by default, so this script never uses
# git - it downloads plain branch tarballs over HTTPS (wget + tar, both
# standard on Venus OS) and extracts them directly to /data.
#
# Usage - paste this on the GX device over SSH:
#
#   wget -qO- https://raw.githubusercontent.com/lucienkerl/dbus-kaco_blueplanet/main/install.sh | bash
#
# Re-pasting the exact same command later re-installs the latest code from
# the "main" branch while preserving your existing config.ini.

set -euo pipefail

REPO_OWNER="lucienkerl"
REPO_NAME="dbus-kaco_blueplanet"
REPO_BRANCH="main"
VELIB_OWNER="victronenergy"
VELIB_REPO="velib_python"
VELIB_BRANCH="master"

DRIVER_DIR="/data/${REPO_NAME}"
SERVICE_LINK="/opt/victronenergy/service/${REPO_NAME}"
RC_LOCAL="/data/rc.local"

WORK_DIR="$(mktemp -d "/tmp/${REPO_NAME}-install.XXXXXX")"
trap 'rm -rf "${WORK_DIR}"' EXIT

echo "Installing ${REPO_NAME} into ${DRIVER_DIR} ..."

# 1. Download and extract the driver itself (fails fast, before anything
#    already installed is touched, if the network or GitHub is unreachable)
echo "Downloading ${REPO_OWNER}/${REPO_NAME}@${REPO_BRANCH} ..."
wget -q -O "${WORK_DIR}/repo.tar.gz" \
    "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REPO_BRANCH}.tar.gz"
tar -xzf "${WORK_DIR}/repo.tar.gz" -C "${WORK_DIR}"
STAGED_DIR="${WORK_DIR}/${REPO_NAME}-${REPO_BRANCH}"

# 2. Download and extract velib_python. The driver's own git repo pins this
#    as a git submodule for development, but since git isn't guaranteed to
#    be installed here, fetch it as a plain tarball and drop it into the
#    same ext/velib_python location instead.
echo "Downloading ${VELIB_OWNER}/${VELIB_REPO}@${VELIB_BRANCH} ..."
wget -q -O "${WORK_DIR}/velib.tar.gz" \
    "https://github.com/${VELIB_OWNER}/${VELIB_REPO}/archive/refs/heads/${VELIB_BRANCH}.tar.gz"
tar -xzf "${WORK_DIR}/velib.tar.gz" -C "${WORK_DIR}"
rm -rf "${STAGED_DIR}/ext/velib_python"
mkdir -p "${STAGED_DIR}/ext"
mv "${WORK_DIR}/${VELIB_REPO}-${VELIB_BRANCH}" "${STAGED_DIR}/ext/velib_python"

# 3. Carry an existing config.ini over into the freshly staged copy - it's
#    gitignored, so it's never part of the downloaded tarball.
if [ -f "${DRIVER_DIR}/config.ini" ]; then
    cp "${DRIVER_DIR}/config.ini" "${STAGED_DIR}/config.ini"
    echo "Kept existing config.ini."
else
    cp "${STAGED_DIR}/config.default.ini" "${STAGED_DIR}/config.ini"
    echo "No existing config.ini found, created one from config.default.ini."
    echo "Edit ${DRIVER_DIR}/config.ini with your inverters' IP/port/position before starting the service."
fi

# 4. Swap the staged copy into place (everything above ran against a
#    scratch directory - this is the only step that touches the live
#    installation, and only once the new copy is fully assembled).
rm -rf "${DRIVER_DIR}"
mkdir -p "$(dirname "${DRIVER_DIR}")"
mv "${STAGED_DIR}" "${DRIVER_DIR}"

# 5. Permissions (the tarball preserves the executable bit, but set it
#    explicitly too in case the extraction tool doesn't)
chmod 755 "${DRIVER_DIR}/service/run"
chmod 755 "${DRIVER_DIR}/service/log/run"
chmod 744 "${DRIVER_DIR}/kill_me.sh"
chmod 755 "${DRIVER_DIR}/install.sh"

# 6. Autostart symlink
mkdir -p /opt/victronenergy/service
ln -sfn "${DRIVER_DIR}/service" "${SERVICE_LINK}"

# 7. Persist symlink across firmware updates via rc.local
if [ ! -f "${RC_LOCAL}" ]; then
    echo "#!/bin/bash" > "${RC_LOCAL}"
    chmod 755 "${RC_LOCAL}"
fi
RC_LINE="ln -sfn ${DRIVER_DIR}/service ${SERVICE_LINK}"
grep -qxF "${RC_LINE}" "${RC_LOCAL}" || echo "${RC_LINE}" >> "${RC_LOCAL}"

# 8. Restart if already running
if pgrep -f "python ${DRIVER_DIR}/dbus-kaco_blueplanet.py" > /dev/null 2>&1; then
    echo "Restarting running service..."
    "${DRIVER_DIR}/kill_me.sh"
fi

echo
echo "Done. The supervisor will (re)start ${REPO_NAME} within a few seconds."
echo "If this is a first-time install, edit ${DRIVER_DIR}/config.ini now, then run"
echo "  ${DRIVER_DIR}/kill_me.sh"
echo "to restart the service with the new configuration."
