import json
import os
import signal
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import comments
import explore
import quota
import fetch
import hands
import think
from yt_dlp.utils import DownloadError

RUNS = Path(__file__).parent / "data" / "runs"
NOTES = Path(__file__).parent / "data" / "notes"
MOUSE = threading.Lock()
halted = {"at": 0.0, "why": ""}
STOP = Path(__file__).parent / "data" / "stop"
LIMITED = re.compile(r"usage limit|rate limit|quota", re.I)
RETRY = 1800
BLIP = re.compile(r"GOAWAY|server_shutting_down|ECONNRESET|connection reset|socket hang up|Service Unavailable|Bad Gateway|\b50[234]\b", re.I)
BLIP_TRIES, BLIP_WAIT = 3, 60


def links(folder: str, names: list[str]) -> list[str]:
    def link(path: str) -> bool:
        return os.path.islink(path) or os.path.isfile(path) and os.stat(path).st_nlink > 1
    return [n for n in names if link(os.path.join(folder, n))]


def notes_in(room: Path, kept: Path) -> None:
    if kept.exists():
        shutil.copytree(kept, room / "notes", dirs_exist_ok=True)
    (room / "notes" / "this-session").mkdir(parents=True)


def notes_out(room: Path, kept: Path, run: Path, started: float) -> None:
    mine = room / "notes" / "this-session"
    if mine.is_dir() and not mine.is_symlink() and any(mine.iterdir()):
        for where in (kept / time.strftime("%Y-%m-%d-%H%M", time.localtime(started)), run / "notes"):
            shutil.rmtree(where, ignore_errors=True)
            shutil.copytree(mine, where, ignore=links)


def next_reel(url: str) -> None:
    hands.close_comments()
    for attempt in range(3):
        hands.focus()
        if attempt < 2:
            hands.press_key(hands.DOWN_ARROW)
        else:
            hands.click_button(hands.find("Navigate to next Reel"))
        moved = time.time()
        while time.time() - moved < 4:
            if hands.current_url() != url:
                time.sleep(random.uniform(0.3, 0.9))
                return
            time.sleep(0.1)
    raise SystemExit("next Reel didn't load")


class Unwanted(SystemExit):
    pass


@dataclass
class Seat:
    tool: str
    profile: str | None
    run: Path
    kept: Path
    room: Path = field(default_factory=lambda: Path(tempfile.mkdtemp()))
    chat: dict = field(default_factory=lambda: {"id": None})
    meta: dict = field(default_factory=dict)
    window: int | None = None
    title: str | None = None
    done: int = 0
    url: str = ""
    shown_at: float = 0
    came_from: str | None = None
    post: dict | None = None
    decision: dict | None = None
    skipped: str | None = None
    ready_at: float = 0
    stopped: str | None = None

    def point(self) -> None:
        hands.use(self.window, self.title)

    def say(self, *words) -> None:
        print(f"[{self.tool}]", *words, flush=True)

    def save(self, ended: float | None = None) -> None:
        notes_out(self.room, self.kept, self.run, self.meta["started"])
        (self.run / "run.json.tmp").write_text(json.dumps({**self.meta, "conversation": self.chat["id"], "reels_done": self.done,
                                                            "stopped_by": self.stopped, "ended": ended}, indent=1))
        os.replace(self.run / "run.json.tmp", self.run / "run.json")


def hide(seat: Seat) -> None:
    seat.point()
    seat.url = hands.current_url()
    if "instagram.com/reels/" not in seat.url or seat.url.rstrip("/").endswith("/reels"):
        raise SystemExit(f"active tab isn't a Reel: {seat.url}")
    seat.shown_at = time.time()
    seat.came_from = hands.step_away()


def show(seat: Seat) -> None:
    seat.point()
    hands.step_back(seat.came_from)
    seat.came_from = None


def look(seat: Seat) -> None:
    for old in seat.room.iterdir():
        if old.name != "notes":
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    seat.post = seat.decision = seat.skipped = None
    code = seat.url.rstrip("/").split("/")[-1]
    try:
        seat.post = fetch.fetch(seat.url, seat.room)
        seat.decision = decide(seat, code)
    except DownloadError as e:
        if "no video" in str(e):
            seat.skipped = "photo post"
        elif "empty media response" in str(e) or "isn't available to everyone" in str(e):
            seat.skipped = "only shown to some viewers"
        else:
            raise
    except json.JSONDecodeError:
        seat.skipped = "unreadable reply"


