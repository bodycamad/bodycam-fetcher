"""
혼합 수집 스크립트 (48 h 범위 · Private/Deleted 제외 · 키워드 필터)
──────────────────────────────────────────────────────────────
• channels.txt  ─ 형식:  UCID [>> keyword1, keyword2, …]
    ↳ 키워드가 없으면 채널 ‘전체 업로드’, 있으면 제목 필터
• playlists.txt ─ 형식:  PLID
──────────────────────────────────────────────────────────────
"""

import os, datetime, pathlib, subprocess
from googleapiclient.discovery import build

# ───── 1. API 키
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY secret 가 없습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ───── 2. 날짜 계산 (UTC 오늘 + 전날 00:00Z 이후 48 h 범위)
today       = datetime.datetime.utcnow().date()          # e.g. 2025-05-31
yesterday   = today - datetime.timedelta(days=1)
today_iso   = today.isoformat()                          # '2025-05-31'
published_after = f"{yesterday.isoformat()}T00:00:00Z"

# ───── 3. helpers ──────────────────────────────────────────
def parse_channels_file(path="channels.txt"):
    """채널 파일 → [(UCID, [keywords…]), …]"""
    res = []
    if not pathlib.Path(path).exists():
        return res
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            if line.strip().startswith("#") or not line.strip():
                continue
            if ">>" in line:
                cid, kw = line.split(">>", 1)
                keywords = [k.strip().lower() for k in kw.split(",") if k.strip()]
            else:
                cid, keywords = line, []
            res.append((cid.strip(), keywords))
    return res

def read_simple_list(path="playlists.txt"):
    if not pathlib.Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fp:
        return [l.split("#")[0].strip() for l in fp if l.strip()]

# ───── 4. API 조회 함수 ─────────────────────────────────────
def video_ids_from_channel(cid: str):
    """채널에서 최근 48 h 영상 반환 [(videoId, title), …]"""
    res = yt.search().list(
        part="id,snippet",
        channelId=cid,
        order="date",
        publishedAfter=published_after,
        type="video",
        maxResults=10
    ).execute()
    return [
        (i["id"]["videoId"], i["snippet"]["title"])
        for i in res.get("items", [])
        if i["snippet"]["title"] not in ("Private video", "Deleted video")
           and i["snippet"]["publishedAt"][:10] == today_iso
    ]

def video_ids_from_playlist(plid: str):
    vids = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=plid,
        maxResults=50
    )
    while req:
        res = req.execute()
        for item in res["items"]:
            if item["snippet"]["title"] in ("Private video", "Deleted video"):
                continue
            dt = item["contentDetails"].get("videoPublishedAt") \
                 or item["snippet"]["publishedAt"]
            if dt[:10] == today_iso:
                vids.append((item["contentDetails"]["videoId"],
                             item["snippet"]["title"]))
        req = yt.playlistItems().list_next(req, res)
    return vids

# ───── 5. 다운로드 함수 ────────────────────────────────────
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

# ───── 6. 채널 처리 (키워드 필터 적용) ───────────────────────
channels     = parse_channels_file()
playlist_ids = read_simple_list("playlists.txt")

for cid, kw_list in channels:
    out_dir = pathlib.Path("data") / cid
    out_dir.mkdir(parents=True, exist_ok=True)

    vids = video_ids_from_channel(cid)
    if kw_list:                                   # 키워드가 있으면 제목 필터
        vids = [
            (vid, title) for vid, title in vids
            if any(k in title.lower() for k in kw_list)
        ]

    if not vids:
        print(f"[CHANNEL] {cid}: No new videos")
    else:
        for vid, _ in vids:
            fetch_and_save(vid, out_dir)
        print(f"[CHANNEL] {cid}: {len(vids)} videos processed")

# ───── 7. 재생목록 처리 ────────────────────────────────────
for plid in playlist_ids:
    out_dir = pathlib.Path("data") / plid
    out_dir.mkdir(parents=True, exist_ok=True)

    vids = video_ids_from_playlist(plid)
    if not vids:
        print(f"[PLAYLIST] {plid}: No new videos")
    else:
        for vid, _ in vids:
            fetch_and_save(vid, out_dir)
        print(f"[PLAYLIST] {plid}: {len(vids)} videos processed")
