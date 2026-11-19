import json
import sys
import threading
import time

import quota
import run

STOP = run.STOP
GAP = 300


def account(reels: int, sessions: int | None, tool: str, profile: str, everyone: list[str]) -> None:
    n = 0
    while not STOP.exists() and (sessions is None or n < sessions):
        if run.halted["why"] == "Ctrl-C":
            return
        [folder] = run.session(reels, [(tool, profile)], together_with=everyone)
        n += 1
        meta = json.loads((folder / "run.json").read_text())
        print(f"=== {tool} session {n} over: {folder.name}, {meta['reels_done']} Reels", flush=True)
        if tool in ("kimi", "grok"):
            print(f"=== {tool} plan: {quota.check(tool)}", flush=True)
        if not meta["reels_done"]:
            print(f"=== {tool}: no Reels at all, so this account stops", flush=True)
            return
        if (meta["stopped_by"] or "").startswith("Unwanted"):
            print(f"=== {tool}: reposted without being asked, so this account stops", flush=True)
            return
        if sessions is not None and n >= sessions:
            return
        pause(GAP)


def pause(seconds: int) -> None:
    ends = time.time() + seconds
    while time.time() < ends and not STOP.exists() and run.halted["why"] != "Ctrl-C":
        time.sleep(5)


if __name__ == "__main__":
    args = sys.argv[1:]
    reels = int(args.pop(0))
    sessions = int(args.pop(0)) if args[0].isdigit() else None
    seats = [tuple(seat.split("=", 1)) for seat in args]
    everyone = [tool for tool, _ in seats]
    threads = [threading.Thread(target=account, args=(reels, sessions, tool, profile, everyone), name=tool) for tool, profile in seats]
    for t in threads:
        t.start()
    run.wait_for(threads)
