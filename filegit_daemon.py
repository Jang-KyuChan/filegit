# filegit_daemon.py
from __future__ import annotations

import time
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sqlite3
import shutil
import hashlib
from datetime import datetime

# --- 설정 및 헬퍼 (메인 스크립트와 공유) ---
FILEGIT_DIR = Path.home() / ".filegit"
OBJECTS_DIR = FILEGIT_DIR / "objects"
DB_PATH = FILEGIT_DIR / "index.db"
WATCHLIST_PATH = FILEGIT_DIR / "watchlist.json"


def get_file_hash(filepath: Path) -> str | None:
    if not filepath.exists(): return None
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192): hasher.update(chunk)
    return hasher.hexdigest()


def create_auto_snapshot(filepath_str: str, conn):
    """파일 변경 시 자동 스냅샷을 생성합니다."""
    filepath = Path(filepath_str)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT object_hash FROM commits WHERE file_path = ? ORDER BY timestamp DESC LIMIT 1",
        (filepath_str,)
    )
    last_hash_row = cursor.fetchone()
    last_hash = last_hash_row[0] if last_hash_row else None

    current_hash = get_file_hash(filepath)

    if current_hash and current_hash != last_hash:
        # 객체 저장소에 파일 복사
        if not OBJECTS_DIR.exists(): OBJECTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(filepath, OBJECTS_DIR / current_hash)

        # DB에 기록
        with conn:
            conn.execute(
                "INSERT INTO commits (file_path, object_hash, timestamp, type) VALUES (?, ?, ?, 'auto')",
                (filepath_str, current_hash, datetime.now().isoformat())
            )
        # 로그 파일에 기록하기 위해 print 사용
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Snapshot for {filepath_str}: {current_hash[:7]}")


# --- Watchdog 이벤트 핸들러 ---
class WatcherEventHandler(FileSystemEventHandler):
    def __init__(self, watchlist: set):
        super().__init__()
        self.watchlist = watchlist
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    def on_modified(self, event):
        if not event.is_directory:
            filepath_str = str(Path(event.src_path).resolve())
            if filepath_str in self.watchlist:
                try:
                    # 파일 쓰기가 완료될 시간을 벌어주기 위한 약간의 지연
                    time.sleep(0.1)
                    create_auto_snapshot(filepath_str, self.conn)
                except Exception as e:
                    print(f"Error creating snapshot for {filepath_str}: {e}")


# --- 데몬 메인 함수 ---
def run_daemon():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FileGit Daemon starting...")

    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.write_text("[]")

    try:
        with open(WATCHLIST_PATH, 'r') as f:
            watchlist_files = set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        watchlist_files = set()

    print(f"Watching {len(watchlist_files)} file(s).")

    event_handler = WatcherEventHandler(watchlist_files)
    observer = Observer()

    watch_dirs = {str(Path(p).parent) for p in watchlist_files}
    for path in watch_dirs:
        if Path(path).exists():
            observer.schedule(event_handler, path, recursive=False)
        else:
            print(f"Warning: Directory not found, cannot watch: {path}")

    observer.start()
    try:
        while True:
            # TODO: 워치리스트 파일 변경 감지 및 옵저버 리로드 기능 추가 가능
            time.sleep(5)
    except Exception as e:
        print(f"Daemon stopped due to an error: {e}")
        observer.stop()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FileGit Daemon stopped.")
    observer.join()


if __name__ == "__main__":
    # 데몬이 시작될 때 필요한 디렉토리와 DB 테이블이 생성되도록 보장
    if not DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        with conn:
            conn.execute("""
                         CREATE TABLE IF NOT EXISTS commits
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             file_path
                             TEXT
                             NOT
                             NULL,
                             object_hash
                             TEXT
                             NOT
                             NULL,
                             message
                             TEXT,
                             timestamp
                             TEXT
                             NOT
                             NULL,
                             type
                             TEXT
                             NOT
                             NULL
                             DEFAULT
                             'auto'
                         );
                         """)
        conn.close()
    run_daemon()