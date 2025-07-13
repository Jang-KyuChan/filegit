#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
import hashlib
import click
import difflib
import json
import os
import sys
import signal
from daemon import DaemonContext
from daemon.pidfile import PIDLockFile

# --- TUI 관련 import ---
from textual.app import App, ComposeResult, on
from textual.widgets import Header, Footer, DataTable, Static, Input
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.binding import Binding

# --- 설정 (데몬과 공유) ---
FILEGIT_DIR = Path.home() / ".filegit"
OBJECTS_DIR = FILEGIT_DIR / "objects"
DB_PATH = FILEGIT_DIR / "index.db"
WATCHLIST_PATH = FILEGIT_DIR / "watchlist.json"
PID_FILE_PATH = FILEGIT_DIR / "daemon.pid"
LOG_FILE_PATH = FILEGIT_DIR / "daemon.log"

# 데몬 스크립트의 절대 경로
DAEMON_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "filegit_daemon.py")


def get_file_hash(filepath: Path) -> str | None:
    if not filepath.exists(): return None
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192): hasher.update(chunk)
    return hasher.hexdigest()


def format_timestamp(ts_iso: str) -> str:
    dt_obj = datetime.fromisoformat(ts_iso)
    return dt_obj.strftime('%y-%m-%d %H:%M:%S')


def setup_repo():
    OBJECTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    return conn


# --- TUI 애플리케이션 (이전과 동일) ---
class CommitInputScreen(ModalScreen):
    # ... (생략, 이전과 동일)
    def __init__(self, commit_id: int): super().__init__(); self.commit_id = commit_id

    def compose(self) -> ComposeResult:
        dialog = Vertical(Static("커밋 메시지를 입력하세요 (ESC: 취소):"), Input(placeholder="메시지...", id="commit-input"),
                          id="commit-dialog")
        dialog.styles.align = ("center", "middle")
        dialog.styles.width = 60
        dialog.styles.height = 5
        dialog.styles.border = ("thick", "dodgerblue")
        yield dialog

    def on_mount(self) -> None: self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None: self.dismiss(event.value or None)


