#!/usr/bin/env python3
"""作業記録ワークフローの画面と API（Python 標準ライブラリのみ）

実行の中身は pipeline.py。ここは画面の配信と、Run の一覧・詳細・承認などの API だけを持つ。
"""
import json
import os
import re
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pipeline

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
HOST = os.environ.get("WORKLOG_HOST", "127.0.0.1")
PORT = int(os.environ.get("WORKLOG_PORT", "8090"))
MAX_BODY = 1_000_000

RUN_PATH = re.compile(r"/api/runs/(\d+)(?:/(inputs|preview|approve|cancel|rerun))?")


class Handler(BaseHTTPRequestHandler):
    server_version = "worklog/2.0"

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/workflow":
            wf = pipeline.load_workflow()
            return self.send(200, {"name": wf["name"], "schedule": wf.get("on", {}).get("schedule"), "steps": wf["steps"]})
        if path == "/api/runs":
            return self.send(200, pipeline.list_runs())
        m = RUN_PATH.fullmatch(path)
        if m and not m.group(2):
            run = pipeline.load_run(m.group(1))
            if run is None:
                return self.send(404, {"error": "Run が見つかりません"})
            run["readme_has_date"] = pipeline.readme_has(run["date"])
            return self.send(200, run)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # 他サイトのフォームから勝手に送信されないよう、独自ヘッダーと JSON を必須にする
        if self.headers.get("X-Worklog") != "1" or \
                not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.send(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send(400, {"error": "JSON が不正です"})

        path = urlparse(self.path).path
        try:
            if path == "/api/runs":
                try:
                    day = date.fromisoformat(body.get("date") or date.today().isoformat())
                except ValueError:
                    return self.send(400, {"error": "日付の形式が正しくありません"})
                return self.send(200, pipeline.trigger_run(day, "manual"))
            m = RUN_PATH.fullmatch(path)
            if not m or not m.group(2):
                return self.send(404, {"error": "not found"})
            run_id, action = m.group(1), m.group(2)
            inputs = body.get("inputs") or {}
            if action == "inputs":
                return self.send(200, pipeline.save_inputs(run_id, inputs))
            if action == "preview":
                run = pipeline.load_run(run_id)
                if run is None:
                    return self.send(404, {"error": "Run が見つかりません"})
                return self.send(200, {"markdown": pipeline.build_draft(run, inputs)})
            if action == "approve":
                return self.send(200, pipeline.approve(run_id, inputs, body.get("markdown", ""), bool(body.get("force"))))
            if action == "cancel":
                return self.send(200, pipeline.cancel(run_id))
            if action == "rerun":
                return self.send(200, pipeline.rerun_failed(run_id))
        except pipeline.Conflict as e:
            return self.send(409, {"error": str(e)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    pipeline.load_workflow()  # 定義の誤りは起動時に気づけるようにする
    print(f"worklog: http://{HOST}:{PORT}/  (repo: {pipeline.REPO}, runs: {pipeline.RUNS})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
