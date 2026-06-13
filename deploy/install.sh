#!/bin/bash
# install.sh -- install the nm2munin manager/bridge onto THIS host. Run as root.
#
#   sudo deploy/install.sh [manager.env]
#
# Renders from the env file (default config/manager.env), copies the daemons,
# units and Munin node map into place, reloads systemd and enables the units.
# Prerequisite: an ION node + nm-agent already run on this host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="${1:-$ROOT/config/manager.env}"
[ "$(id -u)" -eq 0 ] || { echo "install.sh must run as root" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENVFILE"

OUT="$ROOT/build/manager"
"$ROOT/deploy/render.sh" "$ENVFILE" "$OUT"

id "$ION_USER" >/dev/null 2>&1 || useradd --system --home /var/lib/ion --shell /usr/sbin/nologin "$ION_USER"
install -d -o "$ION_USER" -g "$ION_GROUP" /var/lib/nm /var/lib/nm/reports "$INSTALL_DIR"

install -o "$ION_USER" -g "$ION_GROUP" -m 0755 "$OUT"/opt/nm2munin/*.py "$INSTALL_DIR"/
install -D -m 0644 "$OUT"/etc/munin/munin-conf.d/dtn.conf /etc/munin/munin-conf.d/dtn.conf
install -m 0644 "$OUT"/systemd/*.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable nm-mgr.service nm2munin.service

echo
echo "installed nm2munin manager. Start with:"
echo "  systemctl start nm-mgr nm2munin && systemctl restart munin-node"
