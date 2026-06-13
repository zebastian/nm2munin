#!/usr/bin/env python3
"""
nm2munin bridge -- expose ION-DTN NM (AMP) reports to Munin, time-shift capable.

Each managed agent EID is presented as its own Munin node, served on a dedicated
TCP port via the munin-node protocol with the "spool" capability.  Reports are
emitted as multigraph data lines of the form

        <field>.value <epoch>:<value>

where <epoch> is the AMP report's *generation* timestamp at the agent (rpt->time),
NOT the time the ground station received or graphed it.  Because the Munin master's
spoolfetch path stores each sample at its embedded epoch, metrics that arrive late
over the DTN link (or after a manager/bridge outage) are still graphed at the time
they were actually measured -- i.e. time-shifted into the past.

Data sources (per EID):
  * nm_mgr report logs:   <REPORTS_DIR>/<eid>/*.log   (AMP DATA REPORT blocks)
  * host-metric logs:     <HOST_DIR>/<eid>.hm         (CPU/RAM/DISK shipped over BP)

Pure Python 3 standard library; no third-party deps.
"""

import os
import re
import sys
import time
import glob
import socket
import threading

REPORTS_DIR = os.environ.get("NM2MUNIN_REPORTS", "/var/lib/nm/reports")
HOST_DIR = os.environ.get("NM2MUNIN_HOSTMETRICS", "/var/lib/nm/hostmetrics")
PORT_BASE = int(os.environ.get("NM2MUNIN_PORT_BASE", "4950"))
BIND_ADDR = os.environ.get("NM2MUNIN_BIND", "127.0.0.1")

# ---------------------------------------------------------------------------
# Metric -> graph grouping.  AMP gen_rpts of individual EDDs yields one small
# report per metric, so we group metrics into Munin graphs explicitly here.
# Anything not listed falls back to a per-ADM "other" graph by name prefix.
# ---------------------------------------------------------------------------
GRAPHS = {
    "bp_traffic": {
        "title": "BP bundles (pending / custody)",
        "vlabel": "bundles",
        "category": "dtn",
        "fields": ["num_pend_fwd", "num_pend_dis", "num_in_cust",
                   "num_pend_reassembly"],
    },
    "bp_errors": {
        "title": "BP discarded / failed / abandoned bundles",
        "vlabel": "bundles",
        "category": "dtn",
        "fields": ["num_bundles_deleted", "failed_custody_bundles",
                   "failed_forward_bundles", "abandoned_bundles",
                   "discarded_bundles", "num_fragmented_bundles",
                   "num_fragments_produced"],
    },
    "bp_storage": {
        "title": "BP registrations",
        "vlabel": "count",
        "category": "dtn",
        "fields": ["num_registrations"],
    },
    "ion_sdr_storage": {
        "title": "ION ZCO storage (available residual + filesystem ceilings)",
        "vlabel": "bytes",
        "category": "ion_sdr",
        "fields": ["available_storage",
                   "inbound_file_system_occupancy_limit",
                   "outbound_file_system_occupancy_limit"],
    },
    "ion_sdr_heap": {
        "title": "ION ZCO heap occupancy ceilings (SDR working memory)",
        "vlabel": "bytes",
        "category": "ion_sdr",
        "fields": ["inbound_heap_occupancy_limit",
                   "outbound_heap_occupancy_limit"],
    },
    "ion_sdr_congestion": {
        "title": "ION congestion forecast horizon",
        "vlabel": "epoch (0 = none)",
        "category": "ion_sdr",
        "fields": ["congestion_end_time_forecasts"],
    },
    "ion_rates": {
        "title": "ION production / consumption rate",
        "vlabel": "bytes/s",
        "category": "dtn",
        "fields": ["production_rate", "consumption_rate"],
    },
    "ion_clock": {
        "title": "ION clock error",
        "vlabel": "seconds",
        "category": "dtn",
        "fields": ["clock_error", "time_delta"],
    },
    "amp_agent": {
        "title": "AMP agent autonomy engine",
        "vlabel": "count",
        "category": "dtn",
        "fields": ["num_tbr", "run_tbr", "num_sbr", "run_sbr",
                   "num_controls", "run_controls", "num_macros",
                   "run_macros", "sent_reports", "num_rpt_tpls"],
    },
    "host_cpu": {
        "title": "Host CPU load",
        "vlabel": "%",
        "category": "system",
        "fields": ["cpu"],
        "args": "--upper-limit 100 -l 0",
    },
    "host_mem": {
        "title": "Host memory used",
        "vlabel": "%",
        "category": "system",
        "fields": ["mem"],
        "args": "--upper-limit 100 -l 0",
    },
    "host_disk": {
        "title": "Host disk used (root fs)",
        "vlabel": "%",
        "category": "system",
        "fields": ["disk"],
        "args": "--upper-limit 100 -l 0",
    },
}

