#!/bin/bash
# render.sh -- render the nm2munin manager/bridge config for one deployment.
#
#   deploy/render.sh [manager.env] [OUTDIR]
#
# Sources the given env file (default: config/manager.env), expands the unit
# templates, generates the Munin node map from BRIDGE_MAP, and stages the
# daemons. Output mirrors the install layout:
#
#   <out>/opt/nm2munin/{bridge.py,nm_mgr_run.py}
#   <out>/systemd/{nm-mgr.service,nm2munin.service}
#   <out>/etc/munin/munin-conf.d/dtn.conf
#
# This covers ONLY the manager/bridge. The host is assumed to already run an
# ION node + nm-agent (see examples/two-node-lab for one way to provide that).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="${1:-$ROOT/config/manager.env}"
[ -f "$ENVFILE" ] || { echo "no env file: $ENVFILE (copy config/manager.env.example)" >&2; exit 1; }
# shellcheck disable=SC1091
source "$ROOT/deploy/render-lib.sh"
# shellcheck disable=SC1090
source "$ENVFILE"

: "${MGR_EID:?}" "${NM_AGENTS:?}" "${BRIDGE_MAP:?}" "${INSTALL_DIR:?}"
: "${ION_USER:?}" "${ION_GROUP:?}" "${NM_INTERVAL:?}"
: "${NM2MUNIN_BIND:=127.0.0.1}"
export NM2MUNIN_BIND

OUT="${2:-$ROOT/build/manager}"
rm -rf "$OUT"
mkdir -p "$OUT/opt/nm2munin" "$OUT/systemd" "$OUT/etc/munin/munin-conf.d"

install -m 0755 "$ROOT"/src/nm2munin/*.py "$OUT/opt/nm2munin/"
render_file "$ROOT/systemd/nm-mgr.service.tmpl"   "$OUT/systemd/nm-mgr.service"
render_file "$ROOT/systemd/nm2munin.service.tmpl" "$OUT/systemd/nm2munin.service"

# Munin master node map: one [dtn;<node>] block per EID=port pair in BRIDGE_MAP.
dtn="$OUT/etc/munin/munin-conf.d/dtn.conf"
cp "$ROOT/config/munin/munin-conf.d/dtn.conf.header" "$dtn"
for pair in $BRIDGE_MAP; do
    eid="${pair%%=*}"; port="${pair##*=}"
    {
        echo "[dtn;${eid/:/-}]"          # ipn:1.2 -> dtn;ipn-1.2
        echo "    address ${NM2MUNIN_BIND}"
        echo "    port ${port}"
        echo "    use_node_name no"
    } >> "$dtn"
done

echo "rendered manager (MGR_EID=$MGR_EID, agents: $NM_AGENTS) -> $OUT"
