#!/usr/bin/env python3
"""作業記録まとめツール（Python 標準ライブラリのみで動く小さな Web サーバー）

コマンド履歴・apt のインストール履歴・Nginx 設定・エラーログを集めて
ブラウザ上で作業記録の下書きを作り、README.md に追記してコミットする。
"""
import glob
import gzip
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("WORKLOG_REPO", str(HERE.parent)))
README = REPO / "README.md"
INDEX = HERE / "index.html"
HISTFILE = Path(os.environ.get("WORKLOG_HISTFILE", str(Path.home() / ".bash_history")))
NGINX_CONF = Path(os.environ.get("WORKLOG_NGINX_CONF", "/etc/nginx/sites-available/default"))
HOST = os.environ.get("WORKLOG_HOST", "127.0.0.1")
PORT = int(os.environ.get("WORKLOG_PORT", "8090"))

SECTION = "## 作業記録"
TRIVIAL = re.compile(r"^\s*(ls|ll|la|cd|pwd|clear|exit|history|echo|cat|less|man)\b")
MAX_BODY = 1_000_000


def run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def read_text(path):
    path = str(path)
    if path.endswith(".gz"):
        with gzip.open(path, "rt", errors="replace") as f:
            return f.read()
    with open(path, errors="replace") as f:
        return f.read()


# ---------- 収集 ----------

def history_entries():
    """~/.bash_history を読む。HISTTIMEFORMAT が有効なら '#<epoch>' 行が直前に入る。"""
    try:
        text = read_text(HISTFILE)
    except OSError:
        return []
    entries, ts = [], None
    for line in text.splitlines():
        m = re.fullmatch(r"#(\d{9,11})", line)
        if m:
            ts = int(m.group(1))
            continue
        if line.strip():
            entries.append((ts, line))
        ts = None
    return entries


def commands_for(day):
    dated, undated = [], []
    for ts, cmd in history_entries():
        item = {"cmd": cmd, "trivial": bool(TRIVIAL.match(cmd))}
        if ts is None:
            undated.append(item)
            continue
        dt = datetime.fromtimestamp(ts)
        if dt.date() == day:
            item["time"] = dt.strftime("%H:%M")
            dated.append(item)
    return dated, undated[-300:]


PKG_RE = re.compile(r"([a-z0-9][a-z0-9+.\-]*)(?::[a-z0-9]+)? \(([^)]*)\)")


def parse_pkgs(field):
    manual, auto = [], 0
    for name, inner in PKG_RE.findall(field or ""):
        if "automatic" in inner:
            auto += 1
        else:
            manual.append({"name": name, "version": inner.split(",")[0].strip()})
    return manual, auto


def apt_events(day):
    events = []
    prefix = day.isoformat()
    for f in sorted(glob.glob("/var/log/apt/history.log*")):
        try:
            text = read_text(f)
        except OSError:
            continue
        for block in text.split("\n\n"):
            fields = {}
            for line in block.strip().splitlines():
                key, _, val = line.partition(": ")
                fields[key] = val
            start = fields.get("Start-Date", "")
            if not start.startswith(prefix):
                continue
            ev = {"time": start.split()[-1][:5], "command": fields.get("Commandline", "")}
            for key in ("Install", "Remove", "Purge"):
                manual, auto = parse_pkgs(fields.get(key))
                if manual or auto:
                    ev[key.lower()] = {"packages": manual, "automatic": auto}
            if "Upgrade" in fields:
                ev["upgrade"] = len(PKG_RE.findall(fields["Upgrade"]))
            events.append(ev)
    events.sort(key=lambda e: e["time"])
    return events


def versions():
    rows = []
    try:
        for line in read_text("/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                rows.append({"name": "OS", "version": line.split("=", 1)[1].strip('"')})
    except OSError:
        pass
    _, out, _ = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Status}\n",
                     "nginx", "tomcat*", "openjdk-*-jdk-headless", "openjdk-*-jre-headless"])
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == "installed":
            rows.append({"name": parts[0], "version": parts[1]})
    return rows


