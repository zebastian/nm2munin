# nm2munin

Bridge ION-DTN Network Management (NM / CCSDS AMP) reports into
[Munin](https://munin-monitoring.org/), **time-shift capable**: each metric is
graphed at the agent-side generation epoch embedded in its AMP report, not at
the time the ground station received it. Metrics that arrive late over a DTN
link — or after a manager/bridge outage — are still plotted at the moment they
were actually measured.

This project is the **manager/bridge** side: it polls a set of NM agents,
collects their reports, and serves them to a Munin master. It is independent of
any particular DTN topology — you describe your agents in one env file and the
daemons and units are generated from it. A complete worked example of an ION
network feeding this manager lives under
[`examples/two-node-lab/`](examples/two-node-lab/).

## What it does

```
   NM agents (any topology)              this project, on the manager host
   ┌───────────────┐                     ┌───────────────────────────────────┐
   │ nm_agent EID1 │── AMP reports ─────▶│ nm-mgr   (nm_mgr_run.py)          │
   │ nm_agent EID2 │   over BP/DTN       │   polls agents, logs reports to   │
   │      ...      │                     │   /var/lib/nm/reports/<eid>/      │
   └───────────────┘                     │                                   │
                                         │ nm2munin (bridge.py)              │
                                         │   one munin-node endpoint per EID │
                                         │   EID1 → 127.0.0.1:4950           │
                                         │   EID2 → 127.0.0.1:4951           │
                                         └──────────────┬────────────────────┘
                                                        │ munin-node protocol
                                                        ▼  (spool capability)
                                              Munin master (munin-conf.d/dtn.conf)
```

- **`nm-mgr`** (`nm_mgr_run.py`) runs `nm_mgr` headless, registers the
  configured agents, and every `NM_INTERVAL` seconds requests a curated set of
  scalar EDD reports. `nm_mgr` logs each report with the agent-side generation
  timestamp.
- **`nm2munin`** (`bridge.py`) presents each agent EID as its own Munin node on
  a local TCP port, speaking the munin-node protocol with the `spool`
  capability. Because samples are emitted at their embedded epoch, the Munin
  master stores them time-shifted into the past.

See [docs/architecture.md](docs/architecture.md) for the report→graph mapping
and the spoolfetch time-shift mechanism.

## Layout

```
src/nm2munin/bridge.py        the Munin spoolfetch bridge (one node per EID)
src/nm2munin/nm_mgr_run.py    headless nm_mgr + curated report poller
tools/nmdrv.py                one-shot NM driver, for debugging a single report
systemd/*.tmpl                nm-mgr / nm2munin unit templates (@VAR@ tokens)
config/manager.env.example    the one file you edit: agents + ports + EIDs
config/munin/                 munin-conf.d/dtn.conf header (node map generated)
deploy/render.sh              expand templates for your manager.env -> build/
deploy/install.sh             install + enable the units on this host
deploy/render-lib.sh          shared @TOKEN@ expander
examples/two-node-lab/        a full sample ION network feeding this manager
```

## Usage

The manager host must already run an ION node with an `nm_agent`/`nm_mgr`
stack (any topology). Then:

```bash
cp config/manager.env.example config/manager.env
$EDITOR config/manager.env          # set MGR_EID, NM_AGENTS, BRIDGE_MAP

deploy/render.sh                    # dry run -> build/manager/, touches nothing
sudo deploy/install.sh             # install daemons, units, Munin node map
systemctl start nm-mgr nm2munin
systemctl restart munin-node
```

### Configuring for your topology

Everything topology-specific is in `config/manager.env`:

| Variable      | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| `MGR_EID`     | EID of the local NM manager (`nm_mgr -A`)                       |
| `NM_AGENTS`   | space-separated agent EIDs to poll                             |
| `BRIDGE_MAP`  | `EID=port` map exposed to Munin, one free local port per agent |
| `NM_INTERVAL` | poll cadence in seconds                                        |
| `INSTALL_DIR` | where the daemons are installed (`/opt/nm2munin`)              |

Add an agent by appending its EID to `NM_AGENTS` and an `EID=port` pair to
`BRIDGE_MAP`; `munin-conf.d/dtn.conf` is regenerated from `BRIDGE_MAP` on the
next install.

## Requirements

ION-DTN installed (`nm_agent`, `nm_mgr` on `PATH`), Python 3 stdlib only, and
`munin` + `munin-node` on the manager host.
