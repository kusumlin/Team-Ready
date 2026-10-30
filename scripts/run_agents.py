"""Start all seven TeamReady agents with ONE command, the way Agentverse mailboxes work.

    python scripts/run_agents.py          # start all seven, connect mailboxes, keep running
    python scripts/run_agents.py --stop   # stop a copy started earlier (uses logs/pids)

Why not one process? In a single process (agents/main.py / Bureau) the agents share
one server, so the mailbox "Connect" call cannot reach each agent and only some agents
get a mailbox. This script runs each agent as its own process (like run_all.sh), but:
  - works on Mac, Linux and Windows,
  - starts the agents a few seconds apart,
  - checks every agent's log for "Agentverse mailbox connected" and, if one is missing,
    makes the same Connect -> Mailbox call the Agent Inspector button makes,
  - prints a status table, and stops all seven on Ctrl+C.

Only ONE copy may run anywhere (laptop or server): two copies with the same seeds fight.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PIDS = LOGS / "pids"
AGENTS = [  # (name, file, port) - same order as run_all.sh
    ("knowledge", "knowledge_agent", 8101),
    ("routing", "routing_agent", 8102),
    ("manager", "manager_agent", 8103),
    ("insights", "insights_agent", 8104),
    ("tracker", "tracker_agent", 8105),
    ("canary", "canary_agent", 8106),
    ("orchestrator", "orchestrator", 8100),
]
STAGGER_SECONDS = 3
CONNECT_WAIT_SECONDS = 25
OK_TEXT = "Agentverse mailbox connected"


def load_env() -> dict:
    """Read .env without printing anything from it."""
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def port_busy(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def stop() -> None:
    if not PIDS.exists():
        print("Nothing to stop (no logs/pids).")
        return
    for line in PIDS.read_text().split():
        try:
            pid = int(line)
        except ValueError:
            continue
        if alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    time.sleep(2)
    left = [int(p) for p in PIDS.read_text().split() if p.isdigit() and alive(int(p))]
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
        except OSError:
            pass
    PIDS.unlink(missing_ok=True)
    print("Stopped all agents.")


def connect_mailbox(port: int, key: str) -> str:
    body = json.dumps({"user_token": key, "agent_type": "mailbox"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/connect", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return type(e).__name__
    return "ok" if isinstance(data, dict) and data.get("success") else str(data)[:80]


def main() -> int:
    if "--stop" in sys.argv:
        stop()
        return 0

    env = load_env()
    key = os.environ.get("AGENTVERSE_API_KEY") or env.get("AGENTVERSE_API_KEY", "")
    if not key:
        print("WARNING: AGENTVERSE_API_KEY is empty in .env - agents will run locally only, "
              "not on Agentverse/ASI:One.")
    missing = [n for n, _, _ in AGENTS if not env.get(f"{n.upper()}_SEED")]
    if missing:
        print(f"WARNING: no seed in .env for {', '.join(missing)} - they will use demo seeds "
              "and get DIFFERENT addresses.")

    busy = [p for _, _, p in AGENTS if port_busy(p)]
    if busy:
        print(f"Ports already in use: {busy}. Another copy is running. Stop it first "
              "(python scripts/run_agents.py --stop, or kill $(cat logs/pids)).")
        return 1

    LOGS.mkdir(exist_ok=True)
    procs = []
    for name, file, port in AGENTS:
        log = open(LOGS / f"{file}.log", "w")  # noqa: SIM115 - stays open for the agent's lifetime
        p = subprocess.Popen([sys.executable, str(ROOT / "agents" / f"{file}.py")],
                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        procs.append((name, file, port, p))
        print(f"started teamready-{name:13s} pid {p.pid}  port {port}")
        time.sleep(STAGGER_SECONDS)
    PIDS.write_text("\n".join(str(p.pid) for *_, p in procs) + "\n")

    status = {}
    if key:
        print(f"\nWaiting up to {CONNECT_WAIT_SECONDS}s for mailboxes...")
        deadline = time.time() + CONNECT_WAIT_SECONDS
        while time.time() < deadline:
            done = all(OK_TEXT in (LOGS / f"{f}.log").read_text(errors="ignore") for _, f, _, _ in procs)
            if done:
                break
            time.sleep(2)
        for name, file, port, p in procs:
            if p.poll() is not None:
                status[name] = f"CRASHED (exit {p.returncode}) - see logs/{file}.log"
            elif OK_TEXT in (LOGS / f"{file}.log").read_text(errors="ignore"):
                status[name] = "mailbox connected"
            else:
                r = connect_mailbox(port, key)  # same call as Agent Inspector -> Connect -> Mailbox
                status[name] = "mailbox connected (retry)" if r == "ok" else f"NOT connected: {r}"
    else:
        for name, file, port, p in procs:
            status[name] = "running locally" if p.poll() is None else f"CRASHED - see logs/{file}.log"

    print("\nAgent                Status")
    for name, *_ in procs:
        print(f"teamready-{name:13s} {status[name]}")
    if any(s.startswith(("NOT", "CRASHED")) for s in status.values()):
        print("\nSome agents are not connected. Open that agent's 'Agent inspector' link in its "
              "log, sign in to Agentverse, click Connect -> Mailbox.")
    print("\nRunning. Leave this window open. Press Ctrl+C to stop all seven.")

    try:
        while True:
            time.sleep(5)
            for name, file, _, p in procs:
                if p.poll() is not None and not status[name].startswith("CRASHED"):
                    status[name] = "CRASHED"
                    print(f"!! teamready-{name} stopped (exit {p.returncode}) - see logs/{file}.log")
    except KeyboardInterrupt:
        print("\nStopping...")
        for *_, p in procs:
            p.terminate()
        for *_, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        PIDS.unlink(missing_ok=True)
        print("All seven stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