class DashboardApp(App):
    # ... (생략, 이전과 동일)
    BINDINGS = [
        Binding("q", "quit", "종료"), Binding("a", "add_snapshot", "스냅샷 추가(A)"),
        Binding("c", "commit_message", "커밋 메시지(C)"), Binding("r", "restore_selected", "선택 버전으로 복원(R)"),
        Binding("f", "forget_file", "추적 중단(F)"), Binding("s", "refresh_status", "상태 새로고침(S)"),
    ]

    def __init__(self, filepath: Path):
        super().__init__();
        self.filepath = filepath;
        self.conn = setup_repo()
        self.timeline_panel = DataTable(id="timeline_table");
        self.content_panel = Static(id="content_view", expand=True)
        self.diff_panel = Static(id="diff_view", expand=True);
        self.header = Header()
        self.current_row_key = None;
        self.is_forget_pending = False

    def compose(self) -> ComposeResult:
        left_pane = Vertical(self.timeline_panel, self.diff_panel, id="left-pane")
        main_container = Horizontal(left_pane, self.content_panel, id="main-container")
        main_container.styles.height = "1fr";
        left_pane.styles.width = "60%";
        left_pane.styles.min_width = 40;
        left_pane.styles.border_right = ("solid", "dodgerblue")
        self.timeline_panel.styles.height = "60%";
        self.timeline_panel.styles.border_bottom = ("solid", "dodgerblue")
        self.diff_panel.styles.height = "40%";
        self.diff_panel.styles.padding = (0, 1)
        self.content_panel.styles.width = "40%";
        self.content_panel.styles.padding = (0, 1)
        yield self.header;
        yield main_container;
        yield Footer()

    def on_mount(self) -> None:
        self.timeline_panel.cursor_type = "row";
        self.timeline_panel.add_columns("타입", "날짜", "해시", "메시지");
        self.refresh_all()

    def refresh_all(self):
        self.update_header(); self.load_timeline()

    def update_header(self):
        current_hash = get_file_hash(self.filepath);
        style_map = {"success": "darkgreen", "warning": "darkgoldenrod", "error": "darkred"};
        style = "success"
        if not current_hash:
            style, status_text = "error", "[DELETED]"
        else:
            cursor = self.conn.cursor();
            cursor.execute("SELECT object_hash FROM commits WHERE file_path = ? ORDER BY timestamp DESC LIMIT 1",
                           (str(self.filepath),));
            last_commit = cursor.fetchone()
            if not last_commit or current_hash != last_commit['object_hash']:
                style, status_text = "warning", "[MODIFIED]"
            else:
                style, status_text = "success", "[up-to-date]"
        self.header.text = f"📜 {self.filepath.name}";
        self.header.sub_text = f"상태: {status_text}";
        self.header.styles.background = style_map.get(style, "darkblue")

    def load_timeline(self):
        self.timeline_panel.clear();
        cursor = self.conn.cursor();
        cursor.execute("SELECT * FROM commits WHERE file_path = ? ORDER BY timestamp DESC", (str(self.filepath),));
        logs = cursor.fetchall()
        last_commit = logs[0] if logs else None;
        current_hash = get_file_hash(self.filepath);
        is_modified = not last_commit or (current_hash and current_hash != last_commit['object_hash'])
        if is_modified and current_hash:
            marker = "(temp)";
            ts = format_timestamp(datetime.now().isoformat());
            msg = "저장되지 않은 변경 사항";
            prev_hash = last_commit['object_hash'] if last_commit else None
            self.timeline_panel.add_row(marker, ts, current_hash[:12], msg, key=f"{current_hash}|{prev_hash}|temp|temp")
        for i, log in enumerate(logs):
            marker = "(*)" if log['type'] == 'manual' else "(')";
            ts = format_timestamp(log['timestamp']);
            msg = log['message'] or "";
            prev_hash = logs[i + 1]['object_hash'] if i + 1 < len(logs) else None
            self.timeline_panel.add_row(marker, ts, log['object_hash'][:12], msg,
                                        key=f"{log['object_hash']}|{prev_hash}|{log['id']}|{log['type']}")

    @on(DataTable.RowHighlighted)
    def update_views(self, event: DataTable.RowHighlighted) -> None:
        self.current_row_key = event.row_key;
        if not self.current_row_key or not self.current_row_key.value: return
        current_hash, prev_hash, _, _ = self.current_row_key.value.split('|', 4)
        if current_hash and (OBJECTS_DIR / current_hash).exists():
            content_path = OBJECTS_DIR / current_hash;
        else:
            content_path = self.filepath
        try:
            self.content_panel.update(content_path.read_text(encoding='utf-8'))
        except Exception:
            self.content_panel.update("[내용을 읽을 수 없습니다]")
        if not prev_hash or prev_hash == 'None': self.diff_panel.update("[첫 커밋이므로 이전 버전 없음]"); return
        try:
            prev_content = (OBJECTS_DIR / prev_hash).read_text(encoding='utf-8').splitlines()
            if "temp" in self.current_row_key.value:
                current_content = self.filepath.read_text(encoding='utf-8').splitlines()
            else:
                current_content = (OBJECTS_DIR / current_hash).read_text(encoding='utf-8').splitlines()
            diff = difflib.unified_diff(prev_content, current_content, fromfile='a', tofile='b', lineterm='');
            self.diff_panel.update("\n".join(diff))
        except Exception:
            self.diff_panel.update("[Diff 생성 중 오류]")

    def action_add_snapshot(self) -> None:
        current_hash = get_file_hash(self.filepath);
        if not current_hash: self.notify("파일을 찾을 수 없습니다.", severity="error"); return
        shutil.copy(self.filepath, OBJECTS_DIR / current_hash)
        with self.conn: self.conn.execute("INSERT INTO commits (file_path, object_hash, timestamp) VALUES (?, ?, ?)",
                                          (str(self.filepath), current_hash, datetime.now().isoformat()))
        self.notify("✨ 스냅샷을 추가했습니다.", title="Snapshot Added");
        self.refresh_all()

    def action_commit_message(self) -> None:
        if not self.current_row_key: self.notify("먼저 타임라인에서 행을 선택하세요.", severity="warning", timeout=2); return
        key_value = self.current_row_key.value;
        _, _, commit_id, commit_type = key_value.split('|', 4)
        if commit_type == 'manual': self.notify("이미 수동 커밋입니다.", severity="warning"); return
        if commit_type == 'temp': self.notify("먼저 스냅샷을 추가(A)해야 커밋할 수 있습니다.", severity="error"); return

        def on_submit(message: str | None):
            if message:
                with self.conn: self.conn.execute("UPDATE commits SET type = 'manual', message = ? WHERE id = ?",
                                                  (message, int(commit_id)))
                self.notify(f"📌 커밋 완료: {message}");
                self.refresh_all()

        self.push_screen(CommitInputScreen(int(commit_id)), on_submit)

    def action_restore_selected(self) -> None:
        if not self.current_row_key: self.notify("먼저 타임라인에서 행을 선택하세요.", severity="warning", timeout=2); return
        key_value = self.current_row_key.value;
        selected_hash, _, _, commit_type = key_value.split('|', 4)
        if commit_type == 'temp': self.notify("현재 작업중인 버전입니다.", severity="information"); return
        shutil.copy(OBJECTS_DIR / selected_hash, self.filepath);
        self.notify(f"✅ [{selected_hash[:7]}] 버전으로 복원 완료!", title="Restore");
        self.refresh_all()

    def action_forget_file(self) -> None:
        if self.is_forget_pending:
            with self.conn:
                self.conn.execute("DELETE FROM commits WHERE file_path = ?", (str(self.filepath),)); self.exit(
                    message=f"'{self.filepath.name}'의 모든 이력을 삭제했습니다.")
        else:
            self.notify("정말로 삭제하시려면 5초 안에 'F'를 다시 누르세요.", severity="error", timeout=5);
            self.is_forget_pending = True;
            self.set_timer(5, self.cancel_forget)

    def cancel_forget(self) -> None:
        if self.is_forget_pending: self.is_forget_pending = False; self.notify("삭제가 취소되었습니다.")

    def action_refresh_status(self) -> None:
        self.refresh_all(); self.notify("상태를 새로고침했습니다.", title="Refresh")


