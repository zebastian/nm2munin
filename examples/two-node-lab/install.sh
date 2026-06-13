#!/bin/bash
# install.sh -- bring up one host of the two-node lab on THIS machine. Run as root.
#
#   sudo examples/two-node-lab/install.sh hosts/ground.env   # node 1, manager
#   sudo examples/two-node-lab/install.sh hosts/remote.env   # node 2, agent
#
# Installs the ION node + nm-agent for every host. On the manager host it also
# installs dummy-traffic and chains into the repo-root manager install to lay
# down the nm2munin bridge + nm-mgr + Munin node map.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HOSTENV="${1:?usage: install.sh hosts/<host>.env}"
[ "$(id -u)" -eq 0 ] || { echo "install.sh must run as root" >&2; exit 1; }
# shellcheck disable=SC1090
source "$HERE/$HOSTENV"

OUT="$HERE/build/${ROLE}-node${NODE_NBR}"
"$HERE/render.sh" "$HOSTENV" "$OUT"

id "$ION_USER" >/dev/null 2>&1 || useradd --system --home /var/lib/ion --shell /usr/sbin/nologin "$ION_USER"
install -d -o "$ION_USER" -g "$ION_GROUP" /var/lib/ion

install -d /etc/ion
install -o "$ION_USER" -g "$ION_GROUP" -m 0644 "$OUT"/etc/ion/* /etc/ion/
install -m 0755 "$OUT"/usr/local/bin/ion-start "$OUT"/usr/local/bin/ion-stop /usr/local/bin/
install -m 0644 "$OUT"/systemd/ion.service "$OUT"/systemd/nm-agent.service /etc/systemd/system/

UNITS=(ion.service nm-agent.service)
if [ "$ROLE" = "manager" ]; then
    install -d -o "$ION_USER" -g "$ION_GROUP" "$INSTALL_DIR"
    install -o "$ION_USER" -g "$ION_GROUP" -m 0755 "$OUT"/opt/nm2munin/dummy_traffic.py "$INSTALL_DIR"/
    install -m 0644 "$OUT"/systemd/dummy-traffic.service /etc/systemd/system/
    UNITS+=(dummy-traffic.service)
    # The bridge + nm-mgr + Munin map come from the generic project; this host
    # env already carries MGR_EID / NM_AGENTS / BRIDGE_MAP, so reuse it.
    "$REPO/deploy/install.sh" "$HERE/$HOSTENV"
fi

systemctl daemon-reload
systemctl enable "${UNITS[@]}"

echo
echo "installed lab node $NODE_NBR ($ROLE). Units: ${UNITS[*]}"
echo "start with:  systemctl start ${UNITS[*]}"
[ "$ROLE" = "manager" ] && echo "manager bridge: systemctl start nm-mgr nm2munin && systemctl restart munin-node"
