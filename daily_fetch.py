#!/usr/bin/env python3
"""
YouTube Body-Cam Fetcher
────────────────────────────────────────────────────────────────────
● channels.txt ─ UCxxxxxxxxxxxxxxxxxxxxxxxx  [>> keyword1, keyword2 …]
    ↳ UC… → UU…(업로드 재생목록)로 바꿔 playlistItems 호출
● playlists.txt ─ 재생목록 ID 한 줄씩
────────────────────────────────────────────────────────────────────
최근 48 h 영상만 · Private/Deleted 제외 · 키워드 필터 · 중복 다운로드 방지
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import pathlib
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ────────────── 0. 로깅 ──────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)

# ────────────── 1. YouTube API ─────────────────────────────────
API_KEY = os.getenv("YT_API_KEY")
if not API_KEY:
    raise EnvironmentError("환경 변수 YT_API_KEY 가 설정되어 있지 않습니다.")
yt = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ────────────── 2. 48 h 시간 경계 ───────────────────────────────
UTC = dt.timezone.utc
THRESHOLD_DT = dt.datetime.now(UTC) - dt.timedelta(hours=48)

# ────────────── 3. Cookie 파일(선택) ───────────────────────────
COOKIES_FILE = os.getenv("YT_COOKIES_FILE", "cookies.txt")
USE_COOKIES = pathlib.Path(COOKIES_FILE).is_file()

# ────────────── 4. 보조 함수들 ─────────────────────────────────
def to_upload_playlist_id(cid: str) -> str:
    """채널 ID(UC…) → 업로드 재생목록 ID(UU…)"""
    return "UU" + cid[2:] if cid.startswith("UC") and len(cid) == 24 else cid[:24]


def parse_channels_file(
    path: str = "channels.txt",
) -> List[Tuple[str, List[str], str]]:
    """channels.txt 파싱 → (playlist_id, keywords, 설명) 목록"""
    res: List[Tuple[str, List[str], str]] = []
    p = pathlib.Path(path)
    if not p.exists():
        return res

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue

        if "#" in line:
            data_part, desc = line.split("#", 1)
            desc = desc.strip()
        else:
            data_part, desc = line, ""

        data_part = data_part.strip()
        if not data_part:
            continue

        if ">>" in data_part:
            cid_part, kw_part = data_part.split(">>", 1)
            keywords = [k.strip() for k in kw_part.split(",") if k.strip()]
        else:
            cid_part, keywords = data_part, []

        pl_id = to_upload_playlist_id(cid_part.strip())
        if len(pl_id) == 24:
            res.append((pl_id, keywords, desc or pl_id))
        else:
            logging.warning("잘못된 ID 무시: %s", pl_id)

    return res

def read_playlists(path: str = "playlists.txt") -> List[Tuple[str, str]]:
    """playlists.txt 파싱 → (playlist_id, 설명) 목록"""
    p = pathlib.Path(path)
    if not p.exists():
        return []

    res: List[Tuple[str, str]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue

        if "#" in line:
            pl_id, desc = line.split("#", 1)
            pl_id = pl_id.strip()
            desc = desc.strip()
        else:
            pl_id, desc = line, line

        if pl_id:
            res.append((pl_id, desc))

    return res

def safe_execute(req, retries: int = 3):
    """YouTube API 호출 + 간단 재시도 로직"""
    for attempt in range(retries):
        try:
            return req.execute()
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            msg = str(e)
            # 쿼터 소진 → 즉시 종료
            if status == 403 and "quotaExceeded" in msg:
                logging.info("YouTube API 일일 쿼터 소진. 스크립트 중단.")
                sys.exit(0)

            # 일시적 오류는 back-off 후 재시도
            if status in (500, 502, 503, 504):
                wait = 2 ** attempt
                logging.warning("YouTube API %s 오류, %s초 뒤 재시도", status, wait)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("YouTube API 재시도 한도 초과")


def video_ids_from_playlist(pl_id: str) -> List[Tuple[str, str]]:
    """
    playlistItems → 48 h 이내 (videoId, title) 목록.
    만약 'playlist not found(404)' 에러가 발생하면 빈 리스트를 반환하고 경고 로그를 남깁니다.
    """
    vids: List[Tuple[str, str]] = []
    req = yt.playlistItems().list(
        part="contentDetails,snippet",
        playlistId=pl_id,
        maxResults=50,
    )
    while req:
        try:
            res = safe_execute(req)
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            # 404인 경우(재생목록이 없거나 접근 불가), 건너뛰고 빈 목록 반환
            if status == 404:
                logging.warning("플레이리스트를 찾을 수 없습니다: %s (404)", pl_id)
                return []  # 빈 리스트 반환 → handle_playlist 에서 "새 영상 없음" 으로 처리됨
            # 그 외 오류는 그대로 상위로 던집니다.
            raise

        for it in res.get("items", []):
            title = it["snippet"]["title"]
            if title in ("Private video", "Deleted video"):
                continue

            dt_raw = (
                it["contentDetails"].get("videoPublishedAt")
                or it["snippet"]["publishedAt"]
            )
            dt_obj = dt.datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
            if dt_obj >= THRESHOLD_DT:
                vids.append((it["contentDetails"]["videoId"], title))

        req = yt.playlistItems().list_next(req, res)
    return vids


def fetch_and_save(video_id: str, out_dir: pathlib.Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        f"https://www.youtube.com/watch?v={video_id}",
        "--write-info-json",
        "--write-description",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
        "--merge-output-format",
        "mp4",
        "--write-thumbnail",
        "--convert-thumbnails",
        "jpg",
        "--download-archive",
        str(out_dir / "downloaded.txt"),
        "-o",
        str(out_dir / "%(upload_date)s_%(id)s.%(ext)s"),
    ]
    if USE_COOKIES:
        cmd[1:1] = ["--cookies", COOKIES_FILE]

    try:
        # 로그를 상세히 보기 위해 stdout/stderr를 기록
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,  # run 결과를 캡처
            text=True,
        )
        logging.info("✓ 다운로드 완료: %s", video_id)
        logging.debug("yt-dlp stdout: %s", result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error("✗ yt-dlp 실패 (%s): %s", e.returncode, video_id)
        logging.error("yt-dlp stderr: %s", e.stderr)  # 에러 메시지 남김


def handle_playlist(pl_id: str, keywords: List[str], desc: str) -> int:
    """재생목록 하나 처리 → 다운로드 개수 반환"""
    out_dir = pathlib.Path("data") / pl_id
    videos = video_ids_from_playlist(pl_id)

    # 키워드 필터 (제목 정규식 OR 매칭)
    if keywords:
        pattern = re.compile("|".join(map(re.escape, keywords)), re.I)
        videos = [(vid, t) for vid, t in videos if pattern.search(t)]

    if not videos:
        logging.info("[%s] 새 영상 없음", desc)
        return 0

    logging.info("[%s] 새 영상 %d개", desc, len(videos))

    # 병렬 다운로드 (network-bound → 4~8 스레드면 충분)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(fetch_and_save, vid, out_dir) for vid, _ in videos]
        for _ in as_completed(futures):
            pass
    return len(videos)


# ────────────── Main ───────────────────────────────────────────
def main():
    total = 0
    for pl_id, kws, desc in parse_channels_file():
        total += handle_playlist(pl_id, kws, desc)

    for pl_id, desc in read_playlists():
        total += handle_playlist(pl_id, [], desc)

    logging.info("작업 완료 — 총 %d개 영상 처리", total)


if __name__ == "__main__":
    main()
