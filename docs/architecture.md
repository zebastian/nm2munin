# nm2munin architecture

How NM/AMP reports become time-shifted Munin graphs. This concerns the generic
manager/bridge; topology specifics live in the examples.

## Pipeline

```
 nm_agent ──AMP report──▶ nm_mgr ──log file──▶ bridge.py ──munin-node proto──▶ Munin master
 (agent)   over BP/DTN    (-D dir)  per EID      (spool)     per-EID TCP port
```

1. **`nm_mgr_run.py`** launches `nm_mgr` in automator mode
   (`-l -d -r -D <reports>`), registers each agent (`R <eid>`), and every
   `NM_INTERVAL` seconds issues `H <eid> 0 <ctrl>` controls requesting a curated
   set of **scalar** EDDs (BP traffic/errors/storage, ION rates/clock, SDR/ZCO
   ceilings). `nm_mgr` writes each received report to
   `/var/lib/nm/reports/<eid>/N.log`.

   Parameterized / map EDDs (the ADM `full_report` templates) are deliberately
   avoided — they crash `nm_agent` in this build. The control hex strings in
   `nm_mgr_run.py` encode only plain scalar EDDs.

2. **`bridge.py`** parses those logs on demand and serves each EID as a separate
   Munin node.

## Report → graph mapping

`bridge.py` parses each `AMP DATA REPORT` block, taking the report `Timestamp`
as the sample epoch and each entry as `name: value`. Single-entry reports carry
the full metric name in `Rpt Name` (the entry line is truncated at 30 chars), so
that is preferred there; multi-entry reports use the entry names.

Metric names are grouped into Munin multigraphs by the `GRAPHS` table in
`bridge.py` (e.g. `bp_traffic`, `bp_errors`, `ion_rates`, `ion_sdr_storage`,
`host_cpu/mem/disk`). Anything unmapped falls back to an `nm_other` graph.
Cumulative counters listed in `COUNTERS` are emitted as `DERIVE` (per-second
rate) so traffic shows as a curve rather than an ever-rising staircase;
everything else is a `GAUGE`.

Optional host-metric logs at `<HOST_DIR>/<eid>.hm` (lines
`<epoch> cpu=.. mem=.. disk=..`) are merged in for the `host_*` graphs.

## Time-shift via spoolfetch

The bridge advertises `cap multigraph dirtyconfig spool`. When the Munin master
issues `spoolfetch <since>`, the bridge emits every sample newer than `<since>`
as:

```
multigraph <graph>
<field>.value <epoch>:<value>
```

where `<epoch>` is the **agent-side generation time** embedded in the report,
not the time the manager received or served it. Munin's spool stores each
sample at its embedded epoch, so a report that traversed a long DTN delay — or
arrived after a manager/bridge outage — is graphed at the time it was actually
measured. A normal `fetch` (non-spool) is also supported and returns everything
from epoch 0.

## EID → port mapping

`bridge.py` takes `EID=port` pairs as argv (from `BRIDGE_MAP`), one listener per
EID on `NM2MUNIN_BIND` (default `127.0.0.1`). With no args it auto-discovers
EIDs from the reports/hostmetrics directories and assigns ports from
`NM2MUNIN_PORT_BASE`. The Munin master is wired to these ports by
`munin-conf.d/dtn.conf`, generated from `BRIDGE_MAP` at install time.

## Relevant environment

| Variable                | Default                  | Used by    |
|-------------------------|--------------------------|------------|
| `NM2MUNIN_REPORTS`      | `/var/lib/nm/reports`    | bridge     |
| `NM2MUNIN_HOSTMETRICS`  | `/var/lib/nm/hostmetrics`| bridge     |
| `NM2MUNIN_BIND`         | `127.0.0.1`              | bridge     |
| `NM2MUNIN_PORT_BASE`    | `4950`                   | bridge     |
| `NM_MGR_EID`            | `ipn:1.1`                | nm_mgr_run |
| `NM_AGENTS`             | `ipn:1.2 ipn:2.1`        | nm_mgr_run |
| `NM_INTERVAL`           | `30`                     | nm_mgr_run |
| `NM_REPORTS`            | `/var/lib/nm/reports`    | nm_mgr_run |
