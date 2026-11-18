#!/usr/bin/env python3
"""
nm-mgr-run -- run the ION NM manager headless and have agents report to it.

Owns nm_mgr's stdin/stdout (automator mode), registers the configured agents,
and gets a curated set of scalar EDD reports (BP traffic/errors/storage + ION
rates/clock) from each agent every INTERVAL seconds.  nm_mgr logs every
received report to /var/lib/nm/reports/<eid>/N.log with the agent-side
generation timestamp -- which the nm2munin bridge later serves to Munin
time-shifted.

How the agents report is set by NM_REPORTING:

  tbr   (default) install a time-based rule (TBR) on each agent that runs the
        report controls every INTERVAL seconds on the agent's own clock.  The
        agent keeps measuring while its link is down; the reports wait in its
        bundle queue and reach the manager, stamped with their generation
        time, once the link is back.  The rule is sent again every
        TBR_REFRESH seconds so that an agent that restarted gets it back; an
        agent that still has it ignores the duplicate.  A rule an agent
        already holds keeps its period: changing INTERVAL needs an agent
        restart.
  poll  send the report controls every INTERVAL seconds.  An agent reports
        only while the manager's controls reach it, so nothing is measured
        while the link is down.

We deliberately avoid the ADM "full_report" templates: those include
parameterized / map EDDs that crash nm_agent in this build.  Only plain
scalar EDDs are requested.
"""
import os
import sys
import time
import subprocess

MGR_EID = os.environ.get("NM_MGR_EID", "ipn:1.1")
AGENTS = os.environ.get("NM_AGENTS", "ipn:1.2 ipn:2.1").split()
INTERVAL = int(os.environ.get("NM_INTERVAL", "30"))
REPORTING = os.environ.get("NM_REPORTING", "tbr")
TBR_REFRESH = int(os.environ.get("NM_TBR_REFRESH", "300"))
REPORTS = os.environ.get("NM_REPORTS", "/var/lib/nm/reports")
ROTATE = os.environ.get("NM_ROTATE", "5000")

# Curated gen_rpts controls (scalar EDDs only) -- see project memory for encoding.
# BP scalars: pend_fwd,pend_dis,in_cust,pend_reasm,frag_bundles,frags_produced,
#             deleted,failed_custody,failed_fwd,abandoned,discarded,avail_storage,registrations
BP = ("c1154105050225238d82182a410582182a410682182a410782182a410882182a410d"
      "82182a410e82182a411082182a411182182a411382182a411582182a411782182a41"
      "0282182a410400")
# ION ionadmin: clock_error,clock_sync,consumption_rate,production_rate,time_delta
ION = "c1154105050225238582188e410082188e410182188e410482188e410a82188e410c00"
# ION SDR / ZCO storage: in/out fs+heap occupancy limits, congestion alarm+forecast
ION_SDR = ("c1154105050225238682188e410582188e410682188e410882188e4109"
           "82188e410282188e410300")
# ION memory pools (DTN/ion EDDs 0x0e-0x13): working_memory + heap total/free/used.
# Needs nm_agent/nm_mgr built with the DTN/ion memory EDDs.
ION_MEM = ("c1154105050225238682188e410e82188e410f82188e411082188e4111"
           "82188e411282188e411300")
# Host OS resources -- DTN/sys ADM (nickname 0xde), all 17 EDDs 0x00-0x10:
# num_cpus, load 1/5/15min, cpu_util_pct, mem/swap/disk total/free/used,
# open/max files, num_procs, uptime_sec. Needs nm_agent/nm_mgr with DTN/sys.
SYS = ("c115410505022523918218de41008218de41018218de41028218de4103"
       "8218de41048218de41058218de41068218de41078218de41088218de4109"
       "8218de410a8218de410b8218de410c8218de410d8218de410e8218de410f"
       "8218de411000")
# BP bundle-flow lifetime totals -- DTN/bp_agent EDDs 0x1d-0x28, each as a
# bundle count + byte count: sourced, forwarded, transmitted, received,
# delivered, expired. Needs nm_agent/nm_mgr built with these EDDs.
# NB: EDD ids >= 24 are CBOR-encoded as two bytes (0x18 id) inside a 2-byte
# bstr -> ARI "82182a4218<id>" (not "82182a41<id>", which only holds ids < 24).
BP_FLOW = ("c1154105050225238c82182a42181d82182a42181e82182a42181f82182a421820"
           "82182a42182182182a42182282182a42182382182a42182482182a42182582182a421826"
           "82182a42182782182a42182800")
