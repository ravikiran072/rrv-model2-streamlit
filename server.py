"""Local Model 2 scenario and expert elicitation server.

Place behind an institution-managed HTTPS and authentication proxy before
exposing beyond localhost. The application intentionally has no login system.
"""
import csv
import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from model_engine import run

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("RRV_DB", ROOT / "expert_inputs.sqlite3"))
FIELDS = {
    "observed_event_interval", "detection_probability", "establishment_probability",
    "receptivity_cutoff", "receipt_cutoff", "long_haul_share", "long_haul_distance",
    "route_scope", "origin_destination_weights", "spread_speed", "water_barriers",
    "event_timing", "new_source_feedback", "burden_scaling",
}


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB)) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_utc TEXT NOT NULL,
            name TEXT NOT NULL,
            organization TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            comments TEXT NOT NULL
        )""")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, mime="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, allow_nan=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if mime.startswith("application/json") else "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 100_000:
            raise ValueError("Request body must be 1–100,000 bytes")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlsplit(self.path).path
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/map_style.js": ("map_style.js", "text/javascript; charset=utf-8"),
                 "/model_info.json": ("model_info.json", "application/json; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/methods.html": ("methods.html", "text/html; charset=utf-8"),
                 "/counties.svg": ("counties.svg", "image/svg+xml"),
                 "/county_names.json": ("county_names.json", "application/json; charset=utf-8")}
        if path in files:
            filename, mime = files[path]
            self.respond(200, (ROOT / filename).read_bytes(), mime)
        elif path == "/api/submissions.csv":
            admin_token = os.environ.get("RRV_ADMIN_TOKEN")
            if admin_token and self.headers.get("Authorization") != "Bearer " + admin_token:
                self.respond(403, {"error": "Administrator token required"})
                return
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["id", "created_utc", "name", "organization", "parameter", "central", "low", "high", "evidence", "comments"])
            with closing(sqlite3.connect(DB)) as con, con:
                for row in con.execute("SELECT id,created_utc,name,organization,inputs_json,comments FROM submissions ORDER BY id"):
                    ident, created, name, org, inputs, comments = row
                    for parameter, values in json.loads(inputs).items():
                        writer.writerow([ident, created, name, org, parameter, values.get("central", ""),
                                         values.get("low", ""), values.get("high", ""), values.get("evidence", ""), comments])
            self.respond(200, out.getvalue(), "text/csv; charset=utf-8")
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        try:
            payload = self.payload()
            if urlsplit(self.path).path == "/api/scenario":
                self.respond(200, run(payload))
            elif urlsplit(self.path).path == "/api/submissions":
                if not isinstance(payload, dict):
                    raise ValueError("Submission must be an object")
                name = str(payload.get("name", ""))[:120]
                org = str(payload.get("organization", ""))[:160]
                comments = str(payload.get("comments", ""))[:4000]
                entries = payload.get("inputs")
                if not isinstance(entries, dict) or not entries or set(entries) - FIELDS:
                    raise ValueError("Select at least one recognized parameter")
                clean = {}
                for key, item in entries.items():
                    if not isinstance(item, dict):
                        raise ValueError(f"Invalid entry for {key}")
                    clean[key] = {k: str(item.get(k, ""))[:2000] for k in ("central", "low", "high", "evidence")}
                    if not clean[key]["central"]:
                        raise ValueError(f"Central estimate required for {key}")
                with closing(sqlite3.connect(DB)) as con, con:
                    cur = con.execute("INSERT INTO submissions(created_utc,name,organization,inputs_json,comments) VALUES (?,?,?,?,?)",
                                      (datetime.now(timezone.utc).isoformat(), name, org, json.dumps(clean), comments))
                self.respond(201, {"id": cur.lastrowid, "saved": True})
            else:
                self.respond(404, {"error": "Not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception as exc:
            self.log_error("Request failed: %s", exc)
            self.respond(500, {"error": "Server error"})


if __name__ == "__main__":
    initialize()
    host = os.environ.get("RRV_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    print(f"Model 2 available at http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
