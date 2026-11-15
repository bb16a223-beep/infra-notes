#!/usr/bin/env python3
"""作業記録ワークフローの実行エンジン（GitHub Actions 風）

workflow.toml のステップを順に実行し、実行結果（Run）を runs/ に JSON で残す。

  python3 pipeline.py run [--date YYYY-MM-DD]   手動で1回実行する
  python3 pipeline.py schedule                  タイマーから呼ぶ。予定時刻を過ぎた未実行の日を実行する
"""
import argparse
import contextlib
import difflib
import fcntl
import glob
import gzip
import json
import os
import re
import subprocess
import tomllib
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("WORKLOG_REPO", str(HERE.parent)))
README = REPO / "README.md"
RUNS = Path(os.environ.get("WORKLOG_RUNS", str(HERE / "runs")))
WORKFLOW = HERE / "workflow.toml"
HISTFILE = Path(os.environ.get("WORKLOG_HISTFILE", str(Path.home() / ".bash_history")))
NGINX_CONF = Path(os.environ.get("WORKLOG_NGINX_CONF", "/etc/nginx/sites-available/default"))

SECTION = "## 作業記録"
TRIVIAL = re.compile(r"^\s*(ls|ll|la|cd|pwd|clear|exit|history|echo|cat|less|man)\b")
BACKFILL_DAYS = 7


class StepError(Exception):
    """ステップの失敗。メッセージがログに残る"""


