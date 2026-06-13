#!/bin/bash
# uninstall.sh -- stop/disable the manager/bridge units and remove their files.
# Leaves /var/lib/nm report data in place. Run as root.
#
#   sudo deploy/uninstall.sh [manager.env]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="${1:-$ROOT/config/manager.env}"
[ "$(id -u)" -eq 0 ] || { echo "must run as root" >&2; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENVFILE" ] && source "$ENVFILE"
INSTALL_DIR="${INSTALL_DIR:-/opt/nm2munin}"

systemctl disable --now nm-mgr.service nm2munin.service 2>/dev/null || true
rm -f /etc/systemd/system/nm-mgr.service /etc/systemd/system/nm2munin.service
rm -f /etc/munin/munin-conf.d/dtn.conf
rm -rf "${INSTALL_DIR:?}"
systemctl daemon-reload

echo "uninstalled nm2munin manager; /var/lib/nm data left intact."