# --- Click CLI ---
@click.group()
def cli(): pass


@cli.command()
def init():
    setup_repo()
    click.echo(f"✅ filegit 시스템이 초기화되었습니다: {FILEGIT_DIR}")


@cli.command(help="파일의 타임라인 대시보드를 엽니다.")
@click.argument('filepath', type=click.Path(exists=True, resolve_path=True))
def timeline(filepath):
    DashboardApp(Path(filepath)).run()


# --- 데몬 및 워치리스트 관리 명령어 ---
def get_watchlist() -> set:
    if not WATCHLIST_PATH.exists(): return set()
    with open(WATCHLIST_PATH, 'r') as f:
        try:
            return set(json.load(f))
        except json.JSONDecodeError:
            return set()


def save_watchlist(watchlist: set):
    with open(WATCHLIST_PATH, 'w') as f:
        json.dump(list(watchlist), f, indent=2)


@cli.command()
@click.argument('filepath', type=click.Path(exists=True, resolve_path=True))
def watch(filepath):
    """파일을 자동 감시 목록에 추가합니다."""
    abs_path = str(Path(filepath).resolve());
    FILEGIT_DIR.mkdir(exist_ok=True)
    watchlist = get_watchlist()
    if abs_path not in watchlist:
        watchlist.add(abs_path);
        save_watchlist(watchlist)
        click.echo(f"✅ '{Path(filepath).name}'을(를) 감시 목록에 추가했습니다. 데몬을 재시작하세요.")
    else:
        click.echo(f"이미 감시 중인 파일입니다.")


