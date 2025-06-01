"""
혼합 수집 스크립트 · 48 h · Private/Deleted 제외 · 키워드 필터 · 저쿼터
───────────────────────────────────────────────────────────────────────
• channels.txt  ─  UCxxxxxxxxxxxxxxxxxxxxxxxx  [>> keyword1, keyword2 …]
    ↳ UC… → UU…(업로드 재생목록) 로 변환해 playlistItems(1 unit) 호출
• playlists.txt ─  재생목록 ID 한 줄씩
───────────────────────────────────────────────────────────────────────
"""

import os
import sys
import datetime
import pathlib
import subprocess
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ───── 1. API 키 ────────────────────────────────────────────────
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY secret 가 없습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ───── 2. 날짜 (UTC 오늘 + 전날 00 Z 이후 48 h) ─────────────────
today      = datetime.datetime.utcnow().date()          # e.g. 2025-06-01
yesterday  = today - datetime.timedelta(days=1)         # 2025-05-31
today_iso  = today.isoformat()                          # '2025-06-01'
yest_iso   = yesterday.isoformat()                      # '2025-05-31'

# ───── 3. 도우미 함수 ───────────────────────────────────────────
def to_upload_playlist_id(cid: str) -> str:
    """UC… → UU… (업로드 재생목록)  |  이미 UU… 면 그대로"""
    return "UU" + cid[2:] if cid.startswith("UC") and len(cid) == 24 else cid

def parse_channels_file(path: str = "channels.txt"):
    """channels.txt → [(업로드 PLID, [keywords…]), …]"""
    res = []
    if not pathlib.Path(path).exists():
        return res
    with open(path, encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.split("#", 1)[0].strip()           # 주석 제거
            if not raw:
                continue
            if ">>" in raw:
                cid_part, kw_part = raw.split(">>", 1)
                keywords = [k.strip().lower() for k in kw_part.split(",") if k.strip()]
            else:
                cid_part, keywords = raw, []
            pl_id = to_upload_playlist_id(cid_part.strip())[:24]  # 24자 이내
            if len(pl_id) != 24:
                print("[WARN] skipped invalid ID:", pl_id)
                continue
            res.append((pl_id, keywords))

    # ── DEBUG: 파싱 결과 ───────────────────────────────────────
    for cid, kw in res:
        print("[DEBUG] parsed:", cid, "keywords:", kw)
    return res

def read_playlists(path="playlists.txt"):
    if not pathlib.Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fp:
        return [l.split("#", 1)[0].strip() for l in fp if l.strip()]

# ───── 4. execute 래퍼 (쿼터 초과 시 우아한 종료) ───────────────
def safe_execute(req):
    try:
        return req.execute()
    except HttpError as e:
        if e.resp.status == 403 and "quotaExceeded" in str(e):
            print("[INFO] API quota exhausted for today — stopping early.")
            sys.exit(0)          # 성공(✔) 상태로 워크플로 종료
        raise                    # 다른 오류는 그대로 전파

# ───── 5. playlistItems → 48 h 영상 목록 ───────────────────────
def video_ids_from_playlist(pl_id: str):
    vids = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=pl_id,
        maxResults=50
    )
    while req:
        res = safe_execute(req)
        for it in res.get("items", []):
            title = it["snippet"]["title"]
            if title in ("Private video", "Deleted video"):
                continue

            # videoPublishedAt 우선, 없으면 snippet.publishedAt
            dt = it["contentDetails"].get("videoPublishedAt") \
                 or it["snippet"]["publishedAt"]              # ISO8601 → 'YYYY-MM-DD…'

            # ▶ 어제 00 Z 이후(48 h 창) 이면 다운로드
            if dt[:10] >= yest_iso:                           # ★ 변경된 부분
                vids.append((it["contentDetails"]["videoId"], title))

        req = yt.playlistItems().list_next(req, res)
    return vids

# ───── 6. 다운로드 함수 ─────────────────────────────────────────
def fetch_and_save(video_id: str, out_dir: pathlib.Path):
    cmd = [
        "yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
        "--write-info-json", "--write-description",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "--merge-output-format", "mp4",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--download-archive", str(out_dir / "downloaded.txt"),
        "-o", str(out_dir / "%(upload_date)s_%(id)s.%(ext)s"),
        "--no-warnings", "--ignore-errors"
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] yt-dlp failed for {video_id}: {e.returncode}")

# ───── 7. 채널(업로드 재생목록) 처리 ───────────────────────────
channels = parse_channels_file()
for pl_id, kw in channels:
    out = pathlib.Path("data") / pl_id
    out.mkdir(parents=True, exist_ok=True)

    vids = video_ids_from_playlist(pl_id)
    if kw:
        vids = [(v, t) for v, t in vids if any(k in t.lower() for k in kw)]

    if not vids:
        print(f"[CHANNEL] {pl_id}: No new videos")
    else:
        for vid, _ in vids:
            fetch_and_save(vid, out)
        print(f"[CHANNEL] {pl_id}: {len(vids)} videos processed")

# ───── 8. playlists.txt 처리 ──────────────────────────────────
for pl_id in read_playlists():
    out = pathlib.Path("data") / pl_id
    out.mkdir(parents=True, exist_ok=True)

    vids = video_ids_from_playlist(pl_id)
    if not vids:
        print(f"[PLAYLIST] {pl_id}: No new videos")
    else:
        for vid, _ in vids:
            fetch_and_save(vid, out)
        print(f"[PLAYLIST] {pl_id}: {len(vids)} videos processed")
