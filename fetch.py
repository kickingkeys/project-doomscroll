import subprocess
from pathlib import Path

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget


def fetch(url: str, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    options = {
        "outtmpl": str(folder / "reel.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "impersonate": ImpersonateTarget("chrome"),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url)
    seconds = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(folder / "reel.mp4")],
                             capture_output=True, text=True, check=True).stdout
    post = {
        "creator": info.get("channel") or info.get("uploader"),
        "caption": info.get("description"),
        "seconds": float(seconds),
    }
    (folder / "post.txt").write_text(f"Posted by: {post['creator']}\nLength: {post['seconds']} seconds\nCaption: {post['caption']}\n")
    return post