# reverse map metric-name -> graph-name
_METRIC2GRAPH = {}
for _g, _spec in GRAPHS.items():
    for _f in _spec["fields"]:
        _METRIC2GRAPH[_f] = _g

# Cumulative counters -> graph as a per-second rate (DERIVE) so traffic shows as
# a curve rather than an ever-rising staircase.  Everything else is a level (GAUGE).
COUNTERS = {
    "discarded_bundles", "abandoned_bundles", "failed_custody_bundles",
    "failed_forward_bundles", "num_bundles_deleted", "num_fragmented_bundles",
    "num_fragments_produced", "sent_reports", "run_controls", "run_tbr",
    "run_sbr", "run_macros",
}


def field_type(metric):
    return "DERIVE" if metric in COUNTERS else "GAUGE"


def emit_field_decl(lines, metric):
    lines.append("%s.label %s" % (metric, metric))
    lines.append("%s.type %s" % (metric, field_type(metric)))
    if field_type(metric) == "DERIVE":
        lines.append("%s.min 0" % metric)


def sanitise(name):
    """Munin field/graph names: [A-Za-z_][A-Za-z0-9_]*"""
    s = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if s and s[0].isdigit():
        s = "_" + s
    return s


_TS_RE = re.compile(r"^Timestamp\s*:\s*(.+?)\s*$")
_NAME_RE = re.compile(r"^Rpt Name\s*:\s*(.+?)\s*$")
_ENTRY_RE = re.compile(r"^([A-Za-z0-9_][\w .()/-]*?)\s*:\s*(.+?)\s*$")


def parse_ctime(s):
    """'Fri Jun 12 10:17:49 2026' (agent local time) -> epoch int, or None."""
    for fmt in ("%a %b %d %H:%M:%S %Y", "%a %b  %d %H:%M:%S %Y"):
        try:
            return int(time.mktime(time.strptime(s.strip(), fmt)))
        except ValueError:
            continue
    return None


