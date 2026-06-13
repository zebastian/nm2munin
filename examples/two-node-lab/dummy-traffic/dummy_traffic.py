#!/usr/bin/env python3
"""Dummy BP traffic generator (node1) -- drives a semi-random diurnal curve so the
Munin DTN charts look alive.  Bundles are sent to deliberately unregistered
endpoints so they are *discarded* at the destination, bumping each node's
discarded_bundles counter (which the bridge graphs as a DERIVE rate):

    ipn:1.50  -> discarded locally on node1   (-> dtn/ipn-1.2 chart)
    ipn:2.50  -> routed to node2, discarded   (-> dtn/ipn-2.1 chart)

The per-tick bundle count follows a day curve (morning shoulder + afternoon peak)
with a slow random walk plus per-tick jitter.  node2 gets a slightly phase/scale
shifted curve so the two charts differ.
"""
import os, time, math, random, datetime, subprocess

TICK = int(os.environ.get("DUMMY_TICK", "20"))          # seconds between bursts
MAXRATE = int(os.environ.get("DUMMY_MAXRATE", "90"))    # bundles per tick at peak
DESTS = {                                               # eid -> (peak_hour, scale)
    "ipn:1.50": (14.0, 1.00),
    "ipn:2.50": (15.5, 0.70),
}


def diurnal(h, peak):
    main = math.exp(-((h - peak) ** 2) / (2 * 3.5 ** 2))
    morning = 0.55 * math.exp(-((h - (peak - 5)) ** 2) / (2 * 2.0 ** 2))
    return 0.07 + 0.93 * max(main, morning)


def blast(dest, n):
    if n <= 0:
        return
    payload = "".join("dummy %d\n" % i for i in range(n))
    p = subprocess.Popen(["bpsource", dest], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    try:
        p.stdin.write(payload); p.stdin.flush(); p.stdin.close()
        time.sleep(min(6, 1 + n * 0.03))
    finally:
        p.terminate()
        try: p.wait(2)
        except Exception: p.kill()


walk = {d: 1.0 for d in DESTS}
while True:
    now = datetime.datetime.now()
    h = now.hour + now.minute / 60.0
    for dest, (peak, scale) in DESTS.items():
        walk[dest] = min(1.3, max(0.7, walk[dest] * random.uniform(0.93, 1.07)))
        rate = diurnal(h, peak) * scale * walk[dest] * random.uniform(0.85, 1.15)
        blast(dest, max(0, int(MAXRATE * rate)))
    time.sleep(TICK)
