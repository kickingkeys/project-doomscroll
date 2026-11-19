import math
import random
import re
import subprocess
import sys
import time

import tempfile
from pathlib import Path

import ApplicationServices as AS
import Foundation
import Quartz as Q
import Vision

DOWN_ARROW, ESCAPE, DELETE, RETURN = 125, 53, 51, 36
LIMITED = re.compile(r"couldn.t post comment|try again later|we restrict certain activity|action blocked|we limit how often", re.I)
expected_profile = None
target = None


def osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def window() -> str:
    return f"window id {target}" if target else "front window"


def use(window_id: int | None, profile: str | None) -> None:
    global target, expected_profile
    target, expected_profile = window_id, profile


def focus() -> None:
    if not target:
        return
    osascript(f'tell application "Google Chrome"\n set index of {window()} to 1\n activate\n end tell')
    for _ in range(20):
        if osascript('tell application "Google Chrome" to get id of front window') == str(target) and window_profile() == expected_profile:
            return
        time.sleep(0.25)
    raise SystemExit(f"{expected_profile}'s window won't come to the front")


def current_url() -> str:
    return osascript(f'tell application "Google Chrome" to get URL of active tab of {window()}')


def bring_chrome_forward() -> None:
    osascript('tell application "Google Chrome" to activate')


def step_away(url: str = "about:blank") -> str:
    came_from = osascript(f'tell application "Google Chrome" to get active tab index of {window()}')
    osascript(f'tell application "Google Chrome" to tell {window()} to make new tab with properties {{URL:"{url}"}}')
    return came_from


def step_back(came_from: str) -> None:
    osascript(f"""tell application "Google Chrome" to tell {window()}
        close active tab
        set active tab index to {came_from}
    end tell""")


def watch() -> None:
    last = None
    while True:
        url = current_url()
        if url != last:
            print(url, flush=True)
            last = url


def attr(element, name: str):
    error, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else None


def box(element) -> tuple[float, float, float, float] | None:
    position, size = attr(element, "AXPosition"), attr(element, "AXSize")
    if position is None or size is None:
        return None
    _, p = AS.AXValueGetValue(position, AS.kAXValueCGPointType, None)
    _, s = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
    return p.x, p.y, s.width, s.height


def chrome_app():
    pid = int(subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True, text=True, check=True).stdout.split()[0])
    return AS.AXUIElementCreateApplication(pid)


def typed_text() -> str:
    return str(attr(attr(chrome_app(), "AXFocusedUIElement"), "AXValue") or "")


def chrome_window():
    app = chrome_app()
    AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    AS.AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface", True)
    AS.AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface", True)
    return attr(app, "AXFocusedWindow") or attr(app, "AXWindows")[0]


def on_screen() -> list[dict]:
    window = chrome_window()
    wx, wy, ww, wh = box(window)
    found, stack = [], [window]
    while stack:
        element = stack.pop()
        stack.extend(attr(element, "AXChildren") or [])
        name = attr(element, "AXDescription") or attr(element, "AXTitle") or attr(element, "AXPlaceholderValue")
        where = box(element) if name else None
        if not where or not where[2] or not where[3]:
            continue
        x, y = where[0] + where[2] / 2, where[1] + where[3] / 2
        if wx <= x <= wx + ww and wy <= y <= wy + wh:
            found.append({"name": str(name), "role": str(attr(element, "AXRole")), "x": x, "y": y})
    return found


def window_profile() -> str:
    return str(attr(chrome_window(), "AXTitle")).rsplit(" - ", 1)[-1]


def open_profile(name: str) -> tuple[int, str]:
    global expected_profile, target
    target = None
    folder, _, title = name.partition(":")
    subprocess.run(["open", "-na", "Google Chrome", "--args", f"--profile-directory={folder}", "--no-first-run",
                    "https://www.instagram.com/reels/"], check=True)
    time.sleep(6)
    expected_profile = title or folder
    if window_profile() != expected_profile:
        raise SystemExit(f"front window is {window_profile()!r}, not {expected_profile!r}")
    for _ in range(30):
        if not current_url().rstrip("/").endswith("/reels"):
            break
        time.sleep(1)
    osascript('tell application "Google Chrome" to set bounds of front window to '
              '(run script "tell application \\"Finder\\" to get bounds of window of desktop")')
    target = int(osascript('tell application "Google Chrome" to get id of front window'))
    osascript(f"""tell application "Google Chrome" to tell window id {target}
        set keep to active tab index
        repeat with i from (count of tabs) to 1 by -1
            if i is not keep then close tab i
        end repeat
    end tell""")
    return target, expected_profile


def named(name: str, button: str) -> bool:
    return re.fullmatch(re.escape(button) + r"( [\d.,]+[KkMmBb]?)?", name) is not None