class Conflict(Exception):
    """操作できない状態（承認待ちでない Run を承認した など）"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def run_cmd(args, timeout=15, cwd=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
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


# ---------- ワークフロー定義 ----------

def load_workflow():
    with open(WORKFLOW, "rb") as f:
        wf = tomllib.load(f)
    seen = set()
    for s in wf["steps"]:
        s.setdefault("needs", [])
        if s["uses"] not in ACTIONS:
            raise ValueError(f"workflow.toml: 不明な uses です: {s['uses']}")
        for n in s["needs"]:
            if n not in seen:
                raise ValueError(f"workflow.toml: {s['id']} の needs にある {n} は、それより前に定義してください")
        seen.add(s["id"])
    return wf


def schedule_time(wf):
    hh, mm = wf.get("on", {}).get("schedule", "23:00").split(":")
    return time(int(hh), int(mm))


# ---------- Run の保存 ----------

@contextlib.contextmanager
def locked():
    RUNS.mkdir(parents=True, exist_ok=True)
    with open(RUNS / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def run_path(run_id):
    return RUNS / f"{int(run_id):05d}.json"


def save_run(run):
    path = run_path(run["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def load_run(run_id):
    try:
        return json.loads(run_path(run_id).read_text())
    except FileNotFoundError:
        return None


def all_runs():
    runs = []
    for p in sorted(RUNS.glob("[0-9]*.json")):
        try:
            runs.append(json.loads(p.read_text()))
        except ValueError:
            continue
    return runs


def summary(run):
    keys = ("id", "workflow", "date", "trigger", "created", "started", "finished", "status")
    s = {k: run.get(k) for k in keys}
    s["steps"] = [{"id": st["id"], "status": st["status"]} for st in run["steps"]]
    return s


def list_runs():
    return [summary(r) for r in reversed(all_runs())]


# ---------- 実行 ----------

def new_run(day, trigger, wf):
    runs = all_runs()
    run = {
        "id": (runs[-1]["id"] + 1) if runs else 1,
        "workflow": wf["name"],
        "date": day.isoformat(),
        "trigger": trigger,
        "created": now(),
        "started": None,
        "finished": None,
        "status": "queued",
        "steps": [{"id": s["id"], "name": s["name"], "uses": s["uses"], "needs": s["needs"],
                   "status": "pending", "started": None, "finished": None, "log": []}
                  for s in wf["steps"]],
        "outputs": {},
        "inputs": {},
        "draft": "",
    }
    save_run(run)
    return run


def conclude(run):
    statuses = [s["status"] for s in run["steps"]]
    if "failure" in statuses:
        run["status"] = "failure"
    elif "cancelled" in statuses:
        run["status"] = "cancelled"
    elif "waiting" in statuses:
        run["status"] = "waiting"
    elif run.get("no_work"):
        run["status"] = "neutral"
    elif all(s in ("success", "skipped") for s in statuses):
        run["status"] = "success"
    else:
        run["status"] = "running"
    if run["status"] in ("success", "failure", "cancelled", "neutral"):
        run["finished"] = now()


def execute(run):
    """pending のステップを、needs が満たされたものから順に実行する"""
    run["status"] = "running"
    run["started"] = run["started"] or now()
    run["finished"] = None
    save_run(run)
    by_id = {s["id"]: s for s in run["steps"]}
    for step in run["steps"]:
        if step["status"] != "pending":
            continue
        deps = [by_id[n] for n in step["needs"]]
        if run.get("no_work"):
            step["status"] = "skipped"
            step["log"].append("作業がなかったためスキップしました")
            continue
        if any(d["status"] in ("failure", "skipped", "cancelled") for d in deps):
            step["status"] = "skipped"
            step["log"].append("前のステップが完了しなかったためスキップしました")
            continue
        if any(d["status"] != "success" for d in deps):
            continue
        if step["uses"] == "approval":
            step["status"] = "waiting"
            step["started"] = now()
            step["log"].append("承認待ちです。進捗画面で内容を確認して承認してください")
            continue
        step["status"] = "running"
        step["started"] = now()
        save_run(run)
        try:
            out = ACTIONS[step["uses"]](run, step)
            if out is not None:
                run["outputs"][step["id"]] = out
            step["status"] = "success"
        except StepError as e:
            step["status"] = "failure"
            step["log"].append(f"エラー: {e}")
        except Exception as e:  # 想定外の例外もステップの失敗として記録する
            step["status"] = "failure"
            step["log"].append(f"想定外のエラー: {type(e).__name__}: {e}")
        step["finished"] = now()
        save_run(run)
    conclude(run)
    save_run(run)
    return run


def trigger_run(day, trigger="manual"):
    wf = load_workflow()
    with locked():
        return execute(new_run(day, trigger, wf))


def get_waiting(run, uses="approval"):
    if run is None:
        raise Conflict("Run が見つかりません")
    for s in run["steps"]:
        if s["uses"] == uses and s["status"] == "waiting":
            return s
    raise Conflict("この Run は承認待ちではありません")


def save_inputs(run_id, inputs):
    with locked():
        run = load_run(run_id)
        get_waiting(run)
        run["inputs"] = inputs
        save_run(run)
        return run


def readme_has(day):
    if not README.exists():
        return False
    heading = f"### {day}"
    return any(l.startswith(heading) for l in README.read_text().splitlines())


def approve(run_id, inputs, markdown, force=False):
    with locked():
        run = load_run(run_id)
        step = get_waiting(run)
        if not markdown.strip():
            raise Conflict("下書きが空です")
        if not force and readme_has(run["date"]):
            raise Conflict(f"README に {run['date']} の記録がすでにあります")
        run["inputs"] = inputs
        run["draft"] = markdown.strip() + "\n"
        step["status"] = "success"
        step["finished"] = now()
        step["log"].append("承認しました")
        return execute(run)


def cancel(run_id):
    with locked():
        run = load_run(run_id)
        step = get_waiting(run)
        step["status"] = "cancelled"
        step["finished"] = now()
        step["log"].append("キャンセルしました")
        for s in run["steps"]:
            if s["status"] == "pending":
                s["status"] = "skipped"
                s["log"].append("キャンセルされたためスキップしました")
        conclude(run)
        save_run(run)
        return run


def rerun_failed(run_id):
    with locked():
        run = load_run(run_id)
        if run is None or run["status"] != "failure":
            raise Conflict("失敗した Run だけ再実行できます")
        for s in run["steps"]:
            if s["status"] in ("failure", "skipped"):
                s.update(status="pending", started=None, finished=None)
                s["log"].append(f"--- {now()} 再実行 ---")
        return execute(run)


def schedule():
    """予定時刻を過ぎていて、まだ自動実行していない日の Run を作る（PC が止まっていた日も最大7日さかのぼる）"""
    wf = load_workflow()
    at = schedule_time(wf)
    today = date.today()
    created = []
    with locked():
        done = {r["date"] for r in all_runs() if r["trigger"] == "schedule"}
        last = max((date.fromisoformat(d) for d in done), default=today - timedelta(days=1))
        day = max(last + timedelta(days=1), today - timedelta(days=BACKFILL_DAYS))
        while day <= today:
            if day == today and datetime.now().time() < at:
                break
            if day.isoformat() not in done:
                created.append(execute(new_run(day, "schedule", wf)))
            day += timedelta(days=1)
    return created


# ---------- 各ステップの処理（uses） ----------

def day_of(run):
    return date.fromisoformat(run["date"])


def collect_history(run, step):
    try:
        text = read_text(HISTFILE)
    except OSError as e:
        raise StepError(f"{HISTFILE} を読めません: {e}")
    day = day_of(run)
    # 日時付きの区間では「#<epoch>」行の次から、次の「#<epoch>」までが1つのコマンド
    # （\ で改行した複数行のコマンドもまとめて1つとして扱う）
    entries, ts, last = [], None, None
    for line in text.splitlines():
        m = re.fullmatch(r"#(\d{9,11})", line)
        if m:
            ts = int(m.group(1))
            last = None
            continue
        if ts is not None and last is not None:
            last["cmd"] += "\n" + line
            continue
        if line.strip():
            last = {"ts": ts, "cmd": line} if ts is not None else None
            entries.append(last or {"ts": None, "cmd": line})
    dated, undated = [], []
    for e in entries:
        item = {"cmd": e["cmd"], "trivial": bool(TRIVIAL.match(e["cmd"]))}
        if e["ts"] is None:
            undated.append(item)
            continue
        dt = datetime.fromtimestamp(e["ts"])
        if dt.date() == day:
            item["time"] = dt.strftime("%H:%M")
            dated.append(item)
    main = [c for c in dated if not c["trivial"]]
    step["log"].append(f"{HISTFILE} から {run['date']} のコマンドを {len(dated)} 件見つけました（ls・cd などを除くと {len(main)} 件）")
    step["log"] += [f"  {c['time']}  {c['cmd']}" for c in main[:50]]
    if undated:
        step["log"].append(f"日時のない古い履歴が {len(undated)} 件あります（進捗画面で選べます）")
    return {"commands": dated, "undated": undated[-300:]}


PKG_RE = re.compile(r"([a-z0-9][a-z0-9+.\-]*)(?::[a-z0-9]+)? \(([^)]*)\)")


def parse_pkgs(field):
    manual, auto = [], 0
    for name, inner in PKG_RE.findall(field or ""):
        if "automatic" in inner:
            auto += 1
        else:
            manual.append({"name": name, "version": inner.split(",")[0].strip()})
    return manual, auto


def collect_apt(run, step):
    events = []
    files = sorted(glob.glob("/var/log/apt/history.log*"))
    for f in files:
        try:
            text = read_text(f)
        except OSError as e:
            step["log"].append(f"{f} を読めません: {e}")
            continue
        for block in text.split("\n\n"):
            fields = {}
            for line in block.strip().splitlines():
                key, _, val = line.partition(": ")
                fields[key] = val
            start = fields.get("Start-Date", "")
            if not start.startswith(run["date"]):
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
    step["log"].append(f"/var/log/apt/history.log* ({len(files)} ファイル) から {len(events)} 件見つけました")
    step["log"] += apt_lines(events)
    return {"events": events}


def apt_lines(events):
    lines = []
    for ev in events:
        lines.append(f"{ev['time']}  {ev['command']}")
        for key, label in (("install", "インストール"), ("remove", "削除"), ("purge", "完全削除")):
            x = ev.get(key)
            if x:
                names = ", ".join(f"{p['name']} {p['version']}" for p in x["packages"]) or "-"
                auto = f"（依存 {x['automatic']} 件）" if x["automatic"] else ""
                lines.append(f"  {label}: {names}{auto}")
        if ev.get("upgrade"):
            lines.append(f"  アップグレード: {ev['upgrade']} 件")
    return lines


def collect_errors(run, step):
    day = day_of(run)
    pat = day.strftime("%Y/%m/%d")
    nginx = []
    for f in glob.glob("/var/log/nginx/error.log*"):
        try:
            nginx += [l for l in read_text(f).splitlines() if l.startswith(pat)]
        except OSError as e:
            step["log"].append(f"{f} を読めません: {e}")
    code, out, err = run_cmd(["journalctl", "-u", "tomcat10", "--no-pager", "-q", "-o", "short-iso",
                              "--since", day.isoformat(), "--until", (day + timedelta(days=1)).isoformat()])
    if code != 0 and err:
        step["log"].append(f"journalctl の実行に失敗しました: {err.strip()}")
    tomcat = [l for l in out.splitlines() if re.search(r"SEVERE|WARN|Exception|Error|Failed", l)]
    nginx, tomcat = sorted(nginx)[-100:], tomcat[-100:]
    step["log"].append(f"Nginx のエラー {len(nginx)} 件、Tomcat の警告・エラー {len(tomcat)} 件")
    step["log"] += [f"  {l}" for l in (nginx + tomcat)[:30]]
    return {"nginx": nginx, "tomcat": tomcat}


def collect_nginx(run, step):
    try:
        text = read_text(NGINX_CONF)
    except OSError as e:
        raise StepError(f"{NGINX_CONF} を読めません: {e}")
    content = "\n".join(l.rstrip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#"))
    prev = None
    for r in reversed(all_runs()):
        if r["id"] < run["id"] and "nginx" in r.get("outputs", {}):
            prev = r
            break
    diff = []
    if prev is None:
        step["log"].append("初めての記録なので、比較はしません")
    else:
        diff = list(difflib.unified_diff(prev["outputs"]["nginx"]["content"].splitlines(), content.splitlines(),
                                         f"Run #{prev['id']} ({prev['date']})", f"Run #{run['id']} ({run['date']})",
                                         lineterm=""))
        step["log"].append(f"Run #{prev['id']} から {'変更あり' if diff else '変更なし'}")
        step["log"] += diff
    return {"path": str(NGINX_CONF), "content": content, "diff": "\n".join(diff)}


def collect_versions(run, step):
    rows = []
    try:
        for line in read_text("/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                rows.append({"name": "OS", "version": line.split("=", 1)[1].strip('"')})
    except OSError:
        pass
    _, out, _ = run_cmd(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Status}\n",
                         "nginx", "tomcat*", "openjdk-*-jdk-headless", "openjdk-*-jre-headless"])
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == "installed":
            rows.append({"name": parts[0], "version": parts[1]})
    step["log"] += [f"{r['name']}: {r['version']}" for r in rows]
    return {"rows": rows}


def default_inputs(run):
    o = run["outputs"]
    return {
        "title": "", "summary": "", "pitfalls": "", "memo": "",
        "commands": [c["cmd"] for c in o.get("history", {}).get("commands", []) if not c["trivial"]],
        "include": {"apt": True, "nginx": bool(o.get("nginx", {}).get("diff")), "errors": True, "versions": True},
    }


def build_draft(run, inputs):
    o = run["outputs"]
    inc = inputs.get("include", {})
    parts = [f"### {run['date']}" + (f" {inputs['title'].strip()}" if inputs.get("title", "").strip() else "")]

    def block(heading, body):
        if body and body.strip():
            parts.append(f"#### {heading}\n\n{body.strip()}")

    block("やったこと", inputs.get("summary", ""))
    cmds = []
    for c in inputs.get("commands", []):
        if not cmds or cmds[-1] != c:
            cmds.append(c)
    if cmds:
        block("実行したコマンド", "```bash\n" + "\n".join(cmds) + "\n```")
    events = o.get("apt", {}).get("events", [])
    if inc.get("apt") and events:
        block("apt でのインストール・削除", "```\n" + "\n".join(apt_lines(events)) + "\n```")
    ng = o.get("nginx", {})
    if inc.get("nginx") and ng.get("content"):
        if ng.get("diff"):
            block("Nginx 設定の変更", f"`{ng['path']}`\n\n```diff\n{ng['diff']}\n```")
        else:
            block("Nginx 設定", f"`{ng['path']}`\n\n```nginx\n{ng['content']}\n```")
    block("ハマった点", inputs.get("pitfalls", ""))
    block("考えたこと・メモ", inputs.get("memo", ""))
    er = o.get("errors", {})
    logs = er.get("nginx", []) + er.get("tomcat", [])
    if inc.get("errors") and logs:
        block("エラーログ", "```\n" + "\n".join(logs) + "\n```")
    rows = o.get("versions", {}).get("rows", [])
    if inc.get("versions") and rows:
        block("環境", "| 項目 | バージョン |\n| --- | --- |\n" + "\n".join(f"| {r['name']} | {r['version']} |" for r in rows))
    return "\n\n".join(parts) + "\n"


def step_build_draft(run, step):
    o = run["outputs"]
    work = {
        "コマンド": len([c for c in o.get("history", {}).get("commands", []) if not c["trivial"]]),
        "apt": len(o.get("apt", {}).get("events", [])),
        "エラー": len(o.get("errors", {}).get("nginx", [])) + len(o.get("errors", {}).get("tomcat", [])),
        "Nginx 設定の変更": 1 if o.get("nginx", {}).get("diff") else 0,
    }
    step["log"].append("集めた結果: " + "、".join(f"{k} {v} 件" for k, v in work.items()))
    if not any(work.values()):
        run["no_work"] = True
        step["log"].append("この日は作業がなかったので、ここで終了します")
        return None
    run["inputs"] = default_inputs(run)
    run["draft"] = build_draft(run, run["inputs"])
    step["log"].append(f"下書きを作りました（{len(run['draft'].splitlines())} 行）")
    return None


def step_approval(run, step):
    raise StepError("承認ステップは画面から承認してください")


def append_readme(run, step):
    md = run.get("draft", "").strip()
    if not md:
        raise StepError("下書きが空です")
    text = README.read_text() if README.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    if SECTION not in text.splitlines():
        text += f"\n{SECTION}\n"
        step["log"].append(f"README に「{SECTION}」の見出しを作りました")
    text += "\n" + md + "\n"
    README.write_text(text)
    step["log"].append(f"{README} に {len(md.splitlines())} 行を追記しました")
    return None


def git_commit(run, step):
    def git(*args):
        code, out, err = run_cmd(["git", "-C", str(REPO), *args])
        step["log"].append(f"$ git {' '.join(args)}")
        step["log"] += [l for l in (out + err).strip().splitlines() if l]
        return code
    if git("add", "README.md") != 0:
        raise StepError("git add に失敗しました")
    if run_cmd(["git", "-C", str(REPO), "diff", "--cached", "--quiet"])[0] == 0:
        raise StepError("コミットする変更がありません")
    title = run.get("inputs", {}).get("title", "").strip()
    message = f"Add worklog for {run['date']}" + (f": {title}" if title else "")
    if git("commit", "-m", message) != 0:
        raise StepError("git commit に失敗しました")
    return None


ACTIONS = {
    "collect-history": collect_history,
    "collect-apt": collect_apt,
    "collect-errors": collect_errors,
    "collect-nginx": collect_nginx,
    "collect-versions": collect_versions,
    "build-draft": step_build_draft,
    "approval": step_approval,
    "append-readme": append_readme,
    "git-commit": git_commit,
}


def main():
    p = argparse.ArgumentParser(description="作業記録ワークフロー")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="手動で1回実行する")
    r.add_argument("--date", type=date.fromisoformat, default=date.today())
    sub.add_parser("schedule", help="予定時刻を過ぎた未実行の日を実行する（タイマー用）")
    args = p.parse_args()
    runs = [trigger_run(args.date)] if args.cmd == "run" else schedule()
    for run in runs:
        print(f"Run #{run['id']} {run['date']} ({run['trigger']}): {run['status']}")
    if not runs:
        print("実行する日はありません")


if __name__ == "__main__":
    main()