@cli.command()
@click.argument('filepath', type=click.Path(resolve_path=True))
def unwatch(filepath):
    """파일을 자동 감시 목록에서 제거합니다."""
    abs_path = str(Path(filepath).resolve());
    watchlist = get_watchlist()
    if abs_path in watchlist:
        watchlist.remove(abs_path);
        save_watchlist(watchlist)
        click.echo(f"🗑️ '{Path(filepath).name}'을(를) 감시 목록에서 제거했습니다. 데몬을 재시작하세요.")
    else:
        click.echo(f"감시 목록에 없는 파일입니다.")


@cli.command(name="watch-list")
def watch_list():
    """현재 감시중인 파일 목록을 보여줍니다."""
    watchlist = get_watchlist()
    if not watchlist: click.echo("감시중인 파일이 없습니다."); return
    click.echo("--- 감시중인 파일 ---")
    for file in sorted(list(watchlist)): click.echo(file)


@cli.command(name="daemon-start")
def daemon_start():
    """filegit 자동 감시 데몬을 백그라운드에서 시작합니다."""
    # 데몬이 이미 실행 중인지 확인
    if PID_FILE_PATH.exists():
        click.echo("데몬이 이미 실행 중인 것 같습니다. 먼저 'daemon-stop'을 실행하세요.");
        return

    # 로그 파일 스트림 열기
    log_file = open(LOG_FILE_PATH, 'w+')

    # 데몬 컨텍스트 설정
    daemon_context = DaemonContext(
        working_directory=str(FILEGIT_DIR),
        umask=0o002,
        pidfile=PIDLockFile(PID_FILE_PATH),
        stdout=log_file,
        stderr=log_file,
    )

    click.echo("데몬을 시작합니다... (로그: ~/.filegit/daemon.log)")
    try:
        with daemon_context:
            # 데몬 프로세스 안에서 데몬 스크립트의 메인 함수를 실행
            from filegit_daemon import run_daemon
            run_daemon()
    except Exception as e:
        click.echo(f"데몬 시작 실패: {e}", err=True)


@cli.command(name="daemon-stop")
def daemon_stop():
    """filegit 자동 감시 데몬을 종료합니다."""
    if not PID_FILE_PATH.exists():
        click.echo("데몬이 실행 중이지 않습니다.");
        return

    try:
        with open(PID_FILE_PATH, 'r') as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        click.echo("PID 파일을 읽을 수 없습니다. 직접 프로세스를 확인하세요.");
        return

    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"데몬(PID: {pid})에 종료 신호를 보냈습니다.")
    except ProcessLookupError:
        click.echo(f"프로세스(PID: {pid})를 찾을 수 없습니다. PID 파일을 정리합니다.")
        os.remove(PID_FILE_PATH)
    except Exception as e:
        click.echo(f"데몬 종료 중 오류 발생: {e}", err=True)


@cli.command(name="daemon-status")
def daemon_status():
    """데몬의 실행 상태와 로그를 보여줍니다."""
    if not PID_FILE_PATH.exists():
        click.echo("🔴 데몬이 실행 중이지 않습니다.");
        return

    try:
        with open(PID_FILE_PATH, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # 신호를 보내 프로세스가 살아있는지 확인
        click.echo(f"🟢 데몬이 실행 중입니다. (PID: {pid})")

        if LOG_FILE_PATH.exists():
            click.echo("\n--- 최신 로그 (daemon.log) ---")
            with open(LOG_FILE_PATH, 'r') as log:
                # 마지막 10줄만 보여주기
                lines = log.readlines()
                for line in lines[-10:]:
                    click.echo(line.strip())

    except (OSError, ValueError):
        click.echo("🟡 데몬이 비정상적으로 종료된 것 같습니다. PID 파일을 정리하세요. ('daemon-stop' 실행)")


if __name__ == '__main__':
    # 메인 CLI에 모든 명령어 등록
    cli.add_command(init)
    cli.add_command(timeline)
    cli.add_command(watch)
    cli.add_command(unwatch)
    cli.add_command(watch_list)
    cli.add_command(daemon_start)
    cli.add_command(daemon_stop)
    cli.add_command(daemon_status)
    cli()