import os, datetime, subprocess, pathlib
from googleapiclient.discovery import build

# ▶ (1) GitHub Secret에 저장해 둘 API 키 불러오기
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise ValueError("YT_API_KEY 환경변수가 없어요!")

# ▶ (2) YouTube API 클라이언트 준비
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ▶ (3) 오늘 00:00(UTC) 이후 업로드만 검색
today_iso = datetime.datetime.utcnow().date().isoformat() + "T00:00:00Z"

def today_video_ids(channel_id: str):
    """지정 채널의 오늘 업로드된 videoId 목록 반환"""
    res = yt.search().list(
        part="id", channelId=channel_id,
        order="date", publishedAfter=today_iso,
        maxResults=10, type="video"
    ).execute()
    return [item["id"]["videoId"] for item in res.get("items", [])]

# ▶ (4) channels.txt 읽어 영상마다 메타데이터 파일 저장
for cid in open("channels.txt", encoding="utf-8"):
    cid = cid.strip()
    if not cid: 
        continue
    pathlib.Path(f"data/{cid}").mkdir(parents=True, exist_ok=True)
    for vid in today_video_ids(cid):
        subprocess.run([
            "yt-dlp",
            "--skip-download",
            "--write-info-json",       # 메타데이터
            "--write-description",     # 설명란 텍스트
            "-o", f"data/{cid}/%(upload_date)s_%(id)s",
            f"https://www.youtube.com/watch?v={vid}"
        ], check=True)
