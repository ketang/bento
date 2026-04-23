"""Standalone bugshot review workflow."""

from __future__ import annotations

import datetime
import json
import os
import select
import sqlite3
import sys
import time
import webbrowser
from dataclasses import dataclass

import gallery_server

DEFAULT_BIND_ADDRESS = "0.0.0.0"
LOOPBACK_BIND_ADDRESS = "127.0.0.1"
DEFAULT_BROWSER_OPEN_ENABLED = False
DEFAULT_POLL_INTERVAL_SECONDS = 0.2
ISSUE_DIVIDER = "------------------------------------------------------------"
NEGATIVE_RESPONSES = {"n", "no"}


class ShellIO:
    """Shell-facing input and output adapter."""

    def __init__(
        self,
        input_stream=None,
        output_stream=None,
        error_stream=None,
        json_output: bool = False,
    ):
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self.error_stream = error_stream or sys.stderr
        self.json_output = json_output

    def write(self, message: str = "") -> None:
        stream = self.error_stream if self.json_output else self.output_stream
        stream.write(f"{message}\n")
        stream.flush()

    def write_json(self, payload: object) -> None:
        self.output_stream.write(json.dumps(payload) + "\n")
        self.output_stream.flush()

    def write_error(self, message: str) -> None:
        self.error_stream.write(f"{message}\n")
        self.error_stream.flush()

    def prompt(self, message: str) -> str:
        self.output_stream.write(message)
        self.output_stream.flush()
        response = self.input_stream.readline()
        if response == "":
            return ""
        return response.strip()

    def confirm(self, message: str, default: bool = True) -> bool:
        response = self.prompt(message).strip().lower()
        if not response:
            return default
        return response not in NEGATIVE_RESPONSES


@dataclass
class ReviewSummary:
    draft_count: int
    drafts: list[dict[str, str]]


def run_review_session(
    screenshot_dir: str,
    io: ShellIO,
    bind_address: str = DEFAULT_BIND_ADDRESS,
    open_browser: bool = DEFAULT_BROWSER_OPEN_ENABLED,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    json_output: bool = False,
) -> int:
    try:
        server = gallery_server.create_server(screenshot_dir, bind_address=bind_address)
    except ValueError as error:
        io.write_error(str(error))
        return 1

    try:
        io.write(f"Gallery is running at {server.url}")
        if open_browser:
            browser_opened = webbrowser.open(server.url)
            if not browser_opened:
                io.write(f"Open this URL in your browser: {server.url}")

        io.write(
            "Bugshot gallery is open. Review the screenshots, type comments on any issues "
            "you see, then click \"Done Reviewing\" when finished."
        )

        _wait_for_completion(server.db_path, io, poll_interval_seconds)
        comments = _fetch_comments(server.db_path)
        summary = _process_comments(
            comments,
            os.path.abspath(screenshot_dir),
            io,
            json_output=json_output,
        )
        io.write(f"Bugshot session complete. Produced {summary.draft_count} issue drafts.")
        if json_output:
            io.write_json({
                "draft_count": summary.draft_count,
                "drafts": summary.drafts,
            })
        return 0
    finally:
        server.shutdown()
        if os.path.exists(server.db_path):
            os.unlink(server.db_path)


def _wait_for_completion(db_path: str, io: ShellIO, poll_interval_seconds: float) -> str | None:
    while True:
        done, reason = _read_session_state(db_path)
        if done:
            return reason
        time.sleep(poll_interval_seconds)
        if _terminal_input_is_ready(io):
            user_line = io.prompt("")
            if user_line.strip().lower() == "done":
                return "terminal"


def _read_session_state(db_path: str) -> tuple[bool, str | None]:
    """Read session state directly from SQLite, applying heartbeat timeout."""
    conn = sqlite3.connect(db_path)
    try:
        rows = {
            key: value
            for key, value in conn.execute("SELECT key, value FROM session").fetchall()
        }
    finally:
        conn.close()

    done = rows.get("done") == "true"
    reason = rows.get("done_reason") or None

    if not done:
        last_heartbeat = rows.get("last_heartbeat")
        if last_heartbeat:
            try:
                last_hb = datetime.datetime.fromisoformat(last_heartbeat)
                elapsed = (datetime.datetime.now() - last_hb).total_seconds()
                if elapsed > gallery_server.HEARTBEAT_TIMEOUT_SECONDS:
                    return True, "timeout"
            except (ValueError, TypeError):
                pass

    return done, reason


def _terminal_input_is_ready(io: ShellIO) -> bool:
    if not hasattr(io.input_stream, "isatty") or not io.input_stream.isatty():
        return False
    if not hasattr(io.input_stream, "fileno"):
        return False

    ready_streams, _, _ = select.select([io.input_stream], [], [], 0)
    return bool(ready_streams)


def _fetch_comments(db_path: str) -> list[dict[str, object]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, image, body, created_at FROM comments ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _process_comments(
    comments: list[dict[str, object]],
    screenshot_dir: str,
    io: ShellIO,
    json_output: bool = False,
) -> ReviewSummary:
    if not comments:
        io.write("No comments were submitted.")
        return ReviewSummary(draft_count=0, drafts=[])

    drafts: list[dict[str, str]] = []

    for comment in comments:
        image_name = comment["image"]
        image_path = os.path.join(screenshot_dir, image_name)
        user_comment = comment["body"]

        drafts.append({
            "image_name": image_name,
            "image_path": image_path,
            "user_comment": user_comment,
        })

        if not json_output:
            io.write("")
            io.write(ISSUE_DIVIDER)
            io.write(f"Image name: {image_name}")
            io.write(f"Image path: {image_path}")
            io.write(f"User comment: {user_comment}")
            io.write("")

    return ReviewSummary(draft_count=len(drafts), drafts=drafts)
