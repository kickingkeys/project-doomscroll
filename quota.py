import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

RUNS = Path(__file__).parent / "data" / "runs"


def when(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%b %d %H:%M")


def kimi_usages() -> dict:
    token = json.loads((Path.home() / ".kimi-code/credentials/kimi-code.json").read_text())["access_token"]
    request = urllib.request.Request("https://api.kimi.com/coding/v1/usages", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=20) as r:
        return json.load(r)["usages"]


def back_at(tool: str) -> float | None:
    if tool != "kimi":
        return None
    try:
        used_up = [u for u in kimi_usages().values() if u["used_ratio"] >= 0.99]
    except Exception:
        return None
    if not used_up:
        return None
    return max(datetime.fromisoformat(u["reset_time"].replace("Z", "+00:00")).timestamp() for u in used_up)


def kimi() -> str:
    u = kimi_usages()
    five, month = u["limit_5h"], u["limit_month_total"]
    return (f"5 hours {five['used_ratio']:.0%} used (resets {when(five['reset_time'])}), "
            f"month {month['used_ratio']:.0%} used (resets {when(month['reset_time'])})")


def grok() -> str:
    today = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
    totals = {"today": [0, 0], "30 days": [0, 0]}
    for transcript in RUNS.glob("*-grok/transcripts/*.jsonl"):
        made = transcript.stat().st_mtime
        if made < time.time() - 30 * 86400:
            continue
        for line in transcript.read_text().splitlines():
            if '"type":"result"' not in line.replace(" ", ""):
                continue
            usage = json.loads(line).get("usage") or {}
            tokens = sum(v for k, v in usage.items() if k in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"))
            for span in ["30 days"] + (["today"] if made >= today else []):
                totals[span][0] += 1
                totals[span][1] += tokens
    return ", ".join(f"{span} {reels} Reels, {tokens / 1e6:.1f}M tokens" for span, (reels, tokens) in totals.items())


def check(tool: str) -> str:
    try:
        return {"kimi": kimi, "grok": grok}[tool]()
    except Exception as e:
        return f"couldn't read: {e!r}"


if __name__ == "__main__":
    for tool in sys.argv[1:] or ["kimi", "grok"]:
        print(tool, check(tool))
