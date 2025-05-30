"""
daily_fetch.py
────────────────────────────────────────────────────────
• playlists.txt에 적어 둔 YouTube 재생목록(PL…)마다
  ─ 오늘(UTC 기준) 새로 추가된 영상의 메타데이터와 설명란만 저장
• 필요 라이브러리: google-api-python-client, yt-dlp
────────────────────────────────────────────────────────
"""

import os
import datetime
import pathlib
import subprocess
from googleapiclient.discovery import build

# ──────────────────────── 1. 환경 변수로부터 API 키 가져오기
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("환경변수 YT_API_KEY 가 설정돼 있지 않습니다.")

# ──────────────────────── 2. YouTube API 클라이언트 초기화
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# 오늘 날짜(UTC) 문자열 : 'YYYY-MM-DD'
today_str = datetime.datetime.utcnow().date().isoformat()

# ──────────────────────── 3. 오늘 추가된 videoId 추출 함수
def today_video_ids_from_playlist(pl_id: str) -> list[str]:
    """지정 재생목록(playlistId)에서 *오늘* 새로 추가된 videoId 리스트 반환"""
    vids: list[str] = []
    req = yt.playlistItems().list(
        part="contentDetails",
        playlistId=pl_id,
        maxResults=50,          # 1회 최대 50개
    )
    while req:
        res = req.execute()
        for item in res["items"]:
            # videoPublishedAt → 'YYYY-MM-DDTHH:MM:SSZ'
            published_date = item["contentDetails"]["videoPublishedAt"][:10]
            if published_date == today_str:
                vids.append(item["contentDetails"]["videoId"])
        req = yt.playlistItems().list_next(req, res)
    return vids

# ──────────────────────── 4. playlists.txt 읽어 루프 실행
with open("playlists.txt", encoding="utf-8") as fp:
    playlist_ids = [line.split("#")[0].strip() for line in fp if line.strip()]

for pl_id in playlist_ids:
    out_dir = pathlib.Path("data") / pl_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for vid in today_video_ids_from_playlist(pl_id):
        subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-info-json",
                "--write-description",
                "--no-warnings",
                "-o", str(out_dir / "%(upload_date)s_%(id)s"),
                f"https://www.youtube.com/watch?v={vid}",
            ],
            check=True,
        )