def nearest(*names: str) -> dict | None:
    if not current_url().startswith("https://www.instagram.com/"):
        raise SystemExit(f"active tab isn't Instagram: {current_url()}")
    if expected_profile and window_profile() != expected_profile:
        raise SystemExit(f"front window is {window_profile()!r}, not {expected_profile!r}")
    buttons = [e for e in on_screen() if e["role"] in ("AXButton", "AXPopUpButton")]
    matches = [e for e in buttons if any(named(e["name"], n) for n in names)]
    wx, wy, ww, wh = box(chrome_window())
    matches = [e for e in matches if wy + wh / 4 < e["y"] < wy + wh - 2]
    return max(matches, key=lambda e: e["y"]) if matches else None


def find(name: str) -> dict:
    target = nearest(name)
    if not target:
        raise SystemExit(f"nothing called {name!r} on screen")
    return target


def liked() -> bool:
    heart = nearest("Like", "Unlike")
    return bool(heart) and heart["name"].startswith("Unlike")


def like() -> bool:
    close_comments()
    if liked():
        return True
    mouse_off_buttons()
    for _ in range(6):
        try:
            target = find("Like")
            break
        except SystemExit:
            time.sleep(0.5)
    else:
        return False
    if not click_button(target):
        return False
    mouse_off_buttons()
    for _ in range(16):
        if liked():
            return True
        time.sleep(0.25)
    return False


def drawn() -> bool:
    for attempt in range(2):
        for _ in range(20):
            if nearest("Like", "Unlike", "Comment"):
                return True
            time.sleep(0.5)
        if attempt == 0:
            osascript(f'tell application "Google Chrome" to reload active tab of {window()}')
    return False


def comment_box() -> dict | None:
    return next((e for e in on_screen() if e["role"] in ("AXTextField", "AXTextArea") and e["name"].startswith("Add a comment")), None)


def close_comments() -> None:
    for _ in range(3):
        if not comment_box():
            return
        press_key(ESCAPE)
        time.sleep(0.5)
    raise SystemExit("comments panel won't close")


def mouse_off_buttons() -> None:
    x, y, width, height = box(chrome_window())
    move_to(x + width / 2, y + height / 2)
    time.sleep(random.uniform(0.8, 1.2))


def open_comment_box() -> dict | None:
    for attempt in range(2):
        field = try_comment_box()
        if field or attempt or comment_box():
            return field
    return None


def try_comment_box() -> dict | None:
    mouse_off_buttons()
    click_button(find("Comment"))
    for _ in range(12):
        time.sleep(0.25)
        field = comment_box()
        if field:
            for _ in range(2):
                click_at(field["x"], field["y"])
                for _ in range(8):
                    time.sleep(0.25)
                    if in_comment_box():
                        time.sleep(random.uniform(0.2, 0.5))
                        return field
            break
    close_comments()
    return None


def in_comment_box() -> bool:
    return str(attr(attr(chrome_app(), "AXFocusedUIElement"), "AXRole")) in ("AXTextField", "AXTextArea")


def box_says(text: str) -> bool:
    for _ in range(12):
        time.sleep(0.25)
        if typed_text().strip() == text.strip():
            return True
    return False


def comment(text: str) -> str:
    if not open_comment_box():
        print("comment not posted: the comment box didn't open", flush=True)
        return "failed"
    type_text(text)
    if not box_says(text) and not typed_text().strip():
        type_text(text)
        box_says(text)
    time.sleep(random.uniform(0.4, 0.9))
    if typed_text().strip() != text.strip():
        print(f"comment not posted: box says {typed_text()!r}", flush=True)
        press_key(ESCAPE)
        return "failed"
    press_key(RETURN)
    for _ in range(12):
        time.sleep(0.25)
        if not typed_text().strip():
            break
    else:
        if typed_text().strip() == text.strip():
            click_button(find("Post"))
        for _ in range(12):
            time.sleep(0.25)
            if not typed_text().strip():
                break
        else:
            press_key(ESCAPE)
            return "failed"
    for _ in range(8):
        if LIMITED.search(screen_text()):
            press_key(ESCAPE)
            return "blocked"
        time.sleep(0.25)
    press_key(ESCAPE)
    return "posted"


def screen_text() -> str:
    x, y, width, height = box(chrome_window())
    with tempfile.TemporaryDirectory() as folder:
        shot = Path(folder) / "screen.png"
        subprocess.run(["screencapture", "-x", "-R", f"{x:.0f},{y:.0f},{width:.0f},{height:.0f}", str(shot)], check=True)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(Foundation.NSURL.fileURLWithPath_(str(shot)), None)
        handler.performRequests_error_([request], None)
        return " | ".join(str(r.topCandidates_(1)[0].string()) for r in (request.results() or []))