def decide(seat: Seat, code: str) -> dict:
    blips = 0
    while True:
        try:
            return think.think(seat.room, seat.tool, seat.run / "transcripts" / f"{seat.done + 1:04d}-{code}.jsonl", seat.chat)
        except RuntimeError as e:
            if LIMITED.search(str(e)):
                back = quota.back_at(seat.tool)
                wait = max(back - time.time() + 60, 60) if back else RETRY
                seat.say(f"out of usage on its plan, trying again in {wait / 60:.0f} minutes"
                         + (f" (it resets at {time.strftime('%H:%M', time.localtime(back))})" if back else ""))
            elif BLIP.search(str(e)) and blips < BLIP_TRIES:
                blips += 1
                seat.say(f"server or connection blip, trying again in a minute: {str(e)[:120]!r}")
                wait = BLIP_WAIT
            else:
                raise
            ends = time.time() + wait
            while time.time() < ends:
                carry_on(seat)
                if STOP.exists():
                    raise SystemExit("stopped while waiting for its plan's usage to come back")
                time.sleep(5)


def act(seat: Seat, reels: int) -> None:
    seat.point()
    hands.focus()
    if seat.came_from:
        show(seat)
    if hands.current_url() != seat.url:
        raise SystemExit(f"came back to the wrong place: {hands.current_url()}")
    if not hands.drawn():
        raise SystemExit("the Reel's page is blank, even after a reload")
    if seat.skipped:
        with (seat.run / "reels.jsonl").open("a") as log:
            log.write(json.dumps({"url": seat.url, "shown_at": seat.shown_at, "skipped": seat.skipped}) + "\n")
        seat.say(seat.url, "skipped:", seat.skipped)
    else:
        decision, post = seat.decision, seat.post
        did_like = hands.like() if decision["like"] else False
        if decision["like"]:
            time.sleep(random.uniform(0.6, 1.2))
        comment = comments.make(seat.kept.name, seat.url, decision["comment"], seat.run.name, seat.shown_at) if decision.get("comment") else None
        followed = hands.follow(post["creator"]) if decision.get("follow") else None
        if decision.get("repost"):
            hands.repost()
        did_repost, said = False, None
        if decision["like"] or decision.get("comment") or decision.get("repost") or decision.get("follow"):
            time.sleep(2)
            did_repost = hands.reposted()
            said = hands.instagram_says()
            if said:
                seat.say("Instagram says:", said)
        unwanted = False
        if did_repost and not decision.get("repost"):
            unwanted = did_repost = explore.on_reposts_page(seat.url)
            if not unwanted:
                seat.say("a Repost badge showed, but the Reel isn't on this account's reposts page: someone else's repost")
        seat.done += 1
        with (seat.run / "reels.jsonl").open("a") as log:
            log.write(json.dumps({"n": seat.done, "url": seat.url, "shown_at": seat.shown_at, "finished_at": time.time(), "post": post,
                                  "decision": decision, "watched_seconds": post["seconds"] if decision["like"] else 0,
                                  "liked": did_like, "commented": comment == "posted" if comment else None, "comment": comment,
                                  "followed": followed, "reposted": did_repost, "instagram_said": said},
                                 ensure_ascii=False) + "\n")
        if unwanted:
            raise Unwanted(f"{seat.tool} reposted without being asked: {seat.url}")
        seat.say(seat.url, post["creator"], f"{post['seconds']:.0f}s |", "like" if did_like else "LIKE MISSED" if decision["like"] else "skip",
                 "| follow" if followed else "| FOLLOW MISSED" if decision.get("follow") else "",
                 f"| comment {comment}" if comment else "",
                 "| repost" if did_repost else "| REPOST MISSED" if decision.get("repost") else "",
                 f"| thought {decision['seconds']:.0f}s |", decision["note"])
    if seat.done < reels and not STOP.exists():
        next_reel(seat.url)
        hide(seat)
    else:
        seat.came_from = hands.step_away()


