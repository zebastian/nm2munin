#!/bin/bash
# render.sh -- render the ION node config for one host of the two-node lab.
#
#   examples/two-node-lab/render.sh hosts/ground.env [OUTDIR]
#
# Expands the ION rc/ionconfig/unit templates for the host into build/. This is
# the sample ION setup only; the manager/bridge it feeds is the generic project
# at the repo root (see ../../README.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HOSTENV="${1:?usage: render.sh hosts/<host>.env [outdir]}"
# shellcheck disable=SC1091
source "$REPO/deploy/render-lib.sh"
# shellcheck disable=SC1090
source "$HERE/$HOSTENV"

: "${ROLE:?host env must set ROLE (manager|agent)}"
: "${NODE_NBR:?}" "${LOCAL_IP:?}" "${PEER_IP:?}" "${PEER_NODE:?}" "${AGENT_EID:?}" "${WM_SIZE:?}"

OUT="${2:-$HERE/build/${ROLE}-node${NODE_NBR}}"
rm -rf "$OUT"
mkdir -p "$OUT/etc/ion" "$OUT/usr/local/bin" "$OUT/systemd"

for t in ion.rc bp.rc ipn.rc node.ionconfig nm-agent.env; do
    render_file "$HERE/ion/$t.tmpl" "$OUT/etc/ion/$t"
done
cp "$HERE/ion/ionsec.rc" "$OUT/etc/ion/ionsec.rc"
install -m 0755 "$HERE/ion/ion-start" "$HERE/ion/ion-stop" "$OUT/usr/local/bin/"

render_file "$HERE/systemd/ion.service.tmpl"      "$OUT/systemd/ion.service"
render_file "$HERE/systemd/nm-agent.service.tmpl" "$OUT/systemd/nm-agent.service"

if [ "$ROLE" = "manager" ]; then
    : "${INSTALL_DIR:?}" "${DUMMY_TICK:?}" "${DUMMY_MAXRATE:?}"
    mkdir -p "$OUT/opt/nm2munin"
    install -m 0755 "$HERE/dummy-traffic/dummy_traffic.py" "$OUT/opt/nm2munin/"
    render_file "$HERE/systemd/dummy-traffic.service.tmpl" "$OUT/systemd/dummy-traffic.service"
fi

echo "rendered ION node $NODE_NBR ($ROLE) -> $OUT"
