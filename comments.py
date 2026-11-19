import json
import time
from pathlib import Path

import hands

FOLDER = Path(__file__).parent / "data" / "comments"
HOUR, DAY = 15, 60
TRIES = 2


def ledger(account: str) -> Path:
    return FOLDER / f"{account}.jsonl"


def attempts(account: str) -> list[dict]:
    path = ledger(account)
    return [json.loads(line) for line in path.read_text().split("\n")[:-1]] if path.exists() else []


def record(account: str, **row) -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    with ledger(account).open("a") as f:
        f.write(json.dumps({"at": time.time(), **row}, ensure_ascii=False) + "\n")


def room(account: str, probing: bool = False) -> bool:
    rows = attempts(account)
    tried = [r for r in rows if r["status"] in ("posted", "blocked")]
    if tried and tried[-1]["status"] == "blocked" and not probing:
        return False
    posted = [r["at"] for r in rows if r["status"] == "posted"]
    now = time.time()
    return sum(t > now - 3600 for t in posted) < HOUR and sum(t > now - 86400 for t in posted) < DAY


def waiting(account: str) -> list[dict]:
    latest, failures = {}, {}
    for r in attempts(account):
        latest[r["url"]] = r
        failures[r["url"]] = failures.get(r["url"], 0) + (r["status"] == "failed")
    return [r for r in latest.values()
            if r["status"] in ("queued", "blocked") or r["status"] == "failed" and failures[r["url"]] < TRIES]


def make(account: str, url: str, text: str, run: str, seen_at: float) -> str:
    status = hands.comment(text) if room(account) else "queued"
    record(account, url=url, text=text, status=status, run=run, seen_at=seen_at)
    return status


def catch_up(account: str, run: Path, probing: bool = False) -> str | None:
    queue = waiting(account)
    if not queue or not room(account, probing):
        return None
    c = queue[0]
    came_from = hands.step_away(c["url"])
    try:
        code = c["url"].rstrip("/").split("/")[-1]
        status = hands.comment(c["text"]) if hands.drawn() and code in hands.current_url() else "failed"
    finally:
        hands.step_back(came_from)
    record(account, url=c["url"], text=c["text"], status=status, run=c["run"], seen_at=c["seen_at"], late=True)
    with (run / "late-comments.jsonl").open("a") as f:
        f.write(json.dumps({"url": c["url"], "text": c["text"], "seen_at": c["seen_at"], "posted_at": time.time(), "status": status},
                           ensure_ascii=False) + "\n")
    return status