def stop(seat: Seat, e: BaseException) -> None:
    seat.stopped = repr(e)
    seat.say("stopped:", seat.stopped)
    with MOUSE:
        subprocess.run(["screencapture", "-x", str(seat.run / "stopped.png")])
        if seat.window and not seat.came_from:
            try:
                seat.point()
                seat.came_from = hands.step_away()
            except (Exception, SystemExit):
                pass


def carry_on(seat: Seat) -> None:
    if halted["at"] > seat.meta["started"]:
        raise SystemExit(f"every account stopped: {halted['why']}")


def play(seat: Seat, reels: int, snapshots: bool) -> None:
    try:
        with MOUSE:
            if seat.profile:
                seat.window, seat.title = hands.open_profile(seat.profile)
            else:
                seat.title = hands.window_profile()
            seat.point()
            if snapshots:
                seat.meta["account"] = explore.snapshot("before", seat.run)
                seat.say("logged in as", seat.meta["account"])
            hide(seat)
            late = comments.catch_up(seat.kept.name, seat.run, probing=True)
            if late:
                seat.say("waiting comment:", late)
        while seat.done < reels and not STOP.exists():
            carry_on(seat)
            look(seat)
            carry_on(seat)
            if seat.decision and seat.decision["like"]:
                with MOUSE:
                    seat.point()
                    show(seat)
                time.sleep(seat.post["seconds"])
            with MOUSE:
                act(seat, reels)
                late = comments.catch_up(seat.kept.name, seat.run)
                if late:
                    seat.say("waiting comment:", late)
            seat.save()
    except (Exception, SystemExit) as e:
        stop(seat, e)
    finally:
        seat.save()
        shutil.rmtree(seat.room, ignore_errors=True)
        with MOUSE:
            try:
                if seat.profile and not seat.window:
                    raise SystemExit("its window never opened")
                seat.point()
                hands.focus()
                if seat.came_from:
                    show(seat)
                if snapshots:
                    explore.snapshot("after", seat.run)
            except (Exception, SystemExit) as e:
                seat.say("no Explore snapshot after:", repr(e))
            if seat.window:
                subprocess.run(["osascript", "-e", f'tell application "Google Chrome" to close window id {seat.window}'], capture_output=True)
        seat.save(ended=time.time())


awake = threading.Lock()


def wake() -> None:
    if awake.acquire(blocking=False):
        subprocess.Popen(["caffeinate", "-du", "-w", str(os.getpid())])
    with MOUSE:
        screen = hands.Q.CGDisplayBounds(hands.Q.CGMainDisplayID())
        hands.move_to(screen.size.width / 2, screen.size.height / 2)
        time.sleep(2)


def wait_for(threads: list[threading.Thread]) -> None:
    if threading.current_thread() is threading.main_thread():
        def halt(*_) -> None:
            halted.update(at=time.time(), why="Ctrl-C")
            signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.signal(signal.SIGINT, halt)
    for t in threads:
        t.join()


def session(reels: int, seats: list[tuple[str, str | None]], snapshots: bool = True,
            together_with: list[str] | None = None) -> list[Path]:
    wake()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip()
    everyone = together_with or [t for t, _ in seats]
    table = []
    for tool, profile in seats:
        seat = Seat(tool, profile, RUNS / f"{stamp}-{tool}", NOTES / (f"{tool}-{profile.partition(':')[0]}" if profile else tool))
        seat.run.mkdir(parents=True)
        notes_in(seat.room, seat.kept)
        seat.meta = {"tool": tool, "model": think.MODELS[tool], "profile": profile, "reels_asked": reels, "commit": commit,
                     "together_with": [t for t in everyone if t != tool], "started": time.time(), "prompt": think.prompt(tool)}
        (seat.run / "run.json").write_text(json.dumps(seat.meta, indent=1))
        table.append(seat)
    threads = [threading.Thread(target=play, args=(seat, reels, snapshots), name=seat.tool) for seat in table]
    for t in threads:
        t.start()
    wait_for(threads)
    return [s.run for s in table]


if __name__ == "__main__":
    print(*session(int(sys.argv[1]), [(seat.partition("=")[0], seat.partition("=")[2] or None) for seat in sys.argv[2:]]), sep="\n")
