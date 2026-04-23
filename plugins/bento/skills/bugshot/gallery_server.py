"""Bugshot gallery server.

Usage: python3 gallery_server.py /path/to/screenshots [--bind ADDRESS | --local-only]
"""

import argparse
import atexit
import json
import os
import sqlite3
import sys
import tempfile
import threading
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ANSI_EXTENSION = ".ansi"
RECOGNIZED_EXTENSIONS = IMAGE_EXTENSIONS | {ANSI_EXTENSION}

HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_TIMEOUT_SECONDS = 15


def discover_images(directory):
    """Return sorted list of recognized filenames in directory."""
    names = []
    for name in os.listdir(directory):
        ext = os.path.splitext(name)[1].lower()
        if ext in RECOGNIZED_EXTENSIONS:
            names.append(name)
    names.sort()
    return names


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class GalleryHandler(SimpleHTTPRequestHandler):
    """Routes requests to the appropriate handler."""

    # Set by create_server() before serving
    screenshot_dir = None
    images = None
    db_path = None
    template_dir = None
    static_dir = None

    def log_message(self, format, *args):
        """Suppress request logging for clean output."""
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/" or path == "":
            self._serve_index()
        elif path == "/api/comments":
            self._handle_comment_list(parsed.query)
        elif path.startswith("/view/"):
            filename = path[len("/view/"):]
            self._serve_detail(filename)
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path.startswith("/screenshots/"):
            self._serve_screenshot(path[len("/screenshots/"):])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/api/comments":
            self._handle_comment_create()
        elif path == "/api/heartbeat":
            self._handle_heartbeat()
        elif path == "/api/done":
            self._handle_done()
        elif path == "/api/closed":
            self._handle_closed()
        else:
            self.send_error(404)

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path.startswith("/api/comments/"):
            comment_id = path[len("/api/comments/"):]
            self._handle_comment_update(comment_id)
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path.startswith("/api/comments/"):
            comment_id = path[len("/api/comments/"):]
            self._handle_comment_delete(comment_id)
        else:
            self.send_error(404)

    # -- Page handlers --

    def _serve_index(self):
        template_path = os.path.join(self.template_dir, "index.html")
        with open(template_path, "r") as f:
            template = f.read()

        image_items = []
        for name in self.images:
            ext = os.path.splitext(name)[1].lower()
            encoded_name = urllib.parse.quote(name)
            if ext == ANSI_EXTENSION:
                from ansi_render import ansi_to_html
                ansi_path = os.path.join(self.screenshot_dir, name)
                with open(ansi_path, "r") as f:
                    ansi_content = f.read()
                rendered_html = ansi_to_html(ansi_content)
                image_items.append({
                    "name": name,
                    "encoded_name": encoded_name,
                    "type": "ansi",
                    "preview_html": rendered_html,
                })
            else:
                image_items.append({
                    "name": name,
                    "encoded_name": encoded_name,
                    "type": "image",
                    "src": f"/screenshots/{encoded_name}",
                })

        content = template.replace("{{images_json}}", json.dumps(image_items))
        self._send_html(content)

    def _serve_detail(self, filename):
        if filename not in self.images:
            self.send_error(404, f"Image not found: {filename}")
            return

        template_path = os.path.join(self.template_dir, "detail.html")
        with open(template_path, "r") as f:
            template = f.read()

        idx = self.images.index(filename)
        prev_name = self.images[idx - 1] if idx > 0 else None
        next_name = self.images[idx + 1] if idx < len(self.images) - 1 else None

        ext = os.path.splitext(filename)[1].lower()
        encoded_name = urllib.parse.quote(filename)

        if ext == ANSI_EXTENSION:
            from ansi_render import ansi_to_html
            ansi_path = os.path.join(self.screenshot_dir, filename)
            with open(ansi_path, "r") as f:
                ansi_content = f.read()
            rendered_html = ansi_to_html(ansi_content)
            content_type = "ansi"
            image_src = ""
        else:
            rendered_html = ""
            content_type = "image"
            image_src = f"/screenshots/{encoded_name}"

        nav = {
            "prev": f"/view/{urllib.parse.quote(prev_name)}" if prev_name else None,
            "next": f"/view/{urllib.parse.quote(next_name)}" if next_name else None,
            "prev_name": prev_name,
            "next_name": next_name,
        }
        detail_images = [
            {
                "name": image_name,
                "encoded_name": urllib.parse.quote(image_name),
            }
            for image_name in self.images
        ]

        replacements = {
            "{{filename}}": filename,
            "{{content_type}}": content_type,
            "{{image_src}}": image_src,
            "{{ansi_html}}": rendered_html,
            "{{nav_json}}": json.dumps(nav),
            "{{images_json}}": json.dumps(detail_images),
            "{{encoded_name}}": encoded_name,
        }
        content = template
        for key, value in replacements.items():
            content = content.replace(key, value)

        self._send_html(content)

    def _serve_static(self, filename):
        safe_name = os.path.basename(filename)
        filepath = os.path.join(self.static_dir, safe_name)
        if not os.path.isfile(filepath):
            self.send_error(404)
            return

        ext = os.path.splitext(safe_name)[1].lower()
        content_types = {
            ".css": "text/css",
            ".js": "application/javascript",
        }
        ctype = content_types.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_screenshot(self, filename):
        safe_name = os.path.basename(urllib.parse.unquote(filename))
        filepath = os.path.join(self.screenshot_dir, safe_name)
        if not os.path.isfile(filepath):
            self.send_error(404)
            return

        ext = os.path.splitext(safe_name)[1].lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        ctype = content_types.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- API handlers --

    def _handle_comment_list(self, query):
        params = urllib.parse.parse_qs(query)
        image = params.get("image", [None])[0]

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if image:
                rows = conn.execute(
                    "SELECT id, image, body, created_at FROM comments "
                    "WHERE image = ? ORDER BY id",
                    (image,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, image, body, created_at FROM comments ORDER BY id"
                ).fetchall()
        finally:
            conn.close()

        self._send_json([dict(row) for row in rows])

    def _handle_comment_create(self):
        data = self._read_json_body()
        image = data.get("image")
        body = data.get("body")
        if not image or not body:
            self._send_json({"error": "image and body are required"}, status=400)
            return

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "INSERT INTO comments (image, body) VALUES (?, ?)",
            (image, body),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, image, body, created_at FROM comments WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        conn.close()
        self._send_json(dict(row))

    def _handle_comment_update(self, comment_id):
        data = self._read_json_body()
        body = data.get("body")
        if not body:
            self._send_json({"error": "body is required"}, status=400)
            return

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "UPDATE comments SET body = ? WHERE id = ?",
            (body, comment_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, image, body, created_at FROM comments WHERE id = ?",
            (comment_id,),
        ).fetchone()
        conn.close()

        if row is None:
            self._send_json({"error": "not found"}, status=404)
            return
        self._send_json(dict(row))

    def _handle_comment_delete(self, comment_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
        conn.close()

        if cursor.rowcount == 0:
            self._send_json({"error": "not found"}, status=404)
            return

        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_heartbeat(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE session SET value = datetime('now') WHERE key = 'last_heartbeat'"
        )
        conn.commit()
        conn.close()
        self._send_json({"ok": True})

    def _handle_done(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE session SET value = 'true' WHERE key = 'done'")
        conn.execute("UPDATE session SET value = 'button' WHERE key = 'done_reason'")
        conn.commit()
        conn.close()
        self._send_json({"ok": True})

    def _handle_closed(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE session SET value = 'true' WHERE key = 'done'")
        conn.execute("UPDATE session SET value = 'closed' WHERE key = 'done_reason'")
        conn.commit()
        conn.close()
        self._send_json({"ok": True})

    # -- Helpers --

    def _send_html(self, content):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)


def init_db(db_path):
    """Initialize the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("INSERT OR REPLACE INTO session VALUES ('done', 'false')")
    conn.execute("INSERT OR REPLACE INTO session VALUES ('done_reason', '')")
    conn.execute(
        "INSERT OR REPLACE INTO session VALUES ('last_heartbeat', datetime('now'))"
    )
    conn.commit()
    conn.close()


class GalleryServer:
    """Running gallery server. Holds httpd, serving thread, and resources."""

    def __init__(self, httpd, thread, url, db_path, images, screenshot_dir):
        self.httpd = httpd
        self.thread = thread
        self.url = url
        self.db_path = db_path
        self.images = images
        self.screenshot_dir = screenshot_dir

    def shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def create_server(screenshot_dir, bind_address="0.0.0.0"):
    """Create and start a gallery server in a background thread.

    Returns a GalleryServer. Raises ValueError on invalid directory or no images.
    """
    directory = os.path.abspath(screenshot_dir)
    if not os.path.isdir(directory):
        raise ValueError(f"Not a directory: {directory}")

    images = discover_images(directory)
    if not images:
        raise ValueError(f"No recognized images in: {directory}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(script_dir, "templates")
    static_dir = os.path.join(script_dir, "static")

    db_fd, db_path = tempfile.mkstemp(prefix="bugshot_", suffix=".db")
    os.close(db_fd)
    init_db(db_path)

    handler_cls = type("BoundGalleryHandler", (GalleryHandler,), {
        "screenshot_dir": directory,
        "images": images,
        "db_path": db_path,
        "template_dir": template_dir,
        "static_dir": static_dir,
    })

    httpd = ThreadingHTTPServer((bind_address, 0), handler_cls)
    port = httpd.server_address[1]
    url = f"http://{bind_address}:{port}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    return GalleryServer(httpd, thread, url, db_path, images, directory)


def main():
    parser = argparse.ArgumentParser(description="Bugshot gallery server")
    parser.add_argument("directory", help="Path to screenshot directory")
    bind_group = parser.add_mutually_exclusive_group()
    bind_group.add_argument(
        "--bind", default="0.0.0.0",
        help="Address to bind to (default: 0.0.0.0, all interfaces)",
    )
    bind_group.add_argument(
        "--local-only", action="store_true",
        help="Shortcut for --bind 127.0.0.1 (loopback only)",
    )
    args = parser.parse_args()

    bind_address = "127.0.0.1" if args.local_only else args.bind

    try:
        server = create_server(args.directory, bind_address=bind_address)
    except ValueError as error:
        print(json.dumps({"error": str(error)}), flush=True)
        sys.exit(1)

    atexit.register(
        lambda: os.unlink(server.db_path) if os.path.exists(server.db_path) else None
    )

    print(json.dumps({
        "port": server.httpd.server_address[1],
        "url": server.url,
        "images": server.images,
    }), flush=True)

    try:
        server.thread.join()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
