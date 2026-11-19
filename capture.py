import json
import re
import sys
import time
from pathlib import Path

import hands

REEL = re.compile(r"https://www\.instagram\.com/reels?/([\w-]+)")
CALL_TO_ACTION = re.compile(r"learn more|shop now|install now|sign up|book now|get offer|get quote|order now|apply now|contact us|"
                            r"send message|send whatsapp message|watch more|see menu|buy tickets|buy now|play game|donate now|"
                            r"listen now|get showtimes|get directions|call now|use app|open link|get access|start order|"
                            r"get promotions|try in camera|visit (instagram )?profile|download", re.I)


def texts() -> list[dict]:
    window = hands.chrome_window()
    wx, wy, ww, wh = hands.box(window)
    found, stack = [], [window]
    while stack:
        element = stack.pop()
        stack.extend(hands.attr(element, "AXChildren") or [])
        name = hands.attr(element, "AXDescription") or hands.attr(element, "AXTitle") or hands.attr(element, "AXValue")
        if not isinstance(name, str) or not name.strip():
            continue
        where = hands.box(element)
        if where and where[3] and wy + wh / 4 < where[1] + where[3] / 2 < wy + wh - 2:
            found.append({"name": name.strip(), "role": str(hands.attr(element, "AXRole")), "y": where[1]})
    return found


def ad_signs(page: list[dict]) -> set[str]:
    signs = set()
    for t in page:
        if t["name"].lower() == "sponsored":
            signs.add("Sponsored")
        elif t["role"] in ("AXButton", "AXLink") and CALL_TO_ACTION.fullmatch(t["name"]):
            signs.add(t["name"])
    return signs


def heart(page: list[dict]) -> bool | None:
    hearts = [t for t in page if t["role"] == "AXButton" and re.fullmatch(r"(Like|Unlike)( [\d.,]+[KkMmBb]?)?", t["name"])]
    return max(hearts, key=lambda t: t["y"])["name"].startswith("Unlike") if hearts else None


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    name, wanted = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30
    out = Path(__file__).parent / "data" / "control" / name / "links.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in out.read_text().split("\n")[:-1]] if out.exists() else []
    seen = {r["code"] for r in rows}
    kept = sum(r["ad"] is False for r in rows)
    print(f"{kept} Reels kept so far in {out}. Scroll Reels in Chrome's front window; Ctrl-C stops.", flush=True)
    last = None
    while kept < wanted:
        try:
            url = hands.current_url()
        except Exception:
            time.sleep(0.5)
            continue
        match = REEL.match(url)
        if not match or url == last:
            time.sleep(0.2)
            continue
        last, code, shown_at = url, match.group(1), time.time()
        if code in seen:
            continue
        signs, liked, reads = set(), None, 0
        while True:
            try:
                page = texts()
            except Exception:
                page = None
            try:
                still = hands.current_url() == url
            except Exception:
                still = True
            if not still:
                break
            if page is not None:
                reads += 1
                signs |= ad_signs(page)
                liked = heart(page) if heart(page) is not None else liked
            time.sleep(0.2)
        ad = bool(signs) if reads else None
        seen.add(code)
        kept += ad is False
        with out.open("a") as f:
            f.write(json.dumps({"url": f"https://www.instagram.com/reels/{code}/", "code": code, "shown_at": shown_at,
                                "seconds_on_screen": round(time.time() - shown_at, 1), "person_liked": liked,
                                "ad": ad, "ad_signs": sorted(signs)}) + "\n")
        print(f"{kept}/{wanted}", url, f"{time.time() - shown_at:.1f}s", "liked" if liked else "",
              "AD " + ", ".join(sorted(signs)) if ad else "NOT CHECKED" if ad is None else "", flush=True)
    print("done:", out)


if __name__ == "__main__":
    main()
