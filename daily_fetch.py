"""
혼합 수집 스크립트  (Private/Deleted 필터 + UTC-1일 여유)
────────────────────────────────────────────────────────
• channels.txt  → 채널 전체 업로드(최근 48 h)
• playlists.txt → 특정 재생목록(최근 48 h)
────────────────────────────────────────────────────────
"""

import os, datetime, pathlib, subprocess
from googleapiclient.discovery import build

# ───── 1. API 키
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY secret가 설정돼 있지 않습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ───── 2. 날짜 계산 (UTC ‘오늘’ + 전날 00시 이후 범위)
today      = datetime.datetime.utcnow().date()           # e.g. 2025-05-31
yesterday  = today - datetime.timedelta(days=1)          # 2025-05-30
today_iso  = today.isoformat()                           # '2025-05-31'
published_after = f"{yesterday.isoformat()}T00:00:00Z"   # 48 h 범위 시작점

# ───── 3. 오늘 영상 추출 함수 (채널 · 재생목록)
def video_ids_from_channel(cid: str):
    res = yt.search().list(
        part="id,snippet",
        channelId=cid, order="date",
        publishedAfter=published_after,
        type="video", maxResults=10
    ).execute()
    return [
        (i["id"]["videoId"], i["snippet"]["title"])
        for i in res.get("items", [])
        if i["snippet"]["title"] not in ("Private video", "Deleted video")
           and i["snippet"]["publishedAt"][:10] == today_iso     # ← 날짜 필터
    ]

def video_ids_from_playlist(plid: str):
    vids = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=plid, maxResults=50)
    while req:
        res = req.execute()
        for item in res["items"]:
            if item["snippet"]["title"] in ("Private video", "Deleted video"):
                continue
            dt = item["contentDetails"].get("videoPublishedAt") \
                 or item["snippet"]["publishedAt"]
            if dt[:10] == today_iso:                           # ← 여기서 today_iso 사용
                vids.append((item["contentDetails"]["videoId"],
                             item["snippet"]["title"]))
        req = yt.playlistItems().list_next(req, res)
    return vids

# ───── 4. ID 목록 읽기
def read_id_file(p):
    if not pathlib.Path(p).exists(): return []
    with open(p, encoding="utf-8") as f:
        return [l.split("#")[0].strip() for l in f if l.strip()]

channel_ids  = read_id_file("channels.txt")
playlist_ids = read_id_file("playlists.txt")

# ───── 5. 다운로드 함수
def fetch_and_save(vid: str, folder: pathlib.Path):
    cmd = [
        "yt-dlp", f"https://www.youtube.com/watch?v={vid}",
        "--write-info-json", "--write-description",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "--merge-output-format", "mp4",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--download-archive", str(folder / "downloaded.txt"),
        "-o", str(folder / "%(upload_date)s_%(id)s.%(ext)s"),
        "--no-warnings", "--ignore-errors"
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] yt-dlp failed for {vid}: {e.returncode}")

# ───── 6. 채널 처리
for cid in channel_ids:
    out = pathlib.Path("data") / cid; out.mkdir(parents=True, exist_ok=True)
    vids = video_ids_from_channel(cid)
    if not vids:
        print(f"[CHANNEL] {cid}: No new videos")
    else:
        for vid, _ in vids: fetch_and_save(vid, out)
        print(f"[CHANNEL] {cid}: {len(vids)} videos processed")

# ───── 7. 재생목록 처리
for plid in playlist_ids:
    out = pathlib.Path("data") / plid; out.mkdir(parents=True, exist_ok=True)
    vids = video_ids_from_playlist(plid)
    if not vids:
        print(f"[PLAYLIST] {plid}: No new videos")
    else:
        for vid, _ in vids: fetch_and_save(vid, out)
        print(f"[PLAYLIST] {plid}: {len(vids)} videos processed")