def nginx_conf():
    try:
        text = read_text(NGINX_CONF)
    except OSError as e:
        return {"path": str(NGINX_CONF), "content": "", "error": str(e)}
    lines = [l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    return {"path": str(NGINX_CONF), "content": "\n".join(lines)}


def nginx_errors(day):
    pat = day.strftime("%Y/%m/%d")
    lines = []
    for f in glob.glob("/var/log/nginx/error.log*"):
        try:
            lines += [l for l in read_text(f).splitlines() if l.startswith(pat)]
        except OSError:
            continue
    return sorted(lines)[-100:]


def tomcat_errors(day):
    _, out, _ = run(["journalctl", "-u", "tomcat10", "--no-pager", "-q", "-o", "short-iso",
                     "--since", day.isoformat(), "--until", (day + timedelta(days=1)).isoformat()])
    hits = [l for l in out.splitlines() if re.search(r"SEVERE|WARN|Exception|Error|Failed", l)]
    return hits[-100:]


def collect(day):
    dated, undated = commands_for(day)
    return {
        "date": day.isoformat(),
        "commands": dated,
        "undated": undated,
        "apt": apt_events(day),
        "versions": versions(),
        "nginx": nginx_conf(),
        "errors": {"nginx": nginx_errors(day), "tomcat": tomcat_errors(day)},
        "histfile": str(HISTFILE),
    }


# ---------- 保存・コミット ----------

def save(day, markdown, force=False):
    markdown = markdown.strip()
    if not markdown:
        return 400, {"error": "下書きが空です"}
    text = README.read_text() if README.exists() else ""
    heading = f"### {day.isoformat()}"
    if not force and any(l.startswith(heading) for l in text.splitlines()):
        return 409, {"error": f"README に {day.isoformat()} の記録がすでにあります"}
    if text and not text.endswith("\n"):
        text += "\n"
    if SECTION not in text.splitlines():
        text += f"\n{SECTION}\n"
    text += "\n" + markdown + "\n"
    README.write_text(text)
    return 200, {"ok": True, "message": "README.md に追記しました"}


def git(*args):
    return run(["git", "-C", str(REPO), *args])


def status():
    _, st, _ = git("status", "--short")
    _, log, _ = git("log", "--oneline", "-5")
    return {"status": st, "log": log}


def commit(message):
    message = message.strip()
    if not message:
        return 400, {"error": "コミットメッセージを入力してください"}
    git("add", "README.md")
    code, _, _ = git("diff", "--cached", "--quiet")
    if code == 0:
        return 409, {"error": "コミットする変更がありません"}
    code, out, err = git("commit", "-m", message)
    if code != 0:
        return 500, {"error": (err or out).strip()}
    return 200, {"ok": True, "message": out.strip().splitlines()[0]}


# ---------- HTTP ----------

def parse_day(value):
    try:
        return date.fromisoformat(value) if value else date.today()
    except ValueError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "worklog/1.0"

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self.send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/collect":
            day = parse_day(parse_qs(url.query).get("date", [""])[0])
            if day is None:
                return self.send(400, {"error": "日付の形式が正しくありません"})
            return self.send(200, collect(day))
        if url.path == "/api/status":
            return self.send(200, status())
        self.send(404, {"error": "not found"})

    def do_HEAD(self):
        # curl -I での確認用。本文を送らずにヘッダーだけ返す
        url = urlparse(self.path)
        ok = url.path in ("/", "/index.html")
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8" if ok else "application/json; charset=utf-8")
        self.end_headers()

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
        if path == "/api/save":
            day = parse_day(body.get("date"))
            if day is None:
                return self.send(400, {"error": "日付の形式が正しくありません"})
            return self.send(*save(day, body.get("markdown", ""), bool(body.get("force"))))
        if path == "/api/commit":
            return self.send(*commit(body.get("message", "")))
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"worklog: http://{HOST}:{PORT}/  (repo: {REPO})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
