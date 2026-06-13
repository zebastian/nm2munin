#!/usr/bin/env python3
"""
nm-mgr-run -- run the ION NM manager headless and periodically poll agents.

Owns nm_mgr's stdin/stdout (automator mode), registers the configured agents,
and every INTERVAL seconds asks each agent for a curated set of scalar EDD
reports (BP traffic/errors/storage + ION rates/clock).  nm_mgr logs every
received report to /var/lib/nm/reports/<eid>/N.log with the agent-side
generation timestamp -- which the nm2munin bridge later serves to Munin
time-shifted.

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
CONTROLS = [BP, ION, ION_SDR]


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

    time.sleep(3)
    for a in AGENTS:
        send("R " + a)
    sys.stderr.write("nm-mgr-run: polling %s every %ds\n" % (AGENTS, INTERVAL))
    sys.stderr.flush()
    try:
        while True:
            if p.poll() is not None:
                sys.stderr.write("nm-mgr-run: nm_mgr exited (%s)\n" % p.returncode)
                sys.exit(1)
            for a in AGENTS:
                for ctrl in CONTROLS:
                    send("H %s 0 %s" % (a, ctrl))
                    time.sleep(0.2)
            time.sleep(INTERVAL)
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