CONTROLS = [BP, ION, ION_SDR, ION_MEM, SYS, BP_FLOW]


# ---------------------------------------------------------------------------
# AMP encoding of the agent's add_tbr control, as ION's NM (AMP v8) writes it.
# An ARI is a flags byte (0x80 nickname, 0x40 parameters, low nibble its kind),
# the nickname as a CBOR uint (ADM enum * 20 + the kind's ADM index), the name
# as a CBOR byte string, then its parameters as a typed value collection: the
# byte 0x05, the number of values as a CBOR uint, one type byte per value and
# the values.  An ARI collection (AC) is a CBOR array header followed by the
# ARIs themselves.
# ---------------------------------------------------------------------------
def _cbor_head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    for size, extra in ((1, 24), (2, 25), (4, 26), (8, 27)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | extra]) + n.to_bytes(size, "big")
    raise ValueError(n)


def _uint(n):
    return _cbor_head(0, n)


def _bstr(b):
    return _cbor_head(2, len(b)) + b


def _tstr(s):
    b = s.encode()
    return _cbor_head(3, len(b)) + b


# amp_agent ADM (enum 1): its controls are nickname 21, its rules 28.
_AGENT_CTRL_NN = 1 * 20 + 1
_AGENT_TBR_NN = 1 * 20 + 8
_ADD_TBR = 0x0A
# AMP types of add_tbr's parameters: id ARI, start TV, period TV, count UVAST,
# action AC, description STR.
_ADD_TBR_TYPES = bytes([0x24, 0x20, 0x20, 0x16, 0x25, 0x12])
TBR_NAME = b"nm2munin"


def add_tbr(period, controls, name=TBR_NAME):
    """Hex of the control that installs TBR <name> on an agent: from now on,
    every <period> seconds and without end, run <controls> (hex ARIs).  Their
    reports go to the agent's own manager, as no one calls a rule's controls."""
    rule_id = bytes([0x80 | 0x0B]) + _uint(_AGENT_TBR_NN) + _bstr(name)
    action = _cbor_head(4, len(controls)) + b"".join(bytes.fromhex(c) for c in controls)
    parms = (bytes([0x05]) + _uint(len(_ADD_TBR_TYPES)) + _ADD_TBR_TYPES
             + rule_id + _uint(0) + _uint(period) + _uint(0) + action
             + _tstr("nm2munin reports every %d s" % period))
    ari = bytes([0x80 | 0x40 | 0x01]) + _uint(_AGENT_CTRL_NN) + _bstr(bytes([_ADD_TBR])) + parms
    return ari.hex()


def main():
    os.makedirs(REPORTS, exist_ok=True)
    errf = open("/var/lib/nm/mgr.err", "a")
    p = subprocess.Popen(
        ["nm_mgr", "-l", "-d", "-r", "-L", ROTATE, "-D", REPORTS, "-A", MGR_EID],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=errf, text=True, bufsize=1, cwd="/var/lib/ion")

    def send(c):
        p.stdin.write(c + "\n")
        p.stdin.flush()

    if REPORTING == "tbr":
        controls, every = [add_tbr(INTERVAL, CONTROLS)], TBR_REFRESH
        what = "reports every %ds by rule, sent every %ds" % (INTERVAL, every)
    elif REPORTING == "poll":
        controls, every = CONTROLS, INTERVAL
        what = "polling every %ds" % INTERVAL
    else:
        sys.stderr.write("nm-mgr-run: NM_REPORTING is tbr or poll, not %r\n" % REPORTING)
        sys.exit(2)

    time.sleep(3)
    for a in AGENTS:
        send("R " + a)
    sys.stderr.write("nm-mgr-run: %s: %s\n" % (" ".join(AGENTS), what))
    sys.stderr.flush()
    try:
        due = 0
        while True:
            if p.poll() is not None:
                sys.stderr.write("nm-mgr-run: nm_mgr exited (%s)\n" % p.returncode)
                sys.exit(1)
            if time.monotonic() >= due:
                due = time.monotonic() + every
                for a in AGENTS:
                    for ctrl in controls:
                        send("H %s 0 %s" % (a, ctrl))
                        time.sleep(0.2)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        # nm_mgr died underneath us -> fail so systemd restarts the unit.
        sys.stderr.write("nm-mgr-run: nm_mgr pipe broke (subprocess died); exiting non-zero\n")
        try:
            p.kill()
        except Exception:
            pass
        sys.exit(1)
    finally:
        try:
            send("EXIT_SHUTDOWN")
            p.wait(timeout=5)
        except Exception:
            p.kill()


if __name__ == "__main__":
    main()
