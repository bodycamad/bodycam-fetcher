"""
혼합 수집 스크립트 (48 h · Private/Deleted 제외 · 키워드 필터 · 저쿼터)
"""

import os, datetime, pathlib, subprocess
from googleapiclient.discovery import build

# ─── 1. API 키
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY secret 가 없습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ─── 2. 날짜 (UTC 오늘 + 전날 00 Z 이후 48 h)
today      = datetime.datetime.utcnow().date()
yesterday  = today - datetime.timedelta(days=1)
today_iso  = today.isoformat()

# ─── 3. helpers
def to_upload_playlist_id(cid: str) -> str:
    return "UU" + cid[2:] if cid.startswith("UC") and len(cid) == 24 else cid

def parse_channels_file(path: str = "channels.txt"):
    """
    channels.txt → [(업로드 재생목록 ID, [키워드…]), …]

    • 줄 형식:  UCxxxxxxxxxxxxxxxxxxxxxxxx >> keyword1, keyword2  # comment
    • UC… → UU… 로 자동 변환 (이미 UU… 쓰면 그대로)
    • '#' 이후 주석·공백은 모두 제거
    • 길이 24자가 아니면 건너뜀
    """
    res = []
    if not pathlib.Path(path).exists():
        return res

    with open(path, encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.split("#", 1)[0].strip()          # 주석 제거
            if not raw:
                continue

            # 키워드 분리
            if ">>" in raw:
                cid_part, kw_part = raw.split(">>", 1)
                keywords = [k.strip().lower() for k in kw_part.split(",") if k.strip()]
            else:
                cid_part, keywords = raw, []

            pl_id = to_upload_playlist_id(cid_part.strip())[:24]  # 24자 이내로 자르기
            if len(pl_id) != 24:
                print("[WARN] skipped invalid ID:", pl_id)
                continue

            res.append((pl_id, keywords))

    # ── DEBUG: 파싱 결과 확인 ────────────────────────────────
    for cid, kw in res:
        print("[DEBUG] parsed:", cid, "keywords:", kw)

    return res

def read_playlists(path="playlists.txt"):
    if not pathlib.Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fp:
        return [l.split("#",1)[0].strip() for l in fp if l.strip()]

# ─── 4. playlistItems → 오늘 영상
def video_ids_from_playlist(pl_id: str):
    vids, req = [], yt.playlistItems().list(
        part="contentDetails,snippet", playlistId=pl_id, maxResults=50)
    while req:
        res = req.execute()
        for it in res.get("items", []):
            title = it["snippet"]["title"]
            if title in ("Private video", "Deleted video"): continue
            dt = it["contentDetails"].get("videoPublishedAt") or it["snippet"]["publishedAt"]
            if dt[:10] == today_iso:
                vids.append((it["contentDetails"]["videoId"], title))
        req = yt.playlistItems().list_next(req, res)
    return vids

# ─── 5. downloader
def fetch_and_save(vid: str, out: pathlib.Path):
    cmd = [
        "yt-dlp", f"https://www.youtube.com/watch?v={vid}",
        "--write-info-json", "--write-description",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4", "--merge-output-format", "mp4",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--download-archive", str(out / "downloaded.txt"),
        "-o", str(out / "%(upload_date)s_%(id)s.%(ext)s"),
        "--no-warnings", "--ignore-errors"
    ]
    try: subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] yt-dlp failed for {vid}: {e.returncode}")

# ─── 6. 채널(업로드 재생목록) 처리
channels = parse_channels_file()
for pl_id, kw in channels:
    out = pathlib.Path("data") / pl_id; out.mkdir(parents=True, exist_ok=True)
    vids = video_ids_from_playlist(pl_id)
    if kw:
        vids = [(v,t) for v,t in vids if any(k in t.lower() for k in kw)]
    print(f"[CHANNEL] {pl_id}: {len(vids)} new" if vids else f"[CHANNEL] {pl_id}: No new videos")
    for vid,_ in vids: fetch_and_save(vid, out)

# ─── 7. playlists.txt 처리
for pl_id in read_playlists():
    out = pathlib.Path("data") / pl_id; out.mkdir(parents=True, exist_ok=True)
    vids = video_ids_from_playlist(pl_id)
    print(f"[PLAYLIST] {pl_id}: {len(vids)} new" if vids else f"[PLAYLIST] {pl_id}: No new videos")
    for vid,_ in vids: fetch_and_save(vid, out)