def instagram_says() -> str | None:
    found = LIMITED.search(screen_text())
    return found.group(0) if found else None


def repost() -> None:
    click_button(find("Repost"))


def reposted() -> bool:
    _, y, _, height = box(chrome_window())
    return any(e["role"] == "AXImage" and e["name"] == "Repost" and e["y"] > y + height / 4 for e in on_screen())


def follow_button(creator: str) -> dict | None:
    button = nearest("Follow", "Following")
    if button and any(e["name"] == f"{creator} reels" and abs(e["y"] - button["y"]) < 20 for e in on_screen()):
        return button
    return None


def poster_shown(creator: str) -> bool:
    _, y, _, height = box(chrome_window())
    return any(e["name"] == f"{creator} reels" and e["y"] > y + height / 4 for e in on_screen())


def follow(creator: str) -> bool:
    close_comments()
    mouse_off_buttons()
    target = follow_button(creator)
    if not target:
        return poster_shown(creator)
    if target["name"] == "Following":
        return True
    if not click_button(target):
        return False
    mouse_off_buttons()
    for _ in range(16):
        button = follow_button(creator)
        if button and button["name"] == "Following" or not button and poster_shown(creator):
            return True
        time.sleep(0.25)
    return False


def post(kind: int, x: float, y: float) -> None:
    event = Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonLeft)
    Q.CGEventPost(Q.kCGHIDEventTap, event)


def move_to(x: float, y: float) -> None:
    start = Q.CGEventGetLocation(Q.CGEventCreate(None))
    distance = math.hypot(x - start.x, y - start.y)
    bend_x = (start.x + x) / 2 + random.uniform(-0.15, 0.15) * distance
    bend_y = (start.y + y) / 2 + random.uniform(-0.15, 0.15) * distance
    steps = max(2, int(distance / 12))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        px = (1 - t) ** 2 * start.x + 2 * (1 - t) * t * bend_x + t ** 2 * x
        py = (1 - t) ** 2 * start.y + 2 * (1 - t) * t * bend_y + t ** 2 * y
        post(Q.kCGEventMouseMoved, px, py)
        time.sleep(random.uniform(0.004, 0.012))


def button_at(x: float, y: float) -> str | None:
    _, element = AS.AXUIElementCopyElementAtPosition(chrome_app(), x, y, None)
    while element is not None:
        if str(attr(element, "AXRole")) in ("AXButton", "AXPopUpButton"):
            return str(attr(element, "AXDescription") or attr(element, "AXTitle") or "") or None
        element = attr(element, "AXParent")
    return None


def press(x: float, y: float) -> None:
    post(Q.kCGEventLeftMouseDown, x, y)
    time.sleep(random.uniform(0.04, 0.1))
    post(Q.kCGEventLeftMouseUp, x, y)


def click_at(x: float, y: float) -> None:
    move_to(x, y)
    time.sleep(random.uniform(0.05, 0.15))
    press(x, y)


def click_button(target: dict) -> bool:
    x, y = target["x"], target["y"]
    move_to(x, y)
    time.sleep(random.uniform(0.05, 0.15))
    under = button_at(x, y)
    if under and not named(under, re.sub(r" [\d.,]+[KkMmBb]?$", "", target["name"])):
        print(f"didn't click {target['name']!r}: {under!r} is there now", flush=True)
        return False
    press(x, y)
    return True


def press_key(code: int) -> None:
    Q.CGEventPost(Q.kCGHIDEventTap, Q.CGEventCreateKeyboardEvent(None, code, True))
    time.sleep(random.uniform(0.04, 0.1))
    Q.CGEventPost(Q.kCGHIDEventTap, Q.CGEventCreateKeyboardEvent(None, code, False))


def type_text(text: str) -> None:
    if not text.isascii():
        subprocess.run(["pbcopy"], input=text.encode(), env={"LC_CTYPE": "UTF-8"}, check=True)
        osascript('tell application "System Events" to keystroke "v" using command down')
        return
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    osascript(f'tell application "System Events" to keystroke "{escaped}"')


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "check":
        print("allowed:", AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    elif command == "watch":
        watch()
    elif command == "list":
        for e in on_screen():
            print(f"{e['role']:<16} {e['x']:>6.0f} {e['y']:>6.0f}  {e['name']}")
    elif command == "move":
        bring_chrome_forward()
        target = find(sys.argv[2])
        move_to(target["x"], target["y"])
    elif command == "click":
        bring_chrome_forward()
        target = find(sys.argv[2])
        click_at(target["x"], target["y"])
    elif command == "next":
        bring_chrome_forward()
        press_key(DOWN_ARROW)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
