import json
import re
import subprocess
import sys
import time
from pathlib import Path

import hands

FOLDER = Path(__file__).parent / "data" / "explore"
LOAD_SECONDS = 6


def tiles() -> list[dict]:
    found, stack = [], [hands.chrome_window()]
    while stack:
        element = stack.pop()
        stack.extend(hands.attr(element, "AXChildren") or [])
        url = hands.attr(element, "AXURL")
        if url and any(part in str(url) for part in ("/p/", "/reel/")):
            images = [c for c in hands.attr(element, "AXChildren") or []]
            names = [hands.attr(c, "AXDescription") or hands.attr(c, "AXTitle") for c in images]
            found.append({"url": str(url), "text": hands.attr(element, "AXDescription") or hands.attr(element, "AXTitle") or next((n for n in names if n), None)})
    return found


def account() -> str:
    x = hands.box(hands.chrome_window())[0]
    found, stack = [], [hands.chrome_window()]
    while stack:
        element = stack.pop()
        stack.extend(hands.attr(element, "AXChildren") or [])
        match = re.fullmatch(r"https://www.instagram.com/([\w.]+)/", str(hands.attr(element, "AXURL")))
        where = hands.box(element) if match else None
        if where and where[0] < x + 120 and match.group(1) not in ("explore", "reels", "direct"):
            found.append((where[1], match.group(1)))
    return max(found)[1]


def snapshot(label: str, parent: Path = FOLDER) -> str:
    if not hands.current_url().startswith("https://www.instagram.com/"):
        raise SystemExit(f"active tab isn't Instagram: {hands.current_url()}")
    out = parent / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    out.mkdir(parents=True)
    came_from = hands.step_away("https://www.instagram.com/explore/")
    try:
        time.sleep(LOAD_SECONDS)
        (out / "tiles.json").write_text(json.dumps(tiles(), ensure_ascii=False, indent=1))
        x, y, w, h = hands.box(hands.chrome_window())
        shot = subprocess.run(["screencapture", "-x", "-R", f"{x:.0f},{y:.0f},{w:.0f},{h:.0f}", str(out / "explore.png")],
                              capture_output=True, text=True)
        if shot.returncode:
            print("no screenshot:", shot.stderr.strip(), flush=True)
        handle = account()
    finally:
        hands.step_back(came_from)
    came_from = hands.step_away(f"https://www.instagram.com/{handle}/reposts/")
    try:
        time.sleep(LOAD_SECONDS)
        (out / "reposts.json").write_text(json.dumps(tiles(), ensure_ascii=False, indent=1))
    finally:
        hands.step_back(came_from)
    return handle


def on_reposts_page(url: str) -> bool:
    code = url.rstrip("/").split("/")[-1]
    came_from = hands.step_away(f"https://www.instagram.com/{account()}/reposts/")
    try:
        time.sleep(LOAD_SECONDS)
        return any(f"/{code}/" in t["url"] for t in tiles())
    finally:
        hands.step_back(came_from)


if __name__ == "__main__":
    print(snapshot(sys.argv[1] if len(sys.argv) > 1 else "manual"))
