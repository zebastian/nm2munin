# Example: two-node ION lab

A complete, self-contained sample DTN network that feeds the nm2munin manager
in the repo root. It is one concrete topology — use it as a reference for wiring
your own. Nothing here is required by the generic project; the manager only
cares about the agent EIDs you give it.

## Topology

Two nodes over a bidirectional UDP convergence layer. Node 1 is the ground
station: it hosts the NM manager, the nm2munin bridge and the Munin master.
Node 2 is a remote agent.

```
  asterisk-a  (192.168.122.10)              asterisk-b  (192.168.122.197)
  node 1 / ROLE=manager                     node 2 / ROLE=agent
  ipn:1.x                                    ipn:2.x
  ┌─────────────────────────────┐  UDP CLA  ┌──────────────────────┐
  │ ion                         │ :4556     │ ion                  │
  │ nm-agent      ipn:1.2 ──────┼───────────┼─ nm-agent  ipn:2.1   │
  │ nm-mgr        ipn:1.1       │◀── AMP ───┤                      │
  │ nm2munin bridge             │  reports  └──────────────────────┘
  │   ipn:1.2 → 127.0.0.1:4950  │
  │   ipn:2.1 → 127.0.0.1:4951  │
  │ dummy-traffic               │
  │ munin master + munin-node   │
  └─────────────────────────────┘
```

The ground node's `nm-agent` (ipn:1.2) is monitored alongside the remote
(ipn:2.1), so the manager graphs both ends. `dummy-traffic` sends bundles to
unregistered endpoints so they are discarded, animating the BP counters on a
diurnal curve for demo charts.

## Files

```
hosts/common.env     shared lab settings (user, CLA port, manager EID, ...)
hosts/ground.env     node 1: IPs, EIDs, WM size + manager NM_AGENTS/BRIDGE_MAP
hosts/remote.env     node 2: agent-only
hosts/hosts.example.env   template for adding a third node
ion/*.tmpl           ion.rc / bp.rc / ipn.rc / node.ionconfig / nm-agent.env
ion/ion-start,ion-stop    ION lifecycle wrappers
systemd/*.tmpl       ion / nm-agent / dummy-traffic unit templates
dummy-traffic/       demo BP traffic generator
render.sh / install.sh    bring up one host of the lab
```

## Bring-up

On each node, as root, point install at that node's env file:

```bash
# node 2 (remote agent) — 192.168.122.197
sudo examples/two-node-lab/install.sh hosts/remote.env
systemctl start ion nm-agent

# node 1 (ground / manager) — 192.168.122.10
sudo examples/two-node-lab/install.sh hosts/ground.env
systemctl start ion nm-agent dummy-traffic
systemctl start nm-mgr nm2munin
systemctl restart munin-node
```

On the manager, `install.sh hosts/ground.env` installs the ION node + nm-agent
+ dummy-traffic, then chains into `../../deploy/install.sh` to lay down the
nm2munin bridge, nm-mgr and the Munin node map — reusing the same env file
(`ground.env` carries `NM_AGENTS` and `BRIDGE_MAP`). Use `render.sh` instead of
`install.sh` for a dry run into `build/`.

## Adding a node

Copy `hosts/hosts.example.env` to `hosts/<name>.env`, set `NODE_NBR`, the IPs
and `AGENT_EID`, then extend `NM_AGENTS` and `BRIDGE_MAP` in `hosts/ground.env`
with the new EID and a free port. Re-run the ground install to regenerate the
Munin node map. For more than two nodes you will also want to extend the contact
plan in `ion/ion.rc.tmpl`.
