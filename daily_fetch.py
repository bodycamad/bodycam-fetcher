"""
혼합 수집 스크립트
───────────────────────────────────────────────
• channels.txt  → 채널 전체 업로드(오늘 업로드분)
• playlists.txt → 특정 재생목록(오늘 추가분)
───────────────────────────────────────────────
"""

import os, datetime, pathlib, subprocess
from googleapiclient.discovery import build

# ───────────────── 1. 환경 변수에서 API 키 읽기
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("YT_API_KEY secret가 설정되지 않았습니다.")

yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)
today_iso = datetime.datetime.utcnow().date().isoformat()        # 'YYYY-MM-DD'
published_after = today_iso + "T00:00:00Z"                       # 채널 검색용

# ───────────────── 2. 오늘 업로드 영상 id 얻기 함수 (채널·재생목록)
def video_ids_from_channel(cid: str) -> list[str]:
    """해당 채널에서 오늘 업로드된 videoId 리스트"""
    res = yt.search().list(
        part="id",
        channelId=cid,
        order="date",
        publishedAfter=published_after,
        type="video",
        maxResults=10
    ).execute()
    return [i["id"]["videoId"] for i in res.get("items", [])]

def video_ids_from_playlist(plid: str) -> list[str]:
    """재생목록에 오늘 추가된 videoId 리스트 (videoPublishedAt이 누락된 항목 대비)"""
    vids = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=plid,
        maxResults=50
    )
    while req:
        res = req.execute()
        for item in res["items"]:
            dt = item["contentDetails"].get("videoPublishedAt") \
                 or item["snippet"]["publishedAt"]
            if dt[:10] == today_iso:            # 'YYYY-MM-DD'
                vids.append(item["contentDetails"]["videoId"])
        req = yt.playlistItems().list_next(req, res)
    return vids

# ───────────────── 3. 두 텍스트 파일에서 ID 읽기
def read_id_file(path: str):
    if not pathlib.Path(path).exists():
        return []
    with open(path, encoding="utf-8") as fp:
        return [line.split("#")[0].strip() for line in fp if line.strip()]

channel_ids   = read_id_file("channels.txt")
playlist_ids  = read_id_file("playlists.txt")

# ───────── 4. 공통 다운로드 함수 (MP4 + 썸네일 + 중복 방지)
def fetch_and_save(video_id: str, folder: pathlib.Path):
    subprocess.run([
        "yt-dlp",
        f"https://www.youtube.com/watch?v={video_id}",

        # a) 메타데이터·설명
        "--write-info-json", "--write-description",

        # b) 본영상 (mp4 한 파일로)
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "--merge-output-format", "mp4",

        # c) 대표 썸네일(YouTube 기본 1280×720)
        "--write-thumbnail",               # .jpg 생성
        "--convert-thumbnails", "jpg",     # webp → jpg 변환

        # d) 중복 방지
        "--download-archive", str(folder / "downloaded.txt"),

        # e) 출력 템플릿
        "-o", str(folder / "%(upload_date)s_%(id)s.%(ext)s"),

        "--no-warnings"
    ], check=True)

# ───────────────── 5. 채널 전체 업로드 처리
for cid in channel_ids:
    out_dir = pathlib.Path("data") / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    for vid in video_ids_from_channel(cid):
        fetch_and_save(vid, out_dir)

# ───────────────── 6. 재생목록 전용 처리
for plid in playlist_ids:
    out_dir = pathlib.Path("data") / plid
    out_dir.mkdir(parents=True, exist_ok=True)
    for vid in video_ids_from_playlist(plid):
        fetch_and_save(vid, out_dir)
