#!/usr/bin/env python3
import subprocess, time, sys, os, glob
EID = sys.argv[1]
HEX = sys.argv[2]
RD = "/var/lib/nm/reports"
os.makedirs(RD, exist_ok=True)
for f in glob.glob(RD + "/**/*.log", recursive=True):
    try: os.remove(f)
    except: pass
p = subprocess.Popen(
    ["nm_mgr", "-l", "-d", "-r", "-T", "-D", RD, "-A", "ipn:1.1"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, cwd="/var/lib/ion")
def send(c):
    p.stdin.write(c + "\n"); p.stdin.flush(); time.sleep(0.6)
time.sleep(3)
send("L")
send("R " + EID)
time.sleep(1)
send("H %s 0 %s" % (EID, HEX))
time.sleep(8)
send("EXIT_SHUTDOWN")
try:
    out, _ = p.communicate(timeout=10)
except Exception:
    p.kill(); out, _ = p.communicate()
print("=== MGR TAIL ===")
print("\n".join(out.splitlines()[-40:]))
print("=== REPORT FILES ===")
for f in sorted(glob.glob(RD + "/**/*", recursive=True)):
    if os.path.isfile(f):
        print(f, os.path.getsize(f), "bytes")
