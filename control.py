import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import run
import think

CONTROL = Path(__file__).parent / "data" / "control"


OUTSIDE = re.compile(r"~|\$HOME|/Users/|\.\./|\bssh\b|curl|wget|https?://|security |keychain|osascript|\bopen ", re.I)


def touched(transcript: Path) -> list[str]:
    found = []
    for event in think.events(transcript.read_text()):
        for item in (event.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                found.append(f"{item['name']}: " + (item["input"].get("command") or item["input"].get("file_path") or json.dumps(item["input"])))
        for call in event.get("tool_calls") or []:
            found.append(f"{call['function']['name']}: {call['function']['arguments']}")
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "command_execution":
            found.append(f"Bash: {item['command']}")
    return found


def go(name: str, spec: str, links: list[dict]) -> None:
    tool, _, notes = spec.partition(":")
    earlier = CONTROL / f"notes-{tool}" if notes == "notes" else CONTROL / notes / "memory" if notes else None
    folder = CONTROL / name / (f"{tool}-fresh" if not notes else f"{tool}-notes" if notes == "notes" else f"after-{Path(notes).name}")
    folder.mkdir(parents=True, exist_ok=True)
    seat = run.Seat(tool, None, folder, kept=folder / "memory")
    if earlier and not seat.kept.exists():
        shutil.copytree(earlier, seat.kept)
    seat.meta = {"tool": tool, "model": think.MODELS[tool], "control_of": name, "with_notes": bool(notes),
                 "notes_from": str(earlier.relative_to(CONTROL)) if earlier else None,
                 "sandbox": think.CLAUDE_SANDBOX["sandbox"]["enabled"], "room": str(seat.room), "prompt": think.prompt(tool),
                 "started": time.time()}
    run.notes_in(seat.room, seat.kept)
    finished = [json.loads(line) for line in (folder / "reels.jsonl").read_text().split("\n")[:-1]] if (folder / "reels.jsonl").exists() else []
    if finished:
        before = json.loads((folder / "run.json").read_text())
        part = time.strftime("%Y-%m-%d-%H%M", time.localtime(before["started"]))
        shutil.rmtree(seat.room / "notes" / part, ignore_errors=True)
        if (seat.kept / part).exists():
            shutil.copytree(seat.kept / part, seat.room / "notes" / "this-session", dirs_exist_ok=True)
        seat.meta |= {"started": before["started"], "picked_up": time.time(), "earlier_conversation": before["conversation"]}
        seat.done = len(finished)
        links = [link for link in links if link["url"] not in {r["url"] for r in finished}]
    try:
        for link in links:
            seat.url = link["url"]
            run.look(seat)
            seat.done += 1
            row = {"n": seat.done, "url": seat.url, "shown_at": link["shown_at"], "post": seat.post, "decision": seat.decision,
                   "skipped": seat.skipped}
            with (folder / "reels.jsonl").open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            d = seat.decision or {}
            seat.say(seat.done, seat.url, seat.skipped or " ".join(k for k in ("like", "repost", "comment", "follow") if d.get(k)) or "skip")
            transcript = next((folder / "transcripts").glob(f"{seat.done:04d}-*.jsonl"), None)
            for step in touched(transcript) if transcript else []:
                seat.say("  " + ("OUTSIDE? " if OUTSIDE.search(step) else "") + step[:300].replace("\n", " "))
            seat.save()
        seat.save(ended=time.time())
    except BaseException as e:
        seat.stopped = repr(e)
        seat.save(ended=time.time())
        seat.say("stopped:", repr(e))


def summary(name: str) -> None:
    for folder in sorted((CONTROL / name).iterdir()):
        rows = [json.loads(line) for line in (folder / "reels.jsonl").read_text().split("\n")[:-1]] if (folder / "reels.jsonl").exists() else []
        decided = [r["decision"] for r in rows if r["decision"]]
        if decided:
            print(f"{folder.name:<7} {len(decided)} Reels: " + ", ".join(
                f"{k} {sum(bool(d.get(k)) for d in decided) / len(decided):.0%}" for k in ("like", "comment", "follow", "repost")))


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    if "--no-sandbox" in sys.argv:
        sys.argv.remove("--no-sandbox")
        think.CLAUDE_SANDBOX = {"sandbox": {"enabled": False}}
    name, tools = sys.argv[1], sys.argv[2:]
    rows = [json.loads(line) for line in (CONTROL / name / "links.jsonl").read_text().split("\n")[:-1]]
    links = [r for r in rows if r["ad"] is False]
    print(f"{len(links)} Reels from {name}'s feed, for {', '.join(tools)}", flush=True)
    threads = [threading.Thread(target=go, args=(name, tool, links)) for tool in tools]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    summary(name)


if __name__ == "__main__":
    main()