def parse_report_log(path, out):
    """Parse an nm_mgr AMP report log; append samples to out[metric] = [(epoch,val)]."""
    try:
        with open(path, "r", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    i, n = 0, len(lines)
    while i < n:
        if "AMP DATA REPORT" not in lines[i]:
            i += 1
            continue
        # within a report block
        epoch = None
        rpt_name = None
        entries = []
        i += 1
        while i < n and "AMP DATA REPORT" not in lines[i]:
            line = lines[i]
            if line.startswith("TX:"):
                i += 1
                continue
            m = _TS_RE.match(line)
            if m:
                epoch = parse_ctime(m.group(1))
                i += 1
                continue
            m = _NAME_RE.match(line)
            if m:
                rpt_name = m.group(1).strip()
                i += 1
                continue
            if line.startswith(("Sent to", "# Entries")):
                i += 1
                continue
            m = _ENTRY_RE.match(line)
            if m:
                entries.append((m.group(1).strip(), m.group(2).strip()))
            i += 1
        # commit the block.  Single-entry reports carry the full metric name in
        # "Rpt Name" while the entry line is truncated at 30 chars, so prefer
        # Rpt Name there; multi-entry reports (e.g. full_report) use entry names.
        if epoch is None:
            continue
        for ename, val in entries:
            key = rpt_name if (len(entries) == 1 and rpt_name) else ename
            try:
                fval = float(val)
            except ValueError:
                continue
            out.setdefault(sanitise(key), []).append((epoch, fval))


def parse_host_log(path, out):
    """Host-metric log lines: '<epoch> cpu=<f> mem=<f> disk=<f>'."""
    try:
        with open(path, "r", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        try:
            epoch = int(parts[0])
        except ValueError:
            continue
        for kv in parts[1:]:
            if "=" not in kv:
                continue
            k, _, v = kv.partition("=")
            try:
                out.setdefault(sanitise(k), []).append((epoch, float(v)))
            except ValueError:
                pass


def collect(eid):
    """Return {metric: sorted [(epoch,value)]} for one EID."""
    out = {}
    for f in glob.glob(os.path.join(REPORTS_DIR, eid, "*.log")):
        parse_report_log(f, out)
    hm = os.path.join(HOST_DIR, eid + ".hm")
    if os.path.exists(hm):
        parse_host_log(hm, out)
    for m in out:
        out[m].sort()
    return out


def graph_for(metric):
    if metric in _METRIC2GRAPH:
        return _METRIC2GRAPH[metric]
    return "nm_other"


def build_spool(eid, since):
    """Return spoolfetch text: multigraph blocks with timestamped values > since."""
    data = collect(eid)
    # group metrics into graphs
    graphs = {}
    maxts = since
    for metric, samples in data.items():
        new = [(e, v) for (e, v) in samples if e > since]
        if not new:
            continue
        g = graph_for(metric)
        graphs.setdefault(g, {})[metric] = new
        maxts = max(maxts, new[-1][0])
    lines = []
    for g, fields in graphs.items():
        spec = GRAPHS.get(g, {"title": g, "vlabel": "value",
                              "category": "dtn", "fields": list(fields)})
        lines.append("multigraph %s" % sanitise(g))
        lines.append("graph_title %s" % spec["title"])
        lines.append("graph_category %s" % spec.get("category", "dtn"))
        lines.append("graph_vlabel %s" % spec.get("vlabel", "value"))
        if spec.get("args"):
            lines.append("graph_args %s" % spec["args"])
        for metric in fields:
            emit_field_decl(lines, metric)
        for metric, samples in fields.items():
            for (e, v) in samples:
                # integers print without trailing .0
                vs = ("%d" % v) if float(v).is_integer() else ("%g" % v)
                lines.append("%s.value %d:%s" % (metric, e, vs))
    return "\n".join(lines), maxts


def build_config(eid):
    """Return config text (multigraph) for known graphs that have data."""
    data = collect(eid)
    present = set(data.keys())
    lines = []
    for g, spec in GRAPHS.items():
        flds = [f for f in spec["fields"] if f in present]
        if not flds:
            continue
        lines.append("multigraph %s" % sanitise(g))
        lines.append("graph_title %s" % spec["title"])
        lines.append("graph_category %s" % spec.get("category", "dtn"))
        lines.append("graph_vlabel %s" % spec.get("vlabel", "value"))
        if spec.get("args"):
            lines.append("graph_args %s" % spec["args"])
        for f in flds:
            emit_field_decl(lines, f)
    return "\n".join(lines)


class Handler(threading.Thread):
    def __init__(self, conn, eid):
        super().__init__(daemon=True)
        self.conn = conn
        self.eid = eid

    def send(self, s):
        self.conn.sendall(s.encode())

    def run(self):
        try:
            f = self.conn.makefile("rwb", buffering=0)
            self.send("# munin node at %s\n" % self.eid)
            for raw in f:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                cmd, _, arg = line.partition(" ")
                cmd = cmd.lower()
                if cmd == "cap":
                    self.send("cap multigraph dirtyconfig spool\n")
                elif cmd == "list":
                    # one logical plugin; real graphs come via multigraph
                    self.send("nm\n")
                elif cmd == "nodes":
                    self.send("%s\n.\n" % self.eid)
                elif cmd == "version":
                    self.send("munins node on %s version: nm2munin 1.0\n" % self.eid)
                elif cmd == "config":
                    self.send(build_config(self.eid) + "\n.\n")
                elif cmd == "fetch":
                    txt, _ = build_spool(self.eid, 0)
                    self.send(txt + "\n.\n")
                elif cmd == "spoolfetch":
                    try:
                        since = int(arg.strip())
                    except ValueError:
                        since = 0
                    txt, _ = build_spool(self.eid, since)
                    self.send((txt + "\n" if txt else "") + ".\n")
                elif cmd == "quit" or cmd == ".":
                    break
                else:
                    self.send("# Unknown command. Try cap/list/config/fetch/"
                              "spoolfetch/nodes/version/quit\n")
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.conn.close()
            except OSError:
                pass


def serve_eid(eid, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((BIND_ADDR, port))
    s.listen(8)
    sys.stderr.write("nm2munin: serving %s on %s:%d\n" % (eid, BIND_ADDR, port))
    sys.stderr.flush()
    while True:
        conn, _ = s.accept()
        Handler(conn, eid).start()


def discover_eids():
    eids = set()
    if os.path.isdir(REPORTS_DIR):
        for d in os.listdir(REPORTS_DIR):
            if os.path.isdir(os.path.join(REPORTS_DIR, d)) and ":" in d:
                eids.add(d)
    if os.path.isdir(HOST_DIR):
        for fn in os.listdir(HOST_DIR):
            if fn.endswith(".hm"):
                eids.add(fn[:-3])
    return sorted(eids)


def main():
    # Explicit EID:port pairs as args, else discover and assign from PORT_BASE.
    mapping = {}
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            eid, _, p = a.partition("=")
            mapping[eid] = int(p)
    else:
        for i, eid in enumerate(discover_eids()):
            mapping[eid] = PORT_BASE + i
    if not mapping:
        sys.stderr.write("nm2munin: no EIDs found under %s; pass EID=PORT args\n"
                         % REPORTS_DIR)
        sys.exit(1)
    threads = []
    for eid, port in mapping.items():
        t = threading.Thread(target=serve_eid, args=(eid, port), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
