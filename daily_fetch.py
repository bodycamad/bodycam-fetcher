"""
혼합 수집 스크립트 (48 h · Private/Deleted 제외 · 키워드 필터 · 저쿼터)
────────────────────────────────────────────────────────────────────
• channels.txt  ─ UCID [>> keyword1, keyword2, …]
    ↳ UC… → UU… 변환 후 업로드 재생목록에서 조회(1 unit)
• playlists.txt ─ PLID (그대로)
────────────────────────────────────────────────────────────────────
"""

import os, datetime, pathlib, subprocess
from googleapiclient.discovery import build

# ─── 1. API 키 ────────────────────────────────────────────────
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY 시크릿이 설정돼 있지 않습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ─── 2. 날짜 계산 (UTC 오늘 + 전날 00:00Z 이후 48 h 범위) ─────
today      = datetime.datetime.utcnow().date()          # 2025-05-31
yesterday  = today - datetime.timedelta(days=1)         # 2025-05-30
today_iso  = today.isoformat()                          # '2025-05-31'

# ─── 3. channels.txt 파싱 (UC → UU 변환 + 키워드 분리) ────────
def to_upload_playlist_id(cid: str) -> str:
    """UC… → UU… (업로드 재생목록) | 이미 UU… 면 그대로"""
    return "UU" + cid[2:] if cid.startswith("UC") and len(cid) == 24 else cid

def parse_channels_file(path: str = "channels.txt"):
    entries = []
    if not pathlib.Path(path).exists():
        return entries
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            if line.strip().startswith("#") or not line.strip():
                continue
            if ">>" in line:
                cid_part, kw_part = line.split(">>", 1)
                keywords = [k.strip().lower() for k in kw_part.split(",") if k.strip()]
            else:
                cid_part, keywords = line, []
            pl_id = to_upload_playlist_id(cid_part.strip())
            entries.append((pl_id, keywords))
    return entries

def read_playlists(path="playlists.txt"):
    if not pathlib.Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fp:
        return [l.split("#")[0].strip() for l in fp if l.strip()]

# ─── 4. 업로드/재생목록에서 오늘 영상 추출 ───────────────────
def video_ids_from_playlist(pl_id: str):
    """지정 재생목록(uploads or PL…)에서 *오늘* 영상 [(id, title), …]"""
    vids = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=pl_id,
        maxResults=50
    )
    while req:
        res = req.execute()
        for item in res.get("items", []):
            title = item["snippet"]["title"]
            if title in ("Private video", "Deleted video"):
                continue
            dt = item["contentDetails"].get("videoPublishedAt") \
                 or item["snippet"]["publishedAt"]
            if dt[:10] == today_iso:
                vids.append((item["contentDetails"]["videoId"], title))
        # 날짜가 이미 어제 이전이면 더 내려갈 필요 없음
        if res["items"] and (res["items"][-1]["contentDetails"]
                             .get("videoPublishedAt", "9999")[:10]) < today_iso:
            break
        req = yt.playlistItems().list_next(req, res)
    return vids

# ─── 5. 다운로드 함수 ─────────────────────────────────────────
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

# ─── 6. 채널(업로드 재생목록) 처리 ────────────────────────────
channels = parse_channels_file()
for pl_id, kw_list in channels:
    out = pathlib.Path("data") / pl_id
    out.mkdir(parents=True, exist_ok=True)

    vids = video_ids_from_playlist(pl_id)
    if kw_list:                                   # 제목 키워드 필터
        vids = [
            (vid, title) for vid, title in vids
            if any(k in title.lower() for k in kw_list)
        ]

    if not vids:
        print(f"[CHANNEL] {pl_id}: No new videos")
    else:
        for vid, _ in vids:
            fetch_and_save(vid, out)
        print(f"[CHANNEL] {pl_id}: {len(vids)} videos processed")

# ─── 7. playlists.txt 처리 ───────────────────────────────────
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
