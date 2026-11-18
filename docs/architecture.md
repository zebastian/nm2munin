# nm2munin architecture

How NM/AMP reports become time-shifted Munin graphs. This concerns the generic
manager/bridge; topology specifics live in the examples.

## Pipeline

```
 nm_agent ──AMP report──▶ nm_mgr ──log file──▶ bridge.py ──munin-node proto──▶ Munin master
 (agent)   over BP/DTN    (-D dir)  per EID      (spool)     per-EID TCP port
```

1. **`nm_mgr_run.py`** launches `nm_mgr` in automator mode
   (`-l -d -r -D <reports>`), registers each agent (`R <eid>`), and sends it
   (`H <eid> 0 <ctrl>`) an `add_tbr` control: a time-based rule `nm2munin` that
   runs `gen_rpts` controls for a curated set of **scalar** EDDs (BP
   traffic/errors/storage, ION rates/clock, SDR/ZCO ceilings) every
   `NM_INTERVAL` seconds, without end. The agent runs the rule on its own clock
   and sends the reports to its manager, so it keeps measuring while its link
   is down; the reports wait in its bundle queue and arrive, with the time they
   were generated, once the link is back. The rule is sent again every
   `NM_TBR_REFRESH` seconds, for an agent that restarted and lost it; an agent
   that has it ignores the copy, and keeps its period. `nm_mgr` writes each
   received report to `/var/lib/nm/reports/<eid>/N.log`.

   With `NM_REPORTING=poll` the manager sends the `gen_rpts` controls itself
   every `NM_INTERVAL` seconds instead; an agent then reports only while they
   reach it. Over a disrupted link that is also a hazard: the controls queue
   while the link is down and arrive together after, and ION's NM (4.2.0, and
   the integration branch as of 2026-11-17) ends `nm_agent` when more than 100
   reports are due in one second (its vectors hold at most `VEC_MAX_IDX` = 100
   entries). Two queued rounds of this manager's 59 reports are enough.

   One rule firing sends all its reports to the manager in one message, which
   is larger than 1 KiB. ION's NM (4.2.0, and the integration branch as of
   2026-11-17) cannot encode a message larger than 1 KiB, and the failure ends
   `nm_agent`; the agent needs the fix in `cut_serialize_wrapper`
   (nm/shared/utils/cbor_utils.c) that sizes an item without the caller's
   1024-byte estimate as its limit.

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

Munin takes `<since>` from the newest sample it has stored, not from the clock,
so reports that arrive late with older epochs than the time of its last fetch
are still fetched, as long as they are newer than that sample.

Munin keeps one value per 5 minutes unless a graph says otherwise, which would
merge the samples of a short outage into one. With `NM2MUNIN_UPDATE_RATE` set
(the units set it to `NM_INTERVAL`), every graph's config carries
`update_rate <NM_INTERVAL>` and `graph_data_size custom 1d, 5m for 1w, 1h for
1y` (`NM2MUNIN_GRAPH_DATA_SIZE`): full resolution for a day. The RRD heartbeat
is twice the update rate, so where no samples came, the graph shows a gap.
Munin applies both to the RRD files it creates; existing ones keep their step.

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
| `NM2MUNIN_UPDATE_RATE`  | unset (Munin's 300 s)    | bridge     |
| `NM2MUNIN_GRAPH_DATA_SIZE` | `custom 1d, 5m for 1w, 1h for 1y` | bridge |
| `NM_INTERVAL`           | `30`                     | nm_mgr_run |
| `NM_REPORTING`          | `tbr`                    | nm_mgr_run |
| `NM_TBR_REFRESH`        | `300`                    | nm_mgr_run |
| `NM_REPORTS`            | `/var/lib/nm/reports`    | nm_mgr_run |
