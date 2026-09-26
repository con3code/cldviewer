#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cldviewer — Claude Code セッションログビューア（単一ファイル・標準ライブラリのみ）
cldviewer — Claude Code session log viewer (single file, standard library only)

使い方 / Usage:
  python3 cldviewer.py                 # ~/.claude/projects を読み込んでブラウザで開く
  python3 cldviewer.py --port 9000     # ポート指定
  python3 cldviewer.py --dir PATH      # ログディレクトリを指定（別端末からコピーしたログなど）
  python3 cldviewer.py --dir ~/.claude/projects --dir /Volumes/HDD/claude-projects
                                       # 複数の場所をまとめて表示（同じプロジェクトは 1 つに統合）
  python3 cldviewer.py export -o cld.html [--project KEYWORD ...]
                                       # データ埋め込み済みの単体 HTML を書き出す（Python 不要で閲覧可）
  python3 cldviewer.py csv --project KEYWORD --mode prompts|pairs|full -o out.csv
                                       # CSV 書き出し
  python3 cldviewer.py list            # プロジェクト一覧を表示
  python3 cldviewer.py --lang en       # 英語表示（UI の初期言語・CSV・メッセージ）/ English
"""
import argparse
import base64
import csv
import glob
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

VERSION = "1.1.0"
LANG = "ja"  # CLI メッセージ・CSV 見出し・UI 初期言語（--lang / CLDVIEWER_LANG）

MSG = {
    "ja": {
        "desc": "Claude Code セッションログビューア",
        "h_dir": "ログディレクトリ（複数指定可。既定: ~/.claude/projects）",
        "h_nocache": "解析キャッシュ（~/.cache/cldviewer）を使わない",
        "h_noconfig": "保存済みの設定（追加したログの場所・プロジェクト統合）を読み込まない",
        "h_lang": "表示言語 ja / en（UI の初期言語・CSV 見出し・メッセージ。環境変数 CLDVIEWER_LANG でも指定可）",
        "h_serve": "ローカルサーバを起動してブラウザで開く（既定）",
        "h_export": "データ埋め込み済みの単体 HTML を書き出す",
        "h_project": "対象プロジェクト（パスや名前の部分一致、複数可）",
        "h_light": "ツールログ・推論を省いて軽量化",
        "h_images": "画像（貼り付けたスクリーンショット等）も埋め込む（ファイルが大きくなる）",
        "h_csv": "CSV を書き出す",
        "h_list": "プロジェクト一覧",
        "no_dir": "注意: ログディレクトリが見つかりません（スキップ）: %s",
        "no_dirs": "読めるログディレクトリがありません",
        "no_port": "ポートを確保できませんでした",
        "log": "ログ: %s%s", "missing": "  (見つかりません)", "quit": "終了は Ctrl+C", "bye": "\n終了",
        "no_projects": "対象プロジェクトがありません", "loading": "読み込み: %s", "done": "  完了 %.1fs, %d ターン",
        "exported": "書き出し: %s (%.1f MB, %d プロジェクト)", "written": "書き出し: %s",
        "pick_one": "プロジェクトを 1 つに絞ってください（--project KEYWORD）。候補:",
        "places": "  [%d か所]", "group": "  [統合: %s]",
        "dir_missing": "ディレクトリがありません: %s", "no_project_dirs": "プロジェクトフォルダが見つかりません: %s",
        "select_two": "2 つ以上のプロジェクトを選んでください",
        "save_failed": "warn: 設定の保存に失敗: %s", "groups_save_failed": "warn: 統合設定の保存に失敗: %s",
        "kinds": {"typed": "依頼", "queued": "依頼(割込)", "command": "コマンド", "shell": "シェル",
                  "peer": "他エージェント", "continuation": "継続", "auto": "自動"},
        "steps": {"text": "応答", "thinking": "推論", "notification": "通知", "system": "システム",
                  "compact": "圧縮サマリー", "compact_boundary": "圧縮", "interrupt": "中断", "meta": "コマンド展開"},
        "labels": {"auto": "（プロンプトなしで開始）", "continuation": "（前セッションからの継続）"},
        "csv_prompts": ["日時", "セッション", "種別", "依頼"],
        "csv_pairs": ["日時", "セッション", "種別", "依頼", "応答日時", "応答", "要約", "所要時間(秒)", "ツール回数"],
        "csv_full": ["日時", "セッション", "ターン番号", "種類", "名前", "内容"],
        "csv_prompt_kind": "依頼(%s)", "csv_tool_call": "ツール呼び出し", "csv_tool_result": "ツール結果", "csv_tool_result_err": "ツール結果(エラー)",
    },
    "en": {
        "desc": "Claude Code session log viewer",
        "h_dir": "log directory (repeatable; default: ~/.claude/projects)",
        "h_nocache": "do not use the parse cache (~/.cache/cldviewer)",
        "h_noconfig": "ignore saved settings (added log locations, merged projects)",
        "h_lang": "language ja / en (initial UI language, CSV headers, messages; also CLDVIEWER_LANG)",
        "h_serve": "start the local server and open the browser (default)",
        "h_export": "write a standalone HTML with the data embedded",
        "h_project": "target projects (substring of path or name; repeatable)",
        "h_light": "omit tool logs and reasoning to keep the file small",
        "h_images": "embed images (pasted screenshots etc.); makes the file much larger",
        "h_csv": "write a CSV file",
        "h_list": "list projects",
        "no_dir": "note: log directory not found (skipped): %s",
        "no_dirs": "no readable log directory",
        "no_port": "could not bind a port",
        "log": "logs: %s%s", "missing": "  (not found)", "quit": "Ctrl+C to quit", "bye": "\nbye",
        "no_projects": "no matching project", "loading": "loading: %s", "done": "  done %.1fs, %d turns",
        "exported": "written: %s (%.1f MB, %d projects)", "written": "written: %s",
        "pick_one": "narrow down to one project (--project KEYWORD). candidates:",
        "places": "  [%d locations]", "group": "  [merged: %s]",
        "dir_missing": "directory does not exist: %s", "no_project_dirs": "no project folders found in: %s",
        "select_two": "select two or more projects",
        "save_failed": "warn: failed to save settings: %s", "groups_save_failed": "warn: failed to save merge settings: %s",
        "kinds": {"typed": "Prompt", "queued": "Prompt (mid-turn)", "command": "Command", "shell": "Shell",
                  "peer": "Other agent", "continuation": "Continued", "auto": "Auto"},
        "steps": {"text": "Response", "thinking": "Reasoning", "notification": "Notice", "system": "System",
                  "compact": "Compact summary", "compact_boundary": "Compacted", "interrupt": "Interrupted", "meta": "Command expansion"},
        "labels": {"auto": "(started without a prompt)", "continuation": "(continued from previous session)"},
        "csv_prompts": ["Time", "Session", "Kind", "Prompt"],
        "csv_pairs": ["Time", "Session", "Kind", "Prompt", "Response time", "Response", "Recap", "Duration (s)", "Tool calls"],
        "csv_full": ["Time", "Session", "Turn", "Type", "Name", "Content"],
        "csv_prompt_kind": "Prompt (%s)", "csv_tool_call": "Tool call", "csv_tool_result": "Tool result", "csv_tool_result_err": "Tool result (error)",
    },
}


def _(key):
    return MSG.get(LANG, MSG["ja"]).get(key, MSG["ja"].get(key, key))
DEFAULT_DIR = os.path.expanduser("~/.claude/projects")
CACHE_DIR = os.path.expanduser("~/.cache/cldviewer")
CONFIG_FILE = os.path.expanduser("~/.config/cldviewer/roots.json")  # UI から追加したログの場所
GROUPS_FILE = os.path.expanduser("~/.config/cldviewer/groups.json")  # プロジェクト統合の定義
CACHE_VERSION = 10
MAX_TEXT = 20000        # ツール入出力 1 件あたりの保持上限（文字）
MAX_SUB_TEXT = 4000     # サブエージェントの各ステップの保持上限


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def trim(s, limit=MAX_TEXT):
    if s is None:
        return ""
    if not isinstance(s, str):
        try:
            s = json.dumps(s, ensure_ascii=False, indent=1)
        except Exception:
            s = str(s)
    if len(s) > limit:
        return s[:limit] + "\n… (%d chars omitted / 文字省略)" % (len(s) - limit)
    return s


def trim_obj(obj, limit=MAX_TEXT, depth=0):
    """dict/list 内の長い文字列だけを丸める。"""
    if isinstance(obj, str):
        return trim(obj, limit)
    if depth > 6:
        return trim(obj, limit)
    if isinstance(obj, dict):
        return {k: trim_obj(v, limit, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trim_obj(v, limit, depth + 1) for v in obj[:200]]
    return obj


RE_SYSREM = re.compile(r"<system-reminder>[\s\S]*?</system-reminder>\s*")
RE_TAG = re.compile(r"<(/?)([a-zA-Z_][\w-]*)[^>]*>")


def clean_prompt(text):
    text = RE_SYSREM.sub("", text)
    return text.strip()


def tag_content(text, tag):
    m = re.search(r"<%s>([\s\S]*?)</%s>" % (tag, tag), text)
    return m.group(1).strip() if m else ""


def content_to_text(content, refs=None, prefix=""):
    """message.content（str または block list）から表示用テキストと画像数を返す。
    refs を渡すと画像ブロックの位置（行内インデックス）を追加する。"""
    if content is None:
        return "", 0
    if isinstance(content, str):
        return content, 0
    parts, images = [], 0
    for j, b in enumerate(content):
        if not isinstance(b, dict):
            parts.append(str(b))
            continue
        bt = b.get("type")
        if bt == "text":
            parts.append(b.get("text", ""))
        elif bt == "image":
            images += 1
            parts.append("[image]")
            if refs is not None:
                src = b.get("source") or {}
                ref = {"idx": prefix + str(j), "type": src.get("media_type") or "image/png"}
                if src.get("type") == "url" and src.get("url"):
                    ref["url"] = src["url"]
                refs.append(ref)
        elif bt == "document":
            parts.append("[document]")
    return "\n".join(p for p in parts if p), images


def image_from_line(path, off, idx):
    """ログファイルの指定オフセットの行から画像ブロックを取り出す。(media_type, bytes) を返す。"""
    with open(path, "rb") as f:
        f.seek(int(off))
        raw = f.readline()
    o = json.loads(raw.decode("utf-8", errors="replace"))
    content = (o.get("message") or {}).get("content")
    parts = str(idx).split(".")
    b = content[int(parts[0])]
    if len(parts) > 1:
        b = b["content"][int(parts[1])]
    src = b.get("source") or {}
    if src.get("type") != "base64":
        raise ValueError("not a base64 image")
    return src.get("media_type") or "image/png", base64.b64decode(src.get("data") or "")


def iso_to_ms(ts):
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# セッション解析
# ---------------------------------------------------------------------------

class SessionParser:
    def __init__(self, path):
        self.path = path
        self.sid = os.path.splitext(os.path.basename(path))[0]
        self.turns = []
        self.cur = None
        self.tool_index = {}       # tool_use_id -> step
        self.sidechains = {}       # agentId -> {'steps': [...], 'turn': turnId}
        self.sess = {
            "id": self.sid,
            "file": path,
            "size": os.path.getsize(path),
            "mtime": os.path.getmtime(path),
            "title": None,
            "cwd": None,
            "gitBranch": None,
            "version": None,
            "firstTs": None,
            "lastTs": None,
            "cost": None,
            "continuedIn": None,
            "models": {},
            "compactions": 0,
            "lines": 0,
        }

    # --- ターン管理 -------------------------------------------------------
    def new_turn(self, ts, kind, prompt, **extra):
        t = {
            "id": "%s:%d" % (self.sid, len(self.turns)),
            "sid": self.sid,
            "ts": ts,
            "endTs": ts,
            "kind": kind,            # typed / queued / command / shell / continuation / auto
            "prompt": prompt or "",
            "images": 0,
            "recap": None,
            "durationMs": None,
            "toolCount": 0,
            "responses": [],         # [{ts, text}]
            "steps": [],
            "interrupted": False,
            "model": None,
            "sidechains": [],
        }
        t.update(extra)
        self.turns.append(t)
        self.cur = t
        return t

    def ensure_turn(self, ts):
        if self.cur is None:
            self.new_turn(ts, "auto", "", labelKey="auto")
        return self.cur

    def add_step(self, ts, kind, **fields):
        t = self.ensure_turn(ts)
        step = {"ts": ts, "kind": kind}
        step.update(fields)
        t["steps"].append(step)
        if ts:
            t["endTs"] = ts
        return step

    # --- レコード処理 -----------------------------------------------------
    def feed(self, o):
        t = o.get("type")
        ts = o.get("timestamp")
        s = self.sess
        if ts:
            if s["firstTs"] is None or ts < s["firstTs"]:
                s["firstTs"] = ts
            if s["lastTs"] is None or ts > s["lastTs"]:
                s["lastTs"] = ts
        if not s["cwd"] and o.get("cwd"):
            s["cwd"] = o["cwd"]
        if o.get("gitBranch") and not s["gitBranch"]:
            s["gitBranch"] = o["gitBranch"]
        if o.get("version"):
            s["version"] = o["version"]

        if t == "ai-title":
            s["title"] = o.get("aiTitle") or s["title"]
        elif t == "cost-state":
            s["cost"] = {
                "usd": o.get("totalCostUSD"),
                "durationMs": o.get("totalDuration"),
                "apiMs": o.get("totalAPIDuration"),
                "linesAdded": o.get("totalLinesAdded"),
                "linesRemoved": o.get("totalLinesRemoved"),
            }
            for m, u in (o.get("modelUsage") or {}).items():
                s["models"][m] = {
                    "in": u.get("inputTokens"),
                    "out": u.get("outputTokens"),
                    "cacheRead": u.get("cacheReadInputTokens"),
                    "cacheWrite": u.get("cacheCreationInputTokens"),
                }
        elif t == "continued-in":
            s["continuedIn"] = o.get("continuedInSessionId")
        elif t == "system":
            self.feed_system(o, ts)
        elif t == "attachment":
            self.feed_attachment(o, ts)
        elif t == "user":
            self.feed_user(o, ts)
        elif t == "assistant":
            self.feed_assistant(o, ts)

    def feed_system(self, o, ts):
        sub = o.get("subtype")
        if sub == "turn_duration":
            if self.cur is not None:
                self.cur["durationMs"] = o.get("durationMs")
        elif sub == "away_summary":
            if self.cur is not None:
                c = (o.get("content") or "").replace("(disable recaps in /config)", "").strip()
                self.cur["recap"] = c
        elif sub == "compact_boundary":
            self.sess["compactions"] += 1
            meta = o.get("compactMetadata") or {}
            self.add_step(ts, "compact_boundary", text="compact: %s, %s → %s tokens" % (
                meta.get("trigger", "?"), meta.get("preTokens", "?"), meta.get("postTokens", "?")))
        elif sub in ("local_command", "bridge_status", "informational"):
            c = o.get("content")
            if c:
                self.add_step(ts, "system", name=sub, text=trim(c, 4000))
        else:
            c = o.get("content")
            if isinstance(c, str) and c and self.cur is not None:
                self.add_step(ts, "system", name=sub or "system", text=trim(c, 4000))

    def feed_attachment(self, o, ts):
        a = o.get("attachment") or {}
        at = a.get("type")
        if at == "queued_command":
            p = a.get("prompt")
            text, images = content_to_text(p)
            mode = a.get("commandMode")
            okind = (a.get("origin") or {}).get("kind")
            if text.lstrip().startswith("<task-notification>") or mode == "task-notification":
                self.add_step(ts, "notification", name="task",
                              status=tag_content(text, "status"),
                              text=trim(tag_content(text, "summary") or text, 4000))
                return
            if okind == "peer":
                self.peer_message(ts, a.get("origin") or {}, clean_prompt(text), None)
                return
            if mode not in (None, "prompt") or (okind not in (None, "human")):
                self.add_step(ts, "notification", name=okind or mode or "queued", text=trim(clean_prompt(text), 4000))
                return
            text = clean_prompt(text)
            if text:
                self.new_turn(ts, "queued", text, images=images, promptId=a.get("source_uuid"))
        elif at == "task_status":
            pass

    def feed_user(self, o, ts):
        m = o.get("message") or {}
        c = m.get("content")
        if o.get("isSidechain"):
            self.feed_sidechain(o, ts, "user")
            return
        # ツール結果
        refs = []
        if isinstance(c, list):
            remaining = []
            for j, b in enumerate(c):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    self.attach_tool_result(b, ts, j)
                else:
                    remaining.append((j, b))
            if not remaining:
                return
            parts, images = [], 0
            for j, b in remaining:
                t2, n = content_to_text([b], refs, "")
                if refs and refs[-1]["idx"] == "0" and n:
                    refs[-1]["idx"] = str(j)
                images += n
                if t2:
                    parts.append(t2)
            text = "\n".join(parts)
        else:
            text, images = content_to_text(c)
        for r in refs:
            r["off"] = self.cur_off
        raw = text
        text = text.strip()
        if not text:
            return
        src = o.get("promptSource")
        origin_kind = (o.get("origin") or {}).get("kind")

        if o.get("isCompactSummary"):
            first = self.cur is None
            if first:
                self.new_turn(ts, "continuation", "", labelKey="continuation")
            self.add_step(ts, "compact", text=trim(text, MAX_TEXT))
            return
        if origin_kind == "peer":
            self.peer_message(ts, o.get("origin") or {}, clean_prompt(text), o.get("promptId"))
            return
        if o.get("isMeta"):
            self.add_step(ts, "meta", name="command-expansion", text=trim(clean_prompt(text), 8000))
            return
        if text.startswith("<task-notification>"):
            self.add_step(ts, "notification", name="task",
                          status=tag_content(text, "status"),
                          text=trim(tag_content(text, "summary") or text, 4000))
            return
        if text.startswith("<local-command-stdout>"):
            self.add_step(ts, "system", name="local-command-stdout",
                          text=trim(tag_content(text, "local-command-stdout") or text, 4000))
            return
        if text.startswith("<local-command-caveat>"):
            return
        if text.startswith("[Request interrupted"):
            if self.cur is not None:
                self.cur["interrupted"] = True
            self.add_step(ts, "interrupt", text=text[:200])
            return
        if text.startswith("<bash-input>"):
            self.new_turn(ts, "shell", tag_content(text, "bash-input") or text, promptId=o.get("promptId"))
            return
        if text.startswith("<bash-stdout>") or text.startswith("<bash-stderr>"):
            out = tag_content(text, "bash-stdout")
            err = tag_content(text, "bash-stderr")
            self.add_step(ts, "system", name="shell-output", text=trim((out + ("\n[stderr]\n" + err if err else "")).strip() or text, 8000))
            return
        if "<command-name>" in text:
            name = tag_content(text, "command-name")
            args = tag_content(text, "command-args")
            prompt = (name + " " + args).strip()
            self.new_turn(ts, "command", prompt, promptId=o.get("promptId"))
            return
        if src == "system" or (origin_kind and origin_kind != "human"):
            self.add_step(ts, "notification", name=origin_kind or "system", text=trim(clean_prompt(text), 4000))
            return
        # 人間のプロンプト
        cleaned = clean_prompt(raw)
        if not cleaned:
            return
        kind = "queued" if src == "queued" else "typed"
        self.new_turn(ts, kind, cleaned, images=images, imageRefs=refs, promptId=o.get("promptId"))

    def peer_message(self, ts, origin, text, prompt_id):
        """他エージェントからのメッセージ。自セッションのサブエージェントの最終報告（hand-back）は通知扱い。"""
        body = origin.get("body") or text
        sender = origin.get("name") or origin.get("from") or "?"
        if origin.get("handback"):
            self.add_step(ts, "notification", name="subagent-report", text=trim(body, 8000), sender=sender)
            return
        self.new_turn(ts, "peer", body, sender=sender, promptId=prompt_id)

    def attach_tool_result(self, b, ts, j=0):
        tid = b.get("tool_use_id")
        content = b.get("content")
        refs = []
        if isinstance(content, list):
            text, _ = content_to_text(content, refs, "%d." % j)
            for r in refs:
                r["off"] = self.cur_off
        else:
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        step = self.tool_index.get(tid)
        if step is None:
            step = self.add_step(ts, "tool", id=tid, name="?", input={}, result=trim(text), isError=bool(b.get("is_error")), resultTs=ts)
            if refs:
                step["images"] = refs
            return
        step["result"] = trim(text)
        step["isError"] = bool(b.get("is_error"))
        step["resultTs"] = ts
        if refs:
            step["images"] = refs
        if ts and self.cur is not None:
            self.cur["endTs"] = ts

    def feed_assistant(self, o, ts):
        if o.get("isSidechain"):
            self.feed_sidechain(o, ts, "assistant")
            return
        m = o.get("message") or {}
        content = m.get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        t = self.ensure_turn(ts)
        model = m.get("model")
        if model and not t["model"]:
            t["model"] = model
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                txt = b.get("text") or ""
                if txt.strip():
                    self.add_step(ts, "text", text=txt)
                    t["responses"].append({"ts": ts, "text": txt})
            elif bt == "thinking":
                th = b.get("thinking") or ""
                if th.strip():
                    self.add_step(ts, "thinking", text=trim(th))
            elif bt == "tool_use":
                step = self.add_step(ts, "tool", id=b.get("id"), name=b.get("name"),
                                     input=trim_obj(b.get("input")), result=None, isError=False)
                self.tool_index[b.get("id")] = step
                t["toolCount"] += 1

    def feed_sidechain(self, o, ts, role):
        aid = o.get("agentId") or "legacy"
        sc = self.sidechains.get(aid)
        if sc is None:
            sc = {"id": aid, "steps": [], "legacy": True}
            self.sidechains[aid] = sc
            if self.cur is not None:
                self.cur["sidechains"].append(aid)
        m = o.get("message") or {}
        content = m.get("content")
        light_steps(sc["steps"], role, content, ts)

    # --- 実行 ---------------------------------------------------------------
    def run(self):
        self.cur_off = 0
        with open(self.path, "rb") as f:
            while True:
                off = f.tell()
                raw = f.readline()
                if not raw:
                    break
                self.sess["lines"] += 1
                self.cur_off = off
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                try:
                    self.feed(o)
                except Exception as e:  # 1 レコードの失敗で全体を止めない
                    sys.stderr.write("warn: %s line %d: %s\n" % (self.sid[:8], self.sess["lines"], e))
        self.load_subagents()
        for t in self.turns:
            if t["durationMs"] is None and t["ts"] and t["endTs"]:
                a, b = iso_to_ms(t["ts"]), iso_to_ms(t["endTs"])
                if a is not None and b is not None and b >= a:
                    t["durationMs"] = b - a
        self.sess["turns"] = self.turns
        self.sess["turnCount"] = len(self.turns)
        self.sess["promptCount"] = sum(1 for t in self.turns if t["kind"] in ("typed", "queued", "command", "shell"))
        self.sess["sidechains"] = self.sidechains
        return self.sess

    def load_subagents(self):
        d = os.path.join(os.path.dirname(self.path), self.sid, "subagents")
        if not os.path.isdir(d):
            return
        for fp in sorted(glob.glob(os.path.join(d, "agent-*.jsonl"))):
            aid = os.path.basename(fp)[len("agent-"):-len(".jsonl")]
            meta = {}
            mp = fp[:-len(".jsonl")] + ".meta.json"
            if os.path.exists(mp):
                try:
                    with open(mp, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            steps = []
            first_ts = last_ts = None
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if o.get("type") not in ("user", "assistant"):
                            continue
                        ts = o.get("timestamp")
                        if ts:
                            first_ts = first_ts or ts
                            last_ts = ts
                        light_steps(steps, o["type"], (o.get("message") or {}).get("content"), ts)
            except Exception:
                continue
            agent = {
                "id": aid,
                "type": meta.get("agentType"),
                "description": meta.get("description"),
                "model": meta.get("model"),
                "firstTs": first_ts,
                "lastTs": last_ts,
                "steps": steps,
            }
            tid = meta.get("toolUseId")
            step = self.tool_index.get(tid) if tid else None
            if step is not None:
                step["subagent"] = agent
            else:
                self.sidechains[aid] = agent
                # 時刻でターンに割り当て
                target = None
                for t in self.turns:
                    if first_ts and t["ts"] and t["ts"] <= first_ts:
                        target = t
                if target is not None:
                    target["sidechains"].append(aid)


def light_steps(steps, role, content, ts):
    """サブエージェント用の軽量ステップ列を追加する。"""
    if content is None:
        return
    if isinstance(content, str):
        if content.strip():
            steps.append({"ts": ts, "kind": "prompt" if role == "user" else "text", "text": trim(content, MAX_SUB_TEXT)})
        return
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            if (b.get("text") or "").strip():
                steps.append({"ts": ts, "kind": "prompt" if role == "user" else "text", "text": trim(b["text"], MAX_SUB_TEXT)})
        elif bt == "thinking":
            if (b.get("thinking") or "").strip():
                steps.append({"ts": ts, "kind": "thinking", "text": trim(b["thinking"], MAX_SUB_TEXT)})
        elif bt == "tool_use":
            steps.append({"ts": ts, "kind": "tool", "id": b.get("id"), "name": b.get("name"),
                          "input": trim_obj(b.get("input"), MAX_SUB_TEXT), "result": None})
        elif bt == "tool_result":
            text, _ = content_to_text(b.get("content")) if isinstance(b.get("content"), list) else (b.get("content") or "", 0)
            tid = b.get("tool_use_id")
            for s in reversed(steps):
                if s.get("kind") == "tool" and s.get("id") == tid:
                    s["result"] = trim(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False), MAX_SUB_TEXT)
                    s["isError"] = bool(b.get("is_error"))
                    break


# ---------------------------------------------------------------------------
# キャッシュ付き読み込み
# ---------------------------------------------------------------------------

def cache_path(path):
    st = os.stat(path)
    key = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, "%s-%d-%d-v%d.json" % (key, st.st_size, int(st.st_mtime), CACHE_VERSION)), key


def load_session(path, use_cache=True):
    cp, key = cache_path(path)
    if use_cache and os.path.exists(cp):
        try:
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    sess = SessionParser(path).run()
    if use_cache:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            for old in glob.glob(os.path.join(CACHE_DIR, key + "-*.json")):
                try:
                    os.remove(old)
                except Exception:
                    pass
            tmp = cp + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sess, f, ensure_ascii=False)
            os.replace(tmp, cp)
        except Exception as e:
            sys.stderr.write("warn: cache write failed: %s\n" % e)
    return sess


# ---------------------------------------------------------------------------
# プロジェクト
# ---------------------------------------------------------------------------

def peek_cwd(path, limit=60):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > limit:
                    break
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if isinstance(o, dict) and o.get("cwd"):
                    return o["cwd"]
    except Exception:
        pass
    return None


def guess_path_from_dirname(name):
    # "-Volumes-SSD-SS990P-Dev-x" → "/Volumes/SSD/SS990P/Dev/x"（区切りは曖昧なので参考値）
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name


def sanitize_path(p):
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def project_name(dirname, cwd):
    name = os.path.basename(cwd.rstrip("/")) or cwd
    s = sanitize_path(cwd)
    if dirname != s and dirname.startswith(s):
        name += " (" + dirname[len(s):].strip("-") + ")"
    elif dirname != s:
        name += " (" + dirname.strip("-")[-30:] + ")"
    return name


def load_saved_roots():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            v = json.load(f)
        return [r for r in v.get("roots", []) if isinstance(r, str)]
    except Exception:
        return []


def save_roots(roots):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"roots": roots}, f, ensure_ascii=False, indent=1)
    except Exception as e:
        sys.stderr.write(_("save_failed") % e + "\n")


def norm_root(p):
    return os.path.abspath(os.path.expanduser(p))


def resolve_roots(dirs, use_saved=True):
    """CLI 指定（無ければ既定）に、UI から追加して保存済みの場所を足す。"""
    roots = [norm_root(d) for d in (dirs or [DEFAULT_DIR])]
    if use_saved:
        roots += [norm_root(r) for r in load_saved_roots()]
    out = []
    for r in roots:
        if r not in out:
            out.append(r)
    return out


def load_groups():
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            v = json.load(f)
        out = []
        for g in v.get("groups", []):
            if isinstance(g, dict) and g.get("id") and isinstance(g.get("members"), list):
                out.append({"id": g["id"], "name": g.get("name") or g["id"], "members": [m for m in g["members"] if isinstance(m, str)]})
        return out
    except Exception:
        return []


def save_groups(groups):
    try:
        os.makedirs(os.path.dirname(GROUPS_FILE), exist_ok=True)
        with open(GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump({"groups": groups}, f, ensure_ascii=False, indent=1)
    except Exception as e:
        sys.stderr.write(_("groups_save_failed") % e + "\n")


def find_group(groups, pid):
    for g in groups or []:
        if g["id"] == pid:
            return g
    return None


def resolve_members(groups, pid):
    """統合プロジェクト ID なら構成フォルダ名の一覧、そうでなければ [pid]。"""
    g = find_group(groups, pid)
    return list(g["members"]) if g else [pid]


def _jsonl_files(pd):
    return [f for f in sorted(glob.glob(os.path.join(pd, "*.jsonl"))) if os.path.getsize(f) > 0]


def project_files(roots, pid, groups=None):
    """複数ルート・統合メンバーにまたがるログを集める。同じセッション ID は大きい方を採用。"""
    best = {}
    for member in resolve_members(groups, pid):
        for root in roots:
            pd = os.path.join(root, member)
            if not os.path.isdir(pd):
                continue
            for f in _jsonl_files(pd):
                b = os.path.basename(f)
                if b not in best or os.path.getsize(f) > os.path.getsize(best[b]):
                    best[b] = f
    return sorted(best.values())


def detect_cwd(pd, files):
    idx = os.path.join(pd, "sessions-index.json")
    if os.path.exists(idx):
        try:
            with open(idx, "r", encoding="utf-8") as f:
                v = json.load(f).get("originalPath")
            if v:
                return v
        except Exception:
            pass
    for f in sorted(files, key=os.path.getsize, reverse=True):
        cwd = peek_cwd(f)
        if cwd:
            return cwd
    return None


def list_projects(roots, groups=None):
    if isinstance(roots, str):
        roots = [roots]
    by_id = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d in sorted(os.listdir(root)):
            pd = os.path.join(root, d)
            if not os.path.isdir(pd):
                continue
            files = _jsonl_files(pd)
            if not files:
                continue
            e = by_id.setdefault(d, {"id": d, "files": {}, "roots": [], "cwd": None})
            e["roots"].append(root)
            for f in files:
                b = os.path.basename(f)
                if b not in e["files"] or os.path.getsize(f) > os.path.getsize(e["files"][b]):
                    e["files"][b] = f
            if not e["cwd"]:
                e["cwd"] = detect_cwd(pd, files)
    projects = []
    for d, e in by_id.items():
        files = list(e["files"].values())
        cwd = e["cwd"] or guess_path_from_dirname(d)
        mtimes = [os.path.getmtime(f) for f in files]
        projects.append({
            "id": d,
            "path": cwd,
            "name": project_name(d, cwd),
            "roots": e["roots"],
            "sessionCount": len(files),
            "bytes": sum(os.path.getsize(f) for f in files),
            "lastModified": datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "firstModified": datetime.fromtimestamp(min(mtimes), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        })
    # 統合プロジェクト: メンバーを 1 つのエントリにまとめる
    for g in groups or []:
        members = [p for p in projects if p["id"] in g["members"]]
        if not members:
            continue
        for m in members:
            projects.remove(m)
        seen = {}
        for m in members:
            for f in project_files(roots, m["id"]):
                b = os.path.basename(f)
                if b not in seen or os.path.getsize(f) > os.path.getsize(seen[b]):
                    seen[b] = f
        files = list(seen.values())
        mtimes = [os.path.getmtime(f) for f in files]
        projects.append({
            "id": g["id"],
            "path": " + ".join(m["path"] for m in members),
            "name": g["name"],
            "group": True,
            "members": [{"id": m["id"], "path": m["path"], "name": m["name"], "sessionCount": m["sessionCount"]} for m in members],
            "missingMembers": [x for x in g["members"] if x not in [m["id"] for m in members]],
            "roots": sorted({r for m in members for r in m["roots"]}),
            "sessionCount": len(files),
            "bytes": sum(os.path.getsize(f) for f in files),
            "lastModified": max(m["lastModified"] for m in members),
            "firstModified": min(m["firstModified"] for m in members),
        })
    projects.sort(key=lambda p: p["lastModified"], reverse=True)
    return projects


def suggest_groups(projects):
    """作業フォルダの末尾名が同じ未統合プロジェクトを統合候補として返す。"""
    by_base = {}
    for p in projects:
        if p.get("group"):
            continue
        base = os.path.basename(p["path"].rstrip("/")).lower()
        if base:
            by_base.setdefault(base, []).append(p)
    out = []
    for base, ps in by_base.items():
        if len(ps) > 1:
            out.append({"name": os.path.basename(ps[0]["path"].rstrip("/")), "members": [{"id": p["id"], "path": p["path"]} for p in ps]})
    out.sort(key=lambda s: s["name"])
    return out


def new_group_id(members):
    return "group-" + hashlib.sha1(("|".join(sorted(members)) + str(time.time())).encode("utf-8")).hexdigest()[:10]


def load_project(roots, pid, use_cache=True, progress=None, groups=None):
    if isinstance(roots, str):
        roots = [roots]
    files = project_files(roots, pid, groups)
    if not files:
        raise FileNotFoundError(pid)
    group = find_group(groups, pid)
    sessions, turns = [], []
    for i, f in enumerate(files):
        if progress:
            progress(i, len(files), f)
        s = load_session(f, use_cache)
        turns.extend(s["turns"])
        meta = {k: v for k, v in s.items() if k not in ("turns", "sidechains")}
        meta["sidechains"] = s.get("sidechains") or {}
        meta["root"] = os.path.dirname(os.path.dirname(f))
        meta["projectDir"] = os.path.basename(os.path.dirname(f))
        sessions.append(meta)
    turns.sort(key=lambda t: (t["ts"] or "", t["id"]))
    sessions.sort(key=lambda s: s["firstTs"] or "")
    cwd = next((s["cwd"] for s in sessions if s.get("cwd")), None) or guess_path_from_dirname(pid)
    used_roots = []
    for s in sessions:
        if s["root"] not in used_roots:
            used_roots.append(s["root"])
    members = []
    if group:
        for m in group["members"]:
            ss = [s for s in sessions if s["projectDir"] == m]
            mp = next((s["cwd"] for s in ss if s.get("cwd")), None) or guess_path_from_dirname(m)
            members.append({"id": m, "path": mp, "name": project_name(m, mp), "sessionCount": len(ss)})
    return {
        "id": pid,
        "path": " + ".join(m["path"] for m in members if m["sessionCount"]) if group else cwd,
        "name": group["name"] if group else project_name(pid, cwd),
        "group": bool(group),
        "members": members,
        "roots": used_roots,
        "sessions": sessions,
        "turns": turns,
        "generatedAt": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def turn_light(t):
    d = {k: v for k, v in t.items() if k not in ("steps", "sidechains")}
    d["stepCount"] = len(t["steps"])
    d["thinkCount"] = sum(1 for s in t["steps"] if s["kind"] == "thinking")
    d["hasDetails"] = bool(t["steps"] or t.get("sidechains"))
    return d


def project_light(p):
    return {
        "id": p["id"], "path": p["path"], "name": p["name"], "roots": p.get("roots", []), "group": p.get("group", False), "members": p.get("members", []), "generatedAt": p.get("generatedAt"),
        "sessions": [{k: v for k, v in s.items() if k != "sidechains"} for s in p["sessions"]],
        "turns": [turn_light(t) for t in p["turns"]],
        "light": True,
    }


def turn_details(p, t):
    sess = next((s for s in p["sessions"] if s["id"] == t["sid"]), None)
    agents = []
    if sess:
        for aid in t.get("sidechains") or []:
            a = (sess.get("sidechains") or {}).get(aid)
            if a:
                agents.append(a)
    return {"steps": t["steps"], "agents": agents}


def step_text(s):
    parts = [s.get("text") or ""]
    if s.get("kind") == "tool":
        inp = s.get("input")
        parts.append(s.get("name") or "")
        parts.append(inp if isinstance(inp, str) else json.dumps(inp or {}, ensure_ascii=False))
        parts.append(s.get("result") or "")
        sub = s.get("subagent")
        if sub:
            parts.append(sub.get("description") or "")
            parts.extend(step_text(x) for x in sub.get("steps") or [])
    return "\n".join(parts)


def turn_text(p, t, scope):
    if scope == "prompt":
        return t.get("prompt") or ""
    if scope == "response":
        return "\n".join(r["text"] for r in t.get("responses") or [])
    d = turn_details(p, t)
    parts = [t.get("prompt") or "", t.get("recap") or ""]
    parts.extend(step_text(s) for s in d["steps"])
    for a in d["agents"]:
        parts.append(a.get("description") or "")
        parts.extend(step_text(s) for s in a.get("steps") or [])
    return "\n".join(parts)


def search_project(p, q, scope="all"):
    terms = [k.lower() for k in q.split() if k]
    if not terms:
        return [t["id"] for t in p["turns"]]
    out = []
    for t in p["turns"]:
        hay = turn_text(p, t, scope).lower()
        if all(k in hay for k in terms):
            out.append(t["id"])
    return out


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def fmt_local(ts):
    ms = iso_to_ms(ts)
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def turn_label(t):
    if t.get("prompt"):
        return t["prompt"]
    return _("labels").get(t.get("labelKey"), t.get("label", ""))


def project_csv(project, mode="prompts"):
    buf = io.StringIO()
    w = csv.writer(buf)
    KIND_LABEL = _("kinds")
    stitle = {s["id"]: (s.get("title") or s["id"][:8]) for s in project["sessions"]}
    if mode == "prompts":
        w.writerow(_("csv_prompts"))
        for t in project["turns"]:
            if t["kind"] not in ("typed", "queued", "command", "shell"):
                continue
            w.writerow([fmt_local(t["ts"]), stitle.get(t["sid"], t["sid"]), KIND_LABEL.get(t["kind"], t["kind"]), t["prompt"]])
    elif mode == "pairs":
        w.writerow(_("csv_pairs"))
        for t in project["turns"]:
            resp = "\n\n".join(r["text"] for r in t["responses"])
            rts = t["responses"][-1]["ts"] if t["responses"] else ""
            w.writerow([fmt_local(t["ts"]), stitle.get(t["sid"], t["sid"]), KIND_LABEL.get(t["kind"], t["kind"]),
                        turn_label(t), fmt_local(rts), resp, t.get("recap") or "",
                        round((t.get("durationMs") or 0) / 1000), t["toolCount"]])
    else:
        w.writerow(_("csv_full"))
        for i, t in enumerate(project["turns"], 1):
            w.writerow([fmt_local(t["ts"]), stitle.get(t["sid"], t["sid"]), i, _("csv_prompt_kind") % KIND_LABEL.get(t["kind"], t["kind"]), "", turn_label(t)])
            for s in t["steps"]:
                k = s["kind"]
                if k == "tool":
                    inp = s.get("input")
                    inp_s = inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)
                    w.writerow([fmt_local(s["ts"]), stitle.get(t["sid"], t["sid"]), i, _("csv_tool_call"), s.get("name"), inp_s])
                    if s.get("result") is not None:
                        w.writerow([fmt_local(s.get("resultTs") or s["ts"]), stitle.get(t["sid"], t["sid"]), i, _("csv_tool_result_err") if s.get("isError") else _("csv_tool_result"), s.get("name"), s["result"]])
                else:
                    label = _("steps").get(k, k)
                    w.writerow([fmt_local(s["ts"]), stitle.get(t["sid"], t["sid"]), i, label, s.get("name", ""), s.get("text", "")])
    return "﻿" + buf.getvalue()


# ---------------------------------------------------------------------------
# HTTP サーバ
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, cli_roots, use_cache=True):
        self.cli_roots = list(cli_roots)
        self.saved_roots = [norm_root(r) for r in load_saved_roots()]
        self.groups = load_groups()
        self.use_cache = use_cache
        self.lock = threading.Lock()
        self.projects_cache = {}

    @property
    def roots(self):
        out = []
        for r in self.cli_roots + self.saved_roots:
            if r not in out:
                out.append(r)
        return out

    def roots_info(self):
        return [{"path": r, "ok": os.path.isdir(r), "saved": r in self.saved_roots and r not in self.cli_roots}
                for r in self.roots]

    def add_root(self, path):
        r = norm_root(path)
        if not os.path.isdir(r):
            raise FileNotFoundError(_("dir_missing") % r)
        if not any(os.path.isdir(os.path.join(r, d)) for d in os.listdir(r)):
            raise ValueError(_("no_project_dirs") % r)
        if r not in self.saved_roots and r not in self.cli_roots:
            self.saved_roots.append(r)
            save_roots(self.saved_roots)
        with self.lock:
            self.projects_cache.clear()
        return r

    def remove_root(self, path):
        r = norm_root(path)
        if r in self.saved_roots:
            self.saved_roots.remove(r)
            save_roots(self.saved_roots)
        if r in self.cli_roots:
            self.cli_roots.remove(r)
        with self.lock:
            self.projects_cache.clear()

    def signature(self, pid):
        return tuple(sorted((f, os.path.getsize(f), int(os.path.getmtime(f)))
                            for f in project_files(self.roots, pid, self.groups)))

    def projects(self):
        return list_projects(self.roots, self.groups)

    def create_group(self, name, members):
        # 既存グループが含まれていれば展開して 1 つにまとめる
        flat = []
        for m in members:
            g = find_group(self.groups, m)
            for x in (g["members"] if g else [m]):
                if x not in flat:
                    flat.append(x)
        if len(flat) < 2:
            raise ValueError(_("select_two"))
        self.groups = [g for g in self.groups if g["id"] not in members]
        # 他グループと重なるメンバーは移動
        for g in self.groups:
            g["members"] = [x for x in g["members"] if x not in flat]
        self.groups = [g for g in self.groups if len(g["members"]) >= 1]
        gid = new_group_id(flat)
        self.groups.append({"id": gid, "name": (name or "").strip() or project_name(flat[0], guess_path_from_dirname(flat[0])), "members": flat})
        save_groups(self.groups)
        with self.lock:
            self.projects_cache.clear()
        return gid

    def rename_group(self, gid, name):
        g = find_group(self.groups, gid)
        if not g:
            raise FileNotFoundError(gid)
        g["name"] = (name or "").strip() or g["name"]
        save_groups(self.groups)
        with self.lock:
            self.projects_cache.clear()

    def delete_group(self, gid):
        self.groups = [g for g in self.groups if g["id"] != gid]
        save_groups(self.groups)
        with self.lock:
            self.projects_cache.clear()

    def get_project(self, pid, refresh=False):
        with self.lock:
            cached = self.projects_cache.get(pid)
        if cached and not refresh and self.signature(pid) == cached.get("_sig"):
            return cached
        def prog(i, n, f):
            sys.stderr.write("  [%d/%d] %s (%.1f MB)\n" % (i + 1, n, os.path.basename(f), os.path.getsize(f) / 1e6))
        sys.stderr.write(_("loading") % pid + "\n")
        t0 = time.time()
        p = load_project(self.roots, pid, self.use_cache, prog, self.groups)
        p["_sig"] = self.signature(pid)
        sys.stderr.write(_("done") % (time.time() - t0, len(p["turns"])) + "\n")
        with self.lock:
            self.projects_cache[pid] = p
        return p


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text, ctype="text/html; charset=utf-8", status=200, filename=None):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % filename)
            self.end_headers()
            self.wfile.write(body)

        def projects_payload(self):
            projects = store.projects()
            return {"roots": store.roots_info(), "projects": projects, "groups": store.groups, "suggestions": suggest_groups(projects)}

        def do_POST(self):
            u = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if u.path == "/api/roots":
                    action = body.get("action", "add")
                    if action == "add":
                        store.add_root(body.get("path", ""))
                    elif action == "remove":
                        store.remove_root(body.get("path", ""))
                    self.send_json(self.projects_payload())
                elif u.path == "/api/groups":
                    action = body.get("action", "create")
                    gid = None
                    if action == "create":
                        gid = store.create_group(body.get("name"), body.get("members") or [])
                    elif action == "rename":
                        store.rename_group(body.get("id"), body.get("name"))
                    elif action == "delete":
                        store.delete_group(body.get("id"))
                    out = self.projects_payload()
                    out["id"] = gid
                    self.send_json(out)
                else:
                    self.send_json({"error": "not found"}, 404)
            except (FileNotFoundError, ValueError) as e:
                self.send_json({"error": str(e)}, 400)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"error": str(e)}, 500)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = unquote(u.path)
            try:
                if path == "/" or path == "/index.html":
                    self.send_text(HTML.replace("__EMBEDDED__", "null").replace("__VERSION__", VERSION).replace("__LANG__", LANG))
                elif path == "/api/projects":
                    self.send_json(self.projects_payload())
                elif path.startswith("/api/project/"):
                    pid = path[len("/api/project/"):]
                    p = store.get_project(pid, refresh=q.get("refresh", ["0"])[0] == "1")
                    self.send_json(project_light(p))
                elif path.startswith("/api/details/"):
                    pid = path[len("/api/details/"):]
                    p = store.get_project(pid)
                    ids = q.get("ids", [""])[0]
                    want = set(ids.split(",")) if ids else None
                    out = {}
                    for t in p["turns"]:
                        if want is None or t["id"] in want:
                            out[t["id"]] = turn_details(p, t)
                    self.send_json(out)
                elif path.startswith("/api/image/"):
                    rest = path[len("/api/image/"):]
                    pid, _, sid = rest.partition("/")
                    fp = next((f for f in project_files(store.roots, pid, store.groups) if os.path.basename(f) == sid + ".jsonl"), None)
                    if not fp:
                        raise FileNotFoundError(sid)
                    mt, data = image_from_line(fp, q.get("off", ["0"])[0], q.get("idx", ["0"])[0])
                    self.send_response(200)
                    self.send_header("Content-Type", mt)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                elif path.startswith("/api/search/"):
                    pid = path[len("/api/search/"):]
                    p = store.get_project(pid)
                    self.send_json({"ids": search_project(p, q.get("q", [""])[0], q.get("scope", ["all"])[0])})
                elif path.startswith("/api/csv/"):
                    pid = path[len("/api/csv/"):]
                    mode = q.get("mode", ["prompts"])[0]
                    p = store.get_project(pid)
                    self.send_text(project_csv(p, mode), "text/csv; charset=utf-8",
                                   filename="%s-%s.csv" % (p["name"], mode))
                else:
                    self.send_text("not found", "text/plain; charset=utf-8", 404)
            except FileNotFoundError:
                self.send_json({"error": "not found"}, 404)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"error": str(e)}, 500)
    return Handler


def cmd_serve(args):
    roots = resolve_roots(args.dir, use_saved=not args.no_config)
    missing = [r for r in roots if not os.path.isdir(r)]
    for r in missing:
        sys.stderr.write(_("no_dir") % r + "\n")
    if len(missing) == len(roots):
        sys.exit(_("no_dirs"))
    store = Store([norm_root(d) for d in (args.dir or [DEFAULT_DIR])], use_cache=not args.no_cache)
    if args.no_config:
        store.saved_roots = []
    port = args.port
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((args.host, p), make_handler(store))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit(_("no_port"))
    url = "http://%s:%d/" % ("localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host, port)
    print("cldviewer %s  —  %s" % (VERSION, url))
    for r in store.roots:
        print(_("log") % (r, "" if os.path.isdir(r) else _("missing")))
    print(_("quit"))
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(_("bye"))


def select_projects(roots, keywords, groups=None):
    projects = list_projects(roots, groups)
    if not keywords:
        return projects
    out = []
    for p in projects:
        hay = (p["id"] + " " + p["path"] + " " + p["name"]).lower()
        if any(k.lower() in hay for k in keywords):
            out.append(p)
    return out


def cmd_export(args):
    root = resolve_roots(args.dir, use_saved=not args.no_config)
    groups = [] if args.no_config else load_groups()
    projects = select_projects(root, args.project, groups)
    if not projects:
        sys.exit(_("no_projects"))
    data = {}
    for p in projects:
        sys.stderr.write(_("loading") % p["id"] + "\n")
        full = load_project(root, p["id"], not args.no_cache, None, groups)
        if args.light:
            for t in full["turns"]:
                t["steps"] = [s for s in t["steps"] if s["kind"] in ("text", "compact", "compact_boundary", "interrupt")]
                t["sidechains"] = []
            for s in full["sessions"]:
                s["sidechains"] = {}
        emb = project_light(full)
        emb["light"] = False
        for t, lt in zip(full["turns"], emb["turns"]):
            d = turn_details(full, t)
            lt["steps"] = d["steps"]
            lt["agents"] = d["agents"]
        if args.images:
            files = {os.path.basename(f)[:-6]: f for f in project_files(root, p["id"], groups)}
            n_img = 0
            for lt in emb["turns"]:
                refs = list(lt.get("imageRefs") or [])
                for s in lt.get("steps") or []:
                    refs.extend(s.get("images") or [])
                for r in refs:
                    fp = files.get(lt["sid"])
                    if not fp or "off" not in r:
                        continue
                    try:
                        mt, b = image_from_line(fp, r["off"], r["idx"])
                        r["dataUrl"] = "data:%s;base64,%s" % (mt, base64.b64encode(b).decode("ascii"))
                        n_img += 1
                    except Exception:
                        pass
            sys.stderr.write("  images embedded: %d\n" % n_img)
        data[p["id"]] = emb
    payload = json.dumps({"roots": [{"path": r, "ok": True, "saved": False} for r in root], "projects": projects, "data": data}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    out = HTML.replace("__EMBEDDED__", payload).replace("__VERSION__", VERSION).replace("__LANG__", LANG)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(_("exported") % (args.out, len(out.encode("utf-8")) / 1e6, len(projects)))


def cmd_csv(args):
    root = resolve_roots(args.dir, use_saved=not args.no_config)
    groups = [] if args.no_config else load_groups()
    projects = select_projects(root, args.project, groups)
    if len(projects) != 1:
        print(_("pick_one"))
        for p in projects:
            print("  %s  %s" % (p["id"], p["path"]))
        sys.exit(1)
    p = load_project(root, projects[0]["id"], not args.no_cache, None, groups)
    text = project_csv(p, args.mode)
    out = args.out or "%s-%s.csv" % (p["name"], args.mode)
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print(_("written") % out)


def cmd_list(args):
    roots = resolve_roots(args.dir, use_saved=not args.no_config)
    for r in roots:
        print("# %s%s" % (r, "" if os.path.isdir(r) else _("missing")))
    groups = [] if args.no_config else load_groups()
    for p in list_projects(roots, groups):
        print("%-8s %3d sessions %7.1f MB  %s%s%s" % (p["lastModified"][:10], p["sessionCount"], p["bytes"] / 1e6, p["path"],
                                                     _("places") % len(p["roots"]) if len(p["roots"]) > 1 else "",
                                                     _("group") % p["name"] if p.get("group") else ""))


def main(argv=None):
    global LANG
    argv = list(sys.argv[1:] if argv is None else argv)
    # ヘルプ文にも反映するため、言語だけ先に決める
    env_lang = os.environ.get("CLDVIEWER_LANG", "").lower()
    if env_lang in MSG:
        LANG = env_lang
    for i, a in enumerate(argv):
        if a.startswith("--lang="):
            LANG = a.split("=", 1)[1]
        elif a == "--lang" and i + 1 < len(argv):
            LANG = argv[i + 1]
    if LANG not in MSG:
        LANG = "ja"
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", action="append", help=_("h_dir"))
    common.add_argument("--no-cache", action="store_true", help=_("h_nocache"))
    common.add_argument("--no-config", action="store_true", help=_("h_noconfig"))
    common.add_argument("--lang", choices=["ja", "en"], default=LANG, help=_("h_lang"))
    ap = argparse.ArgumentParser(description=_("desc"), parents=[common])
    sub = ap.add_subparsers(dest="cmd")

    sp = sub.add_parser("serve", help=_("h_serve"), parents=[common])
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--no-browser", action="store_true")

    ep = sub.add_parser("export", help=_("h_export"), parents=[common])
    ep.add_argument("-o", "--out", default="cldviewer-export.html")
    ep.add_argument("--project", nargs="*", default=[], help=_("h_project"))
    ep.add_argument("--light", action="store_true", help=_("h_light"))
    ep.add_argument("--images", action="store_true", help=_("h_images"))

    cp = sub.add_parser("csv", help=_("h_csv"), parents=[common])
    cp.add_argument("--project", nargs="*", default=[], help=_("h_project"))
    cp.add_argument("--mode", choices=["prompts", "pairs", "full"], default="prompts")
    cp.add_argument("-o", "--out")

    sub.add_parser("list", help=_("h_list"), parents=[common])

    # サブコマンドはどの位置にあっても先頭に移す。無ければ serve。
    cmds = ("serve", "export", "csv", "list")
    pos = next((i for i, a in enumerate(argv) if a in cmds), None)
    if pos is not None:
        argv = [argv[pos]] + argv[:pos] + argv[pos + 1:]
    elif not argv or argv[0] not in ("-h", "--help"):
        argv = ["serve"] + argv
    args = ap.parse_args(argv)
    LANG = args.lang
    if args.cmd == "export":
        cmd_export(args)
    elif args.cmd == "csv":
        cmd_csv(args)
    elif args.cmd == "list":
        cmd_list(args)
    else:
        cmd_serve(args)


# ---------------------------------------------------------------------------
# UI（HTML/CSS/JS）
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cldviewer</title>
<style>
:root{
  --bg:#f5f6f8; --panel:#ffffff; --ink:#1d2129; --ink2:#4b525c; --muted:#7a8290; --line:#e1e4e9; --line2:#cfd4db;
  --accent:#2d5fb3; --accent-soft:#e6eefb; --user:#fff8e6; --user-line:#f0d58c; --ai:#eef6ee; --ai-line:#b9dcb9;
  --tool:#f3f4f7; --think:#f7f2fb; --think-line:#d9c7ea; --err:#b3261e; --err-soft:#fbe9e7; --mark:#ffe58a; --pin:#d98b00;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --s1:#3b82f6;--s2:#10b981;--s3:#f59e0b;--s4:#ef4444;--s5:#8b5cf6;--s6:#06b6d4;--s7:#ec4899;--s8:#84cc16;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#15181c; --panel:#1d2126; --ink:#e6e8eb; --ink2:#b8bec6; --muted:#8a919b; --line:#2b3037; --line2:#3a414a;
    --accent:#7ea6e8; --accent-soft:#23324a; --user:#2a2716; --user-line:#5c4f1f; --ai:#1c2a1c; --ai-line:#2f5030;
    --tool:#22262c; --think:#251f2c; --think-line:#4a3a5c; --err:#ff8a80; --err-soft:#3a1f1d; --mark:#7a5d00; --pin:#f2b134;
  }
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Segoe UI",sans-serif}
button,input,select{font:inherit;color:inherit}
button{background:var(--panel);border:1px solid var(--line2);border-radius:6px;padding:3px 10px;cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}
button.icon{padding:2px 7px;border:none;background:transparent;color:var(--muted)}
button.icon:hover{color:var(--accent);background:var(--accent-soft)}
button.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
input[type=text],input[type=search],input[type=date],select{background:var(--panel);border:1px solid var(--line2);border-radius:6px;padding:4px 8px}
a{color:var(--accent)}
.muted{color:var(--muted)}
.small{font-size:12px}
mark{background:var(--mark);color:inherit;border-radius:2px;padding:0 1px}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font-family:var(--mono);font-size:12.5px;line-height:1.5}
#app{display:flex;height:100%}
#side{width:290px;flex:none;border-right:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;min-height:0}
#side.hidden{display:none}
.side-head{display:flex;align-items:center;gap:6px;padding:10px 12px;border-bottom:1px solid var(--line)}
.side-head h1{font-size:16px;margin:0;flex:1}
#side input{margin:8px 12px}
#projList{list-style:none;margin:0;padding:0 6px;overflow:auto;flex:1}
#projList li{padding:8px 10px;border-radius:8px;cursor:pointer;margin-bottom:2px}
#projList li:hover{background:var(--bg)}
#projList li.active{background:var(--accent-soft)}
#projList .pname{font-weight:600}
#projList .ppath{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#projList .pmeta{font-size:11px;color:var(--muted)}
.side-foot{padding:8px 12px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);word-break:break-all}
#suggest{margin:0 12px 6px;padding:6px 8px;border:1px dashed var(--accent);border-radius:8px;background:var(--accent-soft);font-size:12px}
#suggest .srow{display:flex;gap:6px;align-items:center;padding:2px 0}
#suggest .srow .sn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#mergeBar{margin:0 12px 6px;padding:6px 8px;border:1px solid var(--accent);border-radius:8px;background:var(--panel);font-size:12px}
#projList li.sel{display:flex;gap:8px;align-items:flex-start}
#projList li.sel input{margin-top:4px}
#projList li .body{min-width:0;flex:1}
#projList .pmember{font-size:11px;color:var(--muted);padding-left:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badge.group{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
#groupInfo{margin-top:6px;font-size:12px}
#groupInfo .gm{color:var(--ink2);padding-left:6px}
.rootrow{display:flex;gap:4px;align-items:flex-start;padding:2px 0}
.rootrow .rp{flex:1;color:var(--ink2)}
.rootrow.ng .rp{color:var(--err);text-decoration:line-through}
.rootrow button{padding:0 5px;font-size:11px;line-height:1.4}
#main{flex:1;min-width:0;display:flex;flex-direction:column;min-height:0}
#topbar{display:flex;align-items:center;gap:8px;padding:6px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
#scroll{flex:1;overflow:auto;min-height:0}
#empty{padding:60px;text-align:center;color:var(--muted)}
.proj-head{padding:14px 20px 8px}
.proj-head h2{margin:0;font-size:18px}
#sessionChips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line2);border-radius:14px;padding:2px 10px;font-size:12px;cursor:pointer;background:var(--panel)}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent-soft);border-color:var(--accent)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.toolbar{position:sticky;top:0;z-index:5;background:var(--panel);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:8px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.toolbar #q{flex:1;min-width:220px}
.toolbar label{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--ink2);cursor:pointer}
.dropdown{position:relative}
.dropdown .menu{display:none;position:absolute;right:0;top:100%;background:var(--panel);border:1px solid var(--line2);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.15);padding:6px;z-index:20;min-width:260px}
.dropdown.open .menu{display:block}
.dropdown .menu button{display:block;width:100%;text-align:left;border:none;background:none;padding:6px 10px;border-radius:6px}
.dropdown .menu button:hover{background:var(--accent-soft)}
.dropdown .menu hr{border:none;border-top:1px solid var(--line);margin:4px 0}
#timeline{padding:8px 20px 80px;max-width:1200px}
.dayhead{position:sticky;top:52px;z-index:4;margin:18px 0 8px;font-weight:600;color:var(--ink2);background:var(--bg);padding:4px 0;border-bottom:1px solid var(--line)}
.dayhead .cnt{font-weight:400;color:var(--muted);font-size:12px;margin-left:8px}
.turn{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--user-line);border-radius:10px;margin:8px 0;outline:none}
.turn:focus{box-shadow:0 0 0 2px var(--accent)}
.turn.kind-command,.turn.kind-shell{border-left-color:var(--line2)}
.turn.kind-queued{border-left-color:#f59e0b}
.turn.kind-continuation,.turn.kind-auto{border-left-color:var(--line);opacity:.85}
.turn.kind-peer{border-left-color:var(--s6);background:transparent}
.badge.kind-peer{background:#e0f7fa;border-color:#06b6d4;color:#0b6b7a}
.turn.folded .thead{padding-bottom:8px;cursor:pointer;flex-wrap:nowrap}
.turn.folded .preview{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.turn.folded .prompt,.turn.folded .recap,.turn.folded .tbtns,.turn.folded .panel,.turn.folded .morebtn{display:none}
.turn.pinned{border-color:var(--pin)}
.turn.match{box-shadow:inset 0 0 0 1px var(--accent)}
.thead{display:flex;align-items:center;gap:8px;padding:8px 12px 0;flex-wrap:wrap}
.thead .time{font-family:var(--mono);font-size:12px;color:var(--ink2)}
.badge{font-size:11px;border-radius:4px;padding:0 6px;background:var(--tool);color:var(--ink2);border:1px solid var(--line)}
.badge.kind-typed{background:var(--user);border-color:var(--user-line)}
.badge.kind-queued{background:#fff1d6;border-color:#f59e0b;color:#8a5a00}
.badge.err{background:var(--err-soft);color:var(--err);border-color:transparent}
.schip{font-size:11px;display:inline-flex;align-items:center;gap:4px;color:var(--muted)}
.thead .meta{font-size:11px;color:var(--muted);margin-left:auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.prompt{padding:6px 12px 4px;white-space:pre-wrap;word-break:break-word;font-size:14px}
.prompt.clamp{max-height:11.2em;overflow:hidden;position:relative}
.prompt.clamp:after{content:"";position:absolute;left:0;right:0;bottom:0;height:2.4em;background:linear-gradient(transparent,var(--panel))}
.morebtn{margin:0 12px 4px;font-size:12px}
.recap{margin:2px 12px 4px;padding:4px 10px;font-size:12.5px;color:var(--ink2);background:var(--ai);border-left:3px solid var(--ai-line);border-radius:0 6px 6px 0}
.recap b{color:var(--muted);font-weight:500;margin-right:6px}
.tbtns{display:flex;gap:6px;padding:4px 12px 10px;flex-wrap:wrap;align-items:center}
.tbtns .sp{flex:1}
.panel{border-top:1px dashed var(--line);padding:8px 12px 10px}
.panel h4{margin:6px 0 4px;font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.04em}
.resp{background:var(--ai);border:1px solid var(--ai-line);border-radius:8px;padding:8px 12px;margin:6px 0}
.resp .rhead{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--muted);margin-bottom:4px}
.resp .rhead .sp{flex:1}
.md p{margin:.4em 0}
.md h1,.md h2,.md h3,.md h4{margin:.7em 0 .3em;line-height:1.3}
.md h1{font-size:1.25em}.md h2{font-size:1.15em}.md h3{font-size:1.05em}.md h4{font-size:1em}
.md pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:.5em 0;overflow:auto}
.md code{font-family:var(--mono);font-size:.92em;background:rgba(127,127,127,.15);padding:0 4px;border-radius:3px}
.md pre code{background:none;padding:0}
.md ul,.md ol{margin:.3em 0;padding-left:1.6em}
.md blockquote{margin:.4em 0;padding:.2em .8em;border-left:3px solid var(--line2);color:var(--ink2)}
.md table{border-collapse:collapse;margin:.5em 0;font-size:.95em}
.md th,.md td{border:1px solid var(--line2);padding:3px 8px;vertical-align:top}
.md hr{border:none;border-top:1px solid var(--line2);margin:.8em 0}
.step{margin:5px 0;border:1px solid var(--line);border-radius:8px;background:var(--panel);overflow:hidden}
.step.s-tool{background:var(--tool)}
.step.s-thinking{background:var(--think);border-color:var(--think-line)}
.step.s-text{background:var(--ai);border-color:var(--ai-line)}
.step.s-notification,.step.s-system,.step.s-meta{background:transparent;border-style:dashed}
.step.s-interrupt{border-color:var(--err);background:var(--err-soft)}
.step.s-compact{border-color:var(--line2)}
.step.s-compact_boundary{border:none;background:none;text-align:center;color:var(--muted);font-size:12px;padding:4px}
.shead{display:flex;gap:8px;align-items:center;padding:5px 10px;cursor:pointer;font-size:12.5px;flex-wrap:wrap}
.shead .name{font-weight:600;font-family:var(--mono)}
.shead .sum{color:var(--ink2);font-family:var(--mono);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:120px}
.shead .stime{font-family:var(--mono);font-size:11px;color:var(--muted)}
.shead .tri{color:var(--muted);width:12px;display:inline-block}
.sbody{display:none;padding:6px 10px 10px;border-top:1px solid var(--line)}
.step.open .sbody{display:block}
.sbody .lab{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);margin:6px 0 3px}
.sbody .lab .sp{flex:1}
.sbody pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px;max-height:420px;overflow:auto}
.subagent{margin-top:8px;border-left:3px solid var(--accent);padding-left:8px}
.subagent .step{margin:4px 0}
.hidden{display:none !important}
#loading{position:fixed;inset:0;background:rgba(0,0,0,.35);display:none;align-items:center;justify-content:center;z-index:50;color:#fff;font-size:15px}
#loading.show{display:flex}
#loading .box{background:var(--panel);color:var(--ink);padding:18px 26px;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.3)}
.kbd{font-family:var(--mono);font-size:11px;border:1px solid var(--line2);border-radius:4px;padding:0 4px;background:var(--bg)}
#help{position:fixed;right:16px;bottom:16px;background:var(--panel);border:1px solid var(--line2);border-radius:10px;padding:10px 14px;font-size:12px;box-shadow:0 6px 24px rgba(0,0,0,.2);display:none;z-index:30}
#help.show{display:block}
.thumbs{display:flex;flex-wrap:wrap;gap:6px;padding:4px 12px 6px}
.sbody .thumbs{padding:6px 0 0}
.thumbs img{max-height:120px;max-width:220px;border:1px solid var(--line2);border-radius:6px;cursor:zoom-in;background:var(--panel);object-fit:contain}
.thumbs img:hover{border-color:var(--accent)}
.thumbs .noimg{font-size:11px;color:var(--muted);border:1px dashed var(--line2);border-radius:6px;padding:4px 8px}
#lightbox{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;flex-direction:column;z-index:70;cursor:zoom-out}
#lightbox.show{display:flex}
#lightbox .lbbar{display:flex;gap:12px;align-items:center;padding:8px 14px;color:#eee;font-size:12px;cursor:default}
#lightbox .lbbar a{color:#9cc4ff}
#lightbox .lbbar .icon{color:#eee;margin-left:auto;font-size:16px}
#lightbox img{flex:1;min-height:0;object-fit:contain;max-width:100%;padding:0 14px 14px}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:6px 14px;border-radius:20px;font-size:12px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:60}
#toast.show{opacity:1}
@media (max-width:900px){#side{position:absolute;z-index:10;height:100%;box-shadow:0 0 30px rgba(0,0,0,.3)} #timeline{padding:8px 10px 80px} .proj-head{padding:10px 10px 6px} .toolbar{padding:8px 10px}}
</style>
</head>
<body>
<div id="app">
  <aside id="side">
    <div class="side-head">
      <h1>cldviewer</h1>
      <button class="small" id="btnMerge" data-i18n="btnMerge" data-i18n-title="btnMergeTitle"></button>
      <button class="small" id="btnLang" title="Language"></button>
      <button class="icon" id="btnReloadList" data-i18n-title="btnReloadList">↻</button>
    </div>
    <input type="search" id="projFilter" data-i18n-placeholder="projFilter">
    <div id="suggest" class="hidden"></div>
    <div id="mergeBar" class="hidden">
      <div class="small muted" data-i18n="mergeHint"></div>
      <div style="display:flex;gap:4px;margin-top:4px"><input type="text" id="mergeName" data-i18n-placeholder="mergeName" style="flex:1;min-width:0;margin:0"><button class="small" id="btnMergeDo" data-i18n="btnMergeDo"></button><button class="small" id="btnMergeCancel" data-i18n="btnMergeCancel"></button></div>
    </div>
    <ul id="projList"></ul>
    <div class="side-foot">
      <div style="margin-bottom:4px" data-i18n="rootsTitle"></div>
      <div id="roots"></div>
      <div id="rootAdd" style="display:flex;gap:4px;margin-top:6px"><input type="text" id="rootInput" data-i18n-placeholder="rootInput" style="flex:1;min-width:0;margin:0;font-size:11px"><button class="small" id="btnRootAdd" data-i18n="btnRootAdd"></button></div>
      <div style="margin-top:6px">v__VERSION__ · <a href="#" id="btnHelp" data-i18n="btnHelp"></a></div>
    </div>
  </aside>
  <main id="main">
    <div id="topbar">
      <button class="icon" id="btnSide" data-i18n-title="btnSide">☰</button>
      <span id="crumb" class="muted small"></span>
      <span class="sp" style="flex:1"></span>
      <button id="btnRefresh" class="small" data-i18n="btnRefresh" data-i18n-title="btnRefreshTitle"></button>
    </div>
    <div id="scroll">
      <div id="empty" data-i18n="empty"></div>
      <div id="content" class="hidden">
        <header class="proj-head">
          <h2 id="projName"></h2>
          <div id="projPath" class="muted small"></div>
          <div id="groupInfo" class="hidden"></div>
          <div id="sessionChips"></div>
          <div id="projStats" class="muted small" style="margin-top:6px"></div>
        </header>
        <div class="toolbar">
          <input type="search" id="q" data-i18n-placeholder="q">
          <select id="scope">
            <option value="prompt" data-i18n="scopePrompt"></option>
            <option value="response" data-i18n="scopeResponse"></option>
            <option value="all" data-i18n="scopeAll"></option>
          </select>
          <select id="order" data-i18n-title="orderTitle">
            <option value="asc" data-i18n="orderAsc"></option>
            <option value="desc" data-i18n="orderDesc"></option>
          </select>
          <span id="matchCount" class="small muted"></span>
          <input type="date" id="dateFrom" data-i18n-title="dateFrom"> <span class="muted">〜</span> <input type="date" id="dateTo" data-i18n-title="dateTo">
          <label><input type="checkbox" id="pinOnly"> <span data-i18n="pinOnly"></span></label>
          <label><input type="checkbox" id="humanOnly" checked> <span data-i18n="humanOnly"></span></label>
          <label><input type="checkbox" id="showPeer" checked> <span data-i18n="showPeer"></span></label>
          <label><input type="checkbox" id="showSys"> <span data-i18n="showSys"></span></label>
          <label><input type="checkbox" id="showImg" checked> <span data-i18n="showImg"></span></label>
          <span style="flex-basis:100%;height:0"></span>
          <button id="expandResp" class="small" data-i18n="expandResp"></button>
          <button id="expandDetail" class="small" data-i18n="expandDetail"></button>
          <button id="collapseAll" class="small" data-i18n="collapseAll"></button>
          <span class="sp" style="flex:1"></span>
          <div class="dropdown" id="exportDD">
            <button class="small" data-i18n="exportBtn"></button>
            <div class="menu">
              <div class="muted small" style="padding:4px 10px" data-i18n="exportNote"></div>
              <button data-csv="prompts" data-i18n="csvPrompts"></button>
              <button data-csv="pairs" data-i18n="csvPairs"></button>
              <button data-csv="full" data-i18n="csvFull"></button>
              <hr>
              <button data-md="prompts" data-i18n="mdPrompts"></button>
              <button data-md="pairs" data-i18n="mdPairs"></button>
              <hr>
              <button data-plain="prompts" data-i18n="plainPrompts"></button>
            </div>
          </div>
        </div>
        <div id="timeline"></div>
      </div>
    </div>
  </main>
</div>
<div id="loading"><div class="box" id="loadingMsg"></div></div>
<div id="lightbox"><div class="lbbar"><span id="lbCaption"></span><a id="lbOpen" target="_blank" rel="noopener"></a><button class="icon" id="lbClose">✕</button></div><img id="lbImg" alt=""></div>
<div id="help"></div>
<div id="toast"></div>
<script>
const EMBEDDED = __EMBEDDED__;
const DEFAULT_LANG = '__LANG__';
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const HUMAN_KINDS = new Set(['typed','queued','command','shell']);
const I18N = {
ja: {
  langBtn:'EN', btnMerge:'統合…', btnMergeTitle:'複数のプロジェクトを選んで 1 つに統合', btnReloadList:'プロジェクト一覧を再読み込み', projFilter:'プロジェクトを絞り込み',
  mergeHint:'統合するプロジェクトにチェック（2 つ以上）', mergeName:'統合後の名前', btnMergeDo:'統合する', btnMergeCancel:'中止',
  rootsTitle:'ログの場所', rootInput:'追加するディレクトリのパス', btnRootAdd:'追加', btnHelp:'キー操作', btnSide:'サイドバー切替',
  btnRefresh:'ログを更新', btnRefreshTitle:'このプロジェクトのログを再読み込み', empty:'左のリストからプロジェクトを選んでください',
  q:'キーワード検索（スペース区切りで AND）  [/]', scopePrompt:'範囲: 依頼', scopeResponse:'範囲: 応答', scopeAll:'範囲: 全体（推論・ツールログ含む）',
  orderTitle:'並び順', orderAsc:'古い順', orderDesc:'新しい順',
  showImg:'画像を表示', openImage:'新しいタブで開く', imageN:'画像 {n}', noImageData:'画像は書き出し版に含まれていません（export --images で埋め込み可）',
  dateFrom:'開始日', dateTo:'終了日', pinOnly:'ピン留めのみ', humanOnly:'依頼のあるターンのみ', showPeer:'他エージェントからのメッセージ（畳んで表示）', showSys:'通知・システム行を表示',
  expandResp:'応答を全展開', expandDetail:'詳細を全展開', collapseAll:'全て閉じる', exportBtn:'書き出し / コピー ▾', exportNote:'※ 現在の絞り込み結果が対象',
  csvPrompts:'CSV: 依頼のみ', csvPairs:'CSV: 依頼と応答', csvFull:'CSV: 全体（推論・ツールログ含む）', mdPrompts:'Markdown をコピー: 依頼のみ', mdPairs:'Markdown をコピー: 依頼と応答', plainPrompts:'プレーンテキストをコピー: 依頼のみ（1 行 1 依頼）',
  loading:'読み込み中…',
  helpHtml:'<b>キー操作</b><br><span class="kbd">/</span> 検索 &nbsp; <span class="kbd">j</span>/<span class="kbd">k</span> 次/前のターン &nbsp; <span class="kbd">o</span> 応答を開閉 &nbsp; <span class="kbd">d</span> 詳細を開閉 &nbsp; <span class="kbd">p</span> ピン留め &nbsp; <span class="kbd">c</span> 依頼をコピー &nbsp; <span class="kbd">Esc</span> 検索クリア',
  kinds:{typed:'依頼', queued:'依頼(割込)', command:'コマンド', shell:'シェル', peer:'他エージェント', continuation:'継続', auto:'自動'},
  labels:{auto:'（プロンプトなしで開始）', continuation:'（前セッションからの継続）'},
  steps:{text:'応答', thinking:'推論', tool:'ツール', notification:'通知', system:'システム', compact:'圧縮サマリー', compact_boundary:'圧縮', interrupt:'中断', meta:'コマンド展開', prompt:'指示'},
  weekdays:'日月火水木金土', unknownDate:'日時不明',
  sec:'{n}秒', minsec:'{m}分{s}秒', hourmin:'{h}時間{m}分',
  copied:'コピーしました', copiedN:'コピーしました（{n} 文字）', copy:'コピー',
  noEmbedded:'埋め込みデータにありません: ', fetchingDetails:'詳細ログを取得中… ({n} ターン)', fetchingProjects:'プロジェクト一覧を取得中…', loadFailed:'読み込みに失敗しました: ',
  rootMissing:'（見つかりません。ドライブが外れている可能性）', rootRemove:'この場所を外す', rootAdding:'ログの場所を追加中…', updating:'更新中…', added:'追加しました', removed:'外しました', failed:'失敗: ',
  suggestTitle:'統合候補（作業フォルダ名が同じ）', suggestRow:'{name} — {n} 件', merge:'統合', selectTitle:'候補を確認しながら選ぶ', select:'選択',
  groupUpdating:'統合設定を更新中…', merged:'統合しました', unmerged:'統合を解除しました', updated:'更新しました',
  groupBadge:'統合 {n}', pmeta:'{n} セッション · {size} · 最終 {date}', places:' · {n} か所',
  parsing:'ログを解析中… 初回は大きなログで時間がかかります', groupProject:'統合プロジェクト', memberSessions:' （{n} セッション）',
  rename:'名前を変更', renamePrompt:'統合プロジェクトの名前', unmerge:'統合を解除', unmergeConfirm:'統合を解除して元のプロジェクトに戻しますか？（ログは変更されません）',
  allSessions:'すべてのセッション', chipTitle:'{id}\n{from} 〜 {to}\n依頼 {n} 件{cost}{compact}{cont}\n{file}', compactions:' · 圧縮 {n} 回', continuedIn:'\n→ 続き: ',
  stats:'{sessions} セッション · 依頼 {prompts} 件 · ツール呼び出し {tools} 回 · {from} 〜 {to}', statsCost:' · 累計コスト ${cost}', statsRoots:' · ログの場所 ',
  matched:'{n} 件一致', count:'{n} 件', noTurns:'該当するターンがありません', session:'セッション ', unfold:'展開', fold:'畳む',
  images:'画像 {n}', interrupted:'中断', durationTitle:'所要時間', toolsTitle:'ツール呼び出し回数', modelTitle:'モデル', pinTitle:'ピン留め（ピックアップ）', copyPrompt:'⧉ 依頼',
  showFull:'全文を表示', collapse:'折りたたむ', recap:'要約', responses:' 応答 ', details:' 詳細（推論・実行ログ） ', fetching:'取得中…', fetchFailed:'取得に失敗: ',
  noTextResponse:'テキスト応答はありません（ツール実行のみ、または中断）', responsesN:'応答 {n} 件 ', copyAll:'⧉ すべてコピー',
  error:'エラー', subagentN:'サブエージェント {n} 手', input:'入力', command:'コマンド', result:'結果', resultError:'結果（エラー）', copyResult:'⧉ 結果', emptyResult:'（空）', noResult:'結果なし（未完了または記録なし）',
  subagentHead:'サブエージェント {type} {model}: {desc} · {from} 〜 {to}', noSteps:'記録された処理はありません', stepsHead:'ステップ {n}（ツール {tools} · 推論 {thinks}） ', openAll:'全て開く', closeAll:'全て閉じる', subagentLegacy:'サブエージェント {type}: {desc}',
  csvHeadPrompts:['日時','セッション','種別','依頼'], csvHeadPairs:['日時','セッション','種別','依頼','応答日時','応答','要約','所要時間(秒)','ツール回数'], csvHeadFull:['日時','セッション','ターン番号','種類','名前','内容'],
  csvPromptKind:'依頼({k})', csvToolCall:'ツール呼び出し', csvToolResult:'ツール結果', csvToolResultErr:'ツール結果(エラー)',
  mdPromptsTitle:'依頼一覧', mdPairsTitle:'依頼と応答', mdRecap:'> 要約: ', mdResponse:'### 応答 ',
  searching:'検索中…', searchFailed:'検索失敗: ', noMergeEmbedded:'書き出し版では統合できません', selectTwo:'2 つ以上選んでください',
},
en: {
  langBtn:'日本語', btnMerge:'Merge…', btnMergeTitle:'Select several projects and merge them into one', btnReloadList:'Reload project list', projFilter:'Filter projects',
  mergeHint:'Check the projects to merge (2 or more)', mergeName:'Name of merged project', btnMergeDo:'Merge', btnMergeCancel:'Cancel',
  rootsTitle:'Log locations', rootInput:'Directory path to add', btnRootAdd:'Add', btnHelp:'Keys', btnSide:'Toggle sidebar',
  btnRefresh:'Reload logs', btnRefreshTitle:'Re-read the logs of this project', empty:'Select a project from the list on the left',
  q:'Search keywords (space = AND)  [/]', scopePrompt:'Scope: prompts', scopeResponse:'Scope: responses', scopeAll:'Scope: everything (incl. reasoning & tool logs)',
  orderTitle:'Sort order', orderAsc:'Oldest first', orderDesc:'Newest first',
  showImg:'Show images', openImage:'Open in new tab', imageN:'Image {n}', noImageData:'Images are not included in this export (use export --images)',
  dateFrom:'From', dateTo:'To', pinOnly:'Pinned only', humanOnly:'Turns with a prompt only', showPeer:'Messages from other agents (folded)', showSys:'Show notification / system rows',
  expandResp:'Expand all responses', expandDetail:'Expand all details', collapseAll:'Collapse all', exportBtn:'Export / Copy ▾', exportNote:'Applies to the current filtered result',
  csvPrompts:'CSV: prompts only', csvPairs:'CSV: prompts and responses', csvFull:'CSV: everything (incl. reasoning & tool logs)', mdPrompts:'Copy Markdown: prompts only', mdPairs:'Copy Markdown: prompts and responses', plainPrompts:'Copy plain text: prompts only (one per line)',
  loading:'Loading…',
  helpHtml:'<b>Keyboard</b><br><span class="kbd">/</span> search &nbsp; <span class="kbd">j</span>/<span class="kbd">k</span> next/prev turn &nbsp; <span class="kbd">o</span> responses &nbsp; <span class="kbd">d</span> details &nbsp; <span class="kbd">p</span> pin &nbsp; <span class="kbd">c</span> copy prompt &nbsp; <span class="kbd">Esc</span> clear search',
  kinds:{typed:'Prompt', queued:'Prompt (mid-turn)', command:'Command', shell:'Shell', peer:'Other agent', continuation:'Continued', auto:'Auto'},
  labels:{auto:'(started without a prompt)', continuation:'(continued from previous session)'},
  steps:{text:'Response', thinking:'Reasoning', tool:'Tool', notification:'Notice', system:'System', compact:'Compact summary', compact_boundary:'Compacted', interrupt:'Interrupted', meta:'Command expansion', prompt:'Instruction'},
  weekdays:['Sun','Mon','Tue','Wed','Thu','Fri','Sat'], unknownDate:'Unknown date',
  sec:'{n}s', minsec:'{m}m {s}s', hourmin:'{h}h {m}m',
  copied:'Copied', copiedN:'Copied ({n} chars)', copy:'Copy',
  noEmbedded:'Not in embedded data: ', fetchingDetails:'Fetching details… ({n} turns)', fetchingProjects:'Fetching project list…', loadFailed:'Failed to load: ',
  rootMissing:' (not found; the drive may be disconnected)', rootRemove:'Remove this location', rootAdding:'Adding log location…', updating:'Updating…', added:'Added', removed:'Removed', failed:'Failed: ',
  suggestTitle:'Merge candidates (same working folder name)', suggestRow:'{name} — {n} projects', merge:'Merge', selectTitle:'Review candidates before merging', select:'Select',
  groupUpdating:'Updating merge settings…', merged:'Merged', unmerged:'Unmerged', updated:'Updated',
  groupBadge:'merged {n}', pmeta:'{n} sessions · {size} · last {date}', places:' · {n} locations',
  parsing:'Parsing logs… large logs take a while the first time', groupProject:'Merged project', memberSessions:' ({n} sessions)',
  rename:'Rename', renamePrompt:'Name of the merged project', unmerge:'Unmerge', unmergeConfirm:'Unmerge and restore the original projects? (Logs are not modified.)',
  allSessions:'All sessions', chipTitle:'{id}\n{from} – {to}\n{n} prompts{cost}{compact}{cont}\n{file}', compactions:' · compacted {n}×', continuedIn:'\n→ continued in: ',
  stats:'{sessions} sessions · {prompts} prompts · {tools} tool calls · {from} – {to}', statsCost:' · total cost ${cost}', statsRoots:' · locations ',
  matched:'{n} matched', count:'{n}', noTurns:'No matching turns', session:'Session ', unfold:'Expand', fold:'Fold',
  images:'{n} image(s)', interrupted:'Interrupted', durationTitle:'Duration', toolsTitle:'Tool calls', modelTitle:'Model', pinTitle:'Pin (pick up)', copyPrompt:'⧉ Prompt',
  showFull:'Show full text', collapse:'Collapse', recap:'Recap', responses:' Responses ', details:' Details (reasoning & tool log) ', fetching:'Fetching…', fetchFailed:'Fetch failed: ',
  noTextResponse:'No text response (tool calls only, or interrupted)', responsesN:'{n} response(s) ', copyAll:'⧉ Copy all',
  error:'Error', subagentN:'Subagent, {n} steps', input:'Input', command:'Command', result:'Result', resultError:'Result (error)', copyResult:'⧉ Result', emptyResult:'(empty)', noResult:'No result (unfinished or not recorded)',
  subagentHead:'Subagent {type} {model}: {desc} · {from} – {to}', noSteps:'No recorded steps', stepsHead:'{n} steps (tools {tools} · reasoning {thinks}) ', openAll:'Open all', closeAll:'Close all', subagentLegacy:'Subagent {type}: {desc}',
  csvHeadPrompts:['Time','Session','Kind','Prompt'], csvHeadPairs:['Time','Session','Kind','Prompt','Response time','Response','Recap','Duration (s)','Tool calls'], csvHeadFull:['Time','Session','Turn','Type','Name','Content'],
  csvPromptKind:'Prompt ({k})', csvToolCall:'Tool call', csvToolResult:'Tool result', csvToolResultErr:'Tool result (error)',
  mdPromptsTitle:'Prompts', mdPairsTitle:'Prompts and responses', mdRecap:'> Recap: ', mdResponse:'### Response ',
  searching:'Searching…', searchFailed:'Search failed: ', noMergeEmbedded:'Merging is not available in the exported version', selectTwo:'Select two or more',
}};
let LANG = (() => { try{ const v = localStorage.getItem('cldviewer.lang'); if(v && I18N[v]) return v; }catch(e){} return I18N[DEFAULT_LANG] ? DEFAULT_LANG : 'ja'; })();
function tr(key, vars){ let s = I18N[LANG][key]; if(s == null) s = I18N.ja[key]; if(s == null) return key; if(typeof s !== 'string') return s; if(vars) for(const k in vars) s = s.split('{' + k + '}').join(vars[k]); return s; }
function kindLabel(k){ return I18N[LANG].kinds[k] || k; }
function turnLabel(t){ return t.labelKey ? (I18N[LANG].labels[t.labelKey] || t.labelKey) : (t.label || ''); }
function stepLabel(k){ return I18N[LANG].steps[k] || k; }
function applyI18n(){
  document.documentElement.lang = LANG;
  $$('[data-i18n]').forEach(e => e.textContent = tr(e.dataset.i18n));
  $$('[data-i18n-placeholder]').forEach(e => e.placeholder = tr(e.dataset.i18nPlaceholder));
  $$('[data-i18n-title]').forEach(e => e.title = tr(e.dataset.i18nTitle));
  $('#btnLang').textContent = tr('langBtn');
  $('#help').innerHTML = tr('helpHtml');
  $('#loadingMsg').textContent = tr('loading');
}
function setLang(l){
  LANG = l; try{ localStorage.setItem('cldviewer.lang', l); }catch(e){}
  applyI18n(); renderRoots(); renderSuggestions(); renderProjectList();
  if(state.project) renderProject();
}
const SESSION_COLORS = ['--s1','--s2','--s3','--s4','--s5','--s6','--s7','--s8'];

const state = {
  projects: [], roots: [], suggestions: [], project: null, pid: null, mergeMode: false, mergeSel: new Set(),
  sessionFilter: null, open: {},  // turnId -> {r:bool, d:bool}
  pins: new Set(), terms: [], scope: 'prompt',
};

// ------------------------------------------------------------ util
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function pad(n){ return n < 10 ? '0' + n : '' + n; }
function fmtDT(ts){ if(!ts) return ''; const d = new Date(ts); if(isNaN(d)) return ts; return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds()); }
function fmtT(ts){ if(!ts) return ''; const d = new Date(ts); if(isNaN(d)) return ''; return pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds()); }
function fmtDay(ts){ if(!ts) return tr('unknownDate'); const d = new Date(ts); if(isNaN(d)) return tr('unknownDate'); return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' ('+tr('weekdays')[d.getDay()]+')'; }
function dayKey(ts){ if(!ts) return ''; const d = new Date(ts); if(isNaN(d)) return ''; return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
function fmtDur(ms){ if(ms == null) return ''; const s = Math.round(ms/1000); if(s < 60) return tr('sec', {n: s}); const m = Math.floor(s/60); if(m < 60) return tr('minsec', {m, s: pad(s%60)}); return tr('hourmin', {h: Math.floor(m/60), m: pad(m%60)}); }
function fmtBytes(b){ return b > 1e9 ? (b/1e9).toFixed(2)+' GB' : b > 1e6 ? (b/1e6).toFixed(1)+' MB' : Math.round(b/1e3)+' KB'; }
function el(tag, attrs, ...children){
  const e = document.createElement(tag);
  if(attrs) for(const k in attrs){ if(k === 'class') e.className = attrs[k]; else if(k === 'html') e.innerHTML = attrs[k]; else if(k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]); else if(attrs[k] != null) e.setAttribute(k, attrs[k]); }
  for(const c of children){ if(c == null) continue; e.append(c.nodeType ? c : document.createTextNode(String(c))); }
  return e;
}
function toast(msg){ const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 1400); }
async function copyText(text, btn){
  try{ await navigator.clipboard.writeText(text); }
  catch(e){ const ta = el('textarea'); ta.value = text; ta.style.position='fixed'; ta.style.opacity='0'; document.body.append(ta); ta.select(); try{ document.execCommand('copy'); }catch(_){} ta.remove(); }
  toast(text.length > 60 ? tr('copiedN', {n: text.length}) : tr('copied'));
  if(btn){ const o = btn.textContent; btn.textContent = '✓'; setTimeout(() => btn.textContent = o, 900); }
}
function copyBtn(getText, label){ const b = el('button', {class:'icon', title: tr('copy')}, label || '⧉'); b.addEventListener('click', ev => { ev.stopPropagation(); copyText(typeof getText === 'function' ? getText() : getText, b); }); return b; }
function showLoading(msg){ $('#loadingMsg').textContent = msg || tr('loading'); $('#loading').classList.add('show'); }
function hideLoading(){ $('#loading').classList.remove('show'); }
function download(name, text, mime){ const a = el('a', {href: URL.createObjectURL(new Blob([text], {type: mime || 'text/plain;charset=utf-8'})), download: name}); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500); }

// ------------------------------------------------------------ highlight
function hl(text){
  const s = esc(text);
  if(!state.terms.length) return s;
  const re = new RegExp('(' + state.terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
  return s.replace(re, '<mark>$1</mark>');
}
function hlNode(root){
  if(!state.terms.length) return;
  const re = new RegExp('(' + state.terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = []; let n; while((n = walker.nextNode())) if(re.test(n.nodeValue)) nodes.push(n);
  for(const tn of nodes){
    const frag = document.createDocumentFragment(); let last = 0; const v = tn.nodeValue; re.lastIndex = 0; let m;
    while((m = re.exec(v))){ frag.append(v.slice(last, m.index)); frag.append(el('mark', null, m[0])); last = m.index + m[0].length; }
    frag.append(v.slice(last)); tn.replaceWith(frag);
  }
}

// ------------------------------------------------------------ images
function imgSrc(sid, ref){
  if(ref.dataUrl) return ref.dataUrl;
  if(ref.url) return ref.url;
  if(EMBEDDED || ref.off == null) return null;
  return '/api/image/' + encodeURIComponent(state.pid) + '/' + encodeURIComponent(sid) + '?off=' + ref.off + '&idx=' + encodeURIComponent(ref.idx);
}
function renderImages(sid, refs){
  if(!refs || !refs.length || !$('#showImg').checked) return null;
  const box = el('div', {class:'thumbs'});
  refs.forEach((ref, i) => {
    const src = imgSrc(sid, ref);
    if(!src){ box.append(el('span', {class:'noimg', title: tr('noImageData')}, tr('imageN', {n: i + 1}))); return; }
    const img = el('img', {src, loading:'lazy', alt: tr('imageN', {n: i + 1}), title: tr('imageN', {n: i + 1}) + ' (' + (ref.type || '') + ')'});
    img.addEventListener('click', ev => { ev.stopPropagation(); openLightbox(src, tr('imageN', {n: i + 1}) + ' · ' + (ref.type || '')); });
    box.append(img);
  });
  return box;
}
function openLightbox(src, caption){
  $('#lbImg').src = src; $('#lbCaption').textContent = caption || ''; $('#lbOpen').href = src; $('#lbOpen').textContent = tr('openImage');
  $('#lightbox').classList.add('show');
}
function closeLightbox(){ $('#lightbox').classList.remove('show'); $('#lbImg').src = ''; }

// ------------------------------------------------------------ markdown (minimal)
function inline(s){
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, (_, c) => '<code>' + c + '</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/(^|[^\w*])\*([^*\n]+)\*(?!\w)/g, '$1<i>$2</i>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a title="$2">$1</a>');
  return s;
}
function md(src){
  const lines = String(src || '').replace(/\r\n?/g, '\n').split('\n');
  let out = [], i = 0;
  const listStack = [];
  function closeLists(depth){ while(listStack.length > depth){ out.push('</' + listStack.pop() + '>'); } }
  let para = [];
  function flushPara(){ if(para.length){ out.push('<p>' + inline(para.join('\n')).replace(/\n/g, '<br>') + '</p>'); para = []; } }
  while(i < lines.length){
    const line = lines[i];
    let m;
    if((m = line.match(/^\s*(```|~~~)\s*(\S*)/))){
      flushPara(); closeLists(0);
      const fence = m[1]; const buf = []; i++;
      while(i < lines.length && !lines[i].trim().startsWith(fence)){ buf.push(lines[i]); i++; }
      i++;
      out.push('<pre><code' + (m[2] ? ' class="lang-' + esc(m[2]) + '"' : '') + '>' + esc(buf.join('\n')) + '</code></pre>');
      continue;
    }
    if(/^\s*$/.test(line)){ flushPara(); closeLists(0); i++; continue; }
    if((m = line.match(/^(#{1,6})\s+(.*)$/))){ flushPara(); closeLists(0); const l = m[1].length; out.push('<h' + l + '>' + inline(m[2].replace(/\s#+$/, '')) + '</h' + l + '>'); i++; continue; }
    if(/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)){ flushPara(); closeLists(0); out.push('<hr>'); i++; continue; }
    if((m = line.match(/^\s*>\s?(.*)$/))){ flushPara(); closeLists(0); const buf = [m[1]]; i++; while(i < lines.length && /^\s*>/.test(lines[i])){ buf.push(lines[i].replace(/^\s*>\s?/, '')); i++; } out.push('<blockquote>' + md(buf.join('\n')) + '</blockquote>'); continue; }
    if(/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i+1])){
      flushPara(); closeLists(0);
      const cells = l => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => inline(c.trim()));
      let h = '<table><thead><tr>' + cells(line).map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>'; i += 2;
      while(i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])){ h += '<tr>' + cells(lines[i]).map(c => '<td>' + c + '</td>').join('') + '</tr>'; i++; }
      out.push(h + '</tbody></table>'); continue;
    }
    if((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))){
      flushPara();
      const depth = Math.floor(m[1].replace(/\t/g, '  ').length / 2) + 1; const type = /\d/.test(m[2]) ? 'ol' : 'ul';
      while(listStack.length > depth) out.push('</' + listStack.pop() + '>');
      while(listStack.length < depth){ out.push('<' + type + '>'); listStack.push(type); }
      let text = m[3]; i++;
      while(i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) && !/^\s*(```|~~~)/.test(lines[i])){ text += '\n' + lines[i].trim(); i++; }
      out.push('<li>' + inline(text).replace(/\n/g, '<br>') + '</li>'); continue;
    }
    para.push(line); i++;
  }
  flushPara(); closeLists(0);
  return out.join('\n');
}

// ------------------------------------------------------------ data
async function apiProjects(){
  if(EMBEDDED) return {roots: EMBEDDED.roots || [], projects: EMBEDDED.projects, suggestions: []};
  const r = await fetch('/api/projects'); if(!r.ok) throw new Error('projects: ' + r.status); return r.json();
}
async function apiProject(id, refresh){
  if(EMBEDDED){ const p = EMBEDDED.data[id]; if(!p) throw new Error(tr('noEmbedded') + id); return p; }
  const r = await fetch('/api/project/' + encodeURIComponent(id) + (refresh ? '?refresh=1' : ''));
  if(!r.ok) throw new Error('project: ' + r.status); return r.json();
}
async function apiDetails(pid, ids){
  const r = await fetch('/api/details/' + encodeURIComponent(pid) + '?ids=' + encodeURIComponent(ids.join(',')));
  if(!r.ok) throw new Error('details: ' + r.status); return r.json();
}
async function apiSearch(pid, q, scope){
  const r = await fetch('/api/search/' + encodeURIComponent(pid) + '?scope=' + scope + '&q=' + encodeURIComponent(q));
  if(!r.ok) throw new Error('search: ' + r.status); return (await r.json()).ids;
}
async function ensureDetails(turns){
  const need = turns.filter(t => !t.steps);
  if(!need.length) return;
  if(EMBEDDED){ for(const t of need){ t.steps = []; t.agents = []; } return; }
  showLoading(tr('fetchingDetails', {n: need.length}));
  try{
    for(let i = 0; i < need.length; i += 200){
      const chunk = need.slice(i, i + 200);
      const d = await apiDetails(state.pid, chunk.map(t => t.id));
      for(const t of chunk){ const x = d[t.id] || {steps: [], agents: []}; t.steps = x.steps; t.agents = x.agents; t._all = null; }
    }
  } finally { hideLoading(); }
}
function loadPins(pid){ try{ return new Set(JSON.parse(localStorage.getItem('cldviewer.pins.' + pid) || '[]')); }catch(e){ return new Set(); } }
function savePins(){ try{ localStorage.setItem('cldviewer.pins.' + state.pid, JSON.stringify([...state.pins])); }catch(e){} }

// ------------------------------------------------------------ project list
async function loadProjects(){
  showLoading(tr('fetchingProjects'));
  try{ const r = await apiProjects(); applyProjects(r); }
  catch(e){ alert(tr('loadFailed') + e.message); }
  finally{ hideLoading(); }
}
function renderRoots(){
  const box = $('#roots'); box.innerHTML = '';
  for(const r of state.roots){
    const row = el('div', {class:'rootrow' + (r.ok ? '' : ' ng'), title: r.ok ? r.path : r.path + tr('rootMissing')}, el('span', {class:'rp'}, r.path));
    if(r.saved && !EMBEDDED) row.append(el('button', {class:'icon', title: tr('rootRemove'), onclick: () => changeRoot('remove', r.path)}, '×'));
    box.append(row);
  }
  $('#rootAdd').classList.toggle('hidden', !!EMBEDDED);
}
async function changeRoot(action, path){
  if(!path) return;
  showLoading(action === 'add' ? tr('rootAdding') : tr('updating'));
  try{
    const r = await fetch('/api/roots', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action, path})});
    const j = await r.json();
    if(!r.ok) throw new Error(j.error || r.status);
    state.roots = j.roots; state.projects = j.projects; renderRoots(); renderProjectList();
    if(action === 'add') $('#rootInput').value = '';
    if(state.pid){ if(state.projects.some(p => p.id === state.pid)) selectProject(state.pid, true); else { state.project = null; state.pid = null; $('#content').classList.add('hidden'); $('#empty').classList.remove('hidden'); } }
    toast(action === 'add' ? tr('added') : tr('removed'));
  }catch(e){ alert(tr('failed') + e.message); }
  finally{ hideLoading(); }
}
function applyProjects(r){
  state.projects = r.projects; state.roots = r.roots || []; state.suggestions = r.suggestions || [];
  renderRoots(); renderSuggestions(); renderProjectList();
}
function renderSuggestions(){
  const box = $('#suggest'); box.innerHTML = '';
  const list = (state.suggestions || []).filter(s => !state.mergeMode);
  box.classList.toggle('hidden', !list.length || !!EMBEDDED);
  if(!list.length) return;
  box.append(el('div', {class:'muted', style:'margin-bottom:2px'}, tr('suggestTitle')));
  for(const s of list){
    box.append(el('div', {class:'srow'},
      el('span', {class:'sn', title: s.members.map(m => m.path).join('\n')}, tr('suggestRow', {name: s.name, n: s.members.length})),
      el('button', {class:'small', onclick: () => changeGroup({action:'create', name: s.name, members: s.members.map(m => m.id)})}, tr('merge')),
      el('button', {class:'icon', title: tr('selectTitle'), onclick: () => { enterMerge(); for(const m of s.members) state.mergeSel.add(m.id); $('#mergeName').value = s.name; renderProjectList(); }}, tr('select'))));
  }
}
function enterMerge(){ state.mergeMode = true; state.mergeSel = new Set(); $('#mergeBar').classList.remove('hidden'); $('#btnMerge').classList.add('on'); renderSuggestions(); renderProjectList(); }
function exitMerge(){ state.mergeMode = false; state.mergeSel = new Set(); $('#mergeBar').classList.add('hidden'); $('#btnMerge').classList.remove('on'); $('#mergeName').value = ''; renderSuggestions(); renderProjectList(); }
async function changeGroup(payload){
  showLoading(tr('groupUpdating'));
  try{
    const r = await fetch('/api/groups', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const j = await r.json();
    if(!r.ok) throw new Error(j.error || r.status);
    if(state.mergeMode) exitMerge();
    applyProjects(j);
    if(payload.action === 'create' && j.id) await selectProject(j.id, true);
    else if(payload.action === 'delete'){ state.project = null; state.pid = null; $('#content').classList.add('hidden'); $('#empty').classList.remove('hidden'); location.hash = ''; renderProjectList(); }
    else if(state.pid) await selectProject(state.pid, true);
    toast(payload.action === 'create' ? tr('merged') : payload.action === 'delete' ? tr('unmerged') : tr('updated'));
  }catch(e){ alert(tr('failed') + e.message); }
  finally{ hideLoading(); }
}
function renderProjectList(){
  const f = $('#projFilter').value.trim().toLowerCase();
  const ul = $('#projList'); ul.innerHTML = '';
  for(const p of state.projects){
    const hay = (p.name + ' ' + p.path + ' ' + (p.members || []).map(m => m.path).join(' ')).toLowerCase();
    if(f && !hay.includes(f)) continue;
    const body = el('div', {class:'body'},
      el('div', {class:'pname'}, p.name, p.group ? el('span', {class:'badge group', style:'margin-left:6px'}, tr('groupBadge', {n: p.members.length})) : null),
      p.group ? null : el('div', {class:'ppath'}, p.path),
      el('div', {class:'pmeta'}, tr('pmeta', {n: p.sessionCount, size: fmtBytes(p.bytes), date: fmtDT(p.lastModified).slice(0,16)}) + ((p.roots || []).length > 1 ? tr('places', {n: p.roots.length}) : '')));
    if(p.group) for(const m of p.members) body.append(el('div', {class:'pmember', title: m.path}, '└ ' + m.path));
    const li = el('li', {class: (p.id === state.pid ? 'active' : '') + (state.mergeMode ? ' sel' : ''), title: p.group ? p.members.map(m => m.path).join('\n') : p.path});
    if(state.mergeMode){
      const cb = el('input', {type:'checkbox'}); cb.checked = state.mergeSel.has(p.id);
      cb.addEventListener('change', () => { if(cb.checked) state.mergeSel.add(p.id); else state.mergeSel.delete(p.id); if(!$('#mergeName').value && cb.checked) $('#mergeName').value = p.name.replace(/\s*\(.*\)$/, ''); });
      li.append(cb); li.addEventListener('click', ev => { if(ev.target !== cb){ cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); } });
    } else li.addEventListener('click', () => selectProject(p.id));
    li.append(body);
    ul.append(li);
  }
}

// ------------------------------------------------------------ project
async function selectProject(pid, refresh){
  showLoading(tr('parsing'));
  try{
    const p = await apiProject(pid, refresh);
    state.project = p; state.pid = pid; state.sessionFilter = null; state.open = {}; state.pins = loadPins(pid);
    for(const t of p.turns){ t._all = null; }
    location.hash = 'p=' + encodeURIComponent(pid);
    renderProjectList();
    renderProject();
  }catch(e){ alert(tr('loadFailed') + e.message); }
  finally{ hideLoading(); }
}
function sessionIndex(sid){ return state.project.sessions.findIndex(s => s.id === sid); }
function sessionColor(sid){ const i = sessionIndex(sid); return 'var(' + SESSION_COLORS[(i < 0 ? 0 : i) % SESSION_COLORS.length] + ')'; }
function sessionLabel(sid){ const i = sessionIndex(sid); return 'S' + (i + 1); }

function renderProject(){
  const p = state.project;
  $('#empty').classList.add('hidden'); $('#content').classList.remove('hidden');
  $('#projName').textContent = p.name; $('#projPath').textContent = p.group ? tr('groupProject') : p.path; $('#crumb').textContent = p.name;
  const gi = $('#groupInfo'); gi.innerHTML = ''; gi.classList.toggle('hidden', !p.group);
  if(p.group){
    p.members.forEach((m, i) => gi.append(el('div', {class:'gm'}, el('span', {class:'badge'}, '📂' + (i+1)), ' ' + m.path + tr('memberSessions', {n: m.sessionCount}))));
    if(!EMBEDDED) gi.append(el('div', {style:'margin-top:4px;display:flex;gap:6px'},
      el('button', {class:'small', onclick: () => { const n = prompt(tr('renamePrompt'), p.name); if(n != null && n.trim()) changeGroup({action:'rename', id: p.id, name: n}); }}, tr('rename')),
      el('button', {class:'small', onclick: () => { if(confirm(tr('unmergeConfirm'))) changeGroup({action:'delete', id: p.id}); }}, tr('unmerge'))));
  }
  const chips = $('#sessionChips'); chips.innerHTML = '';
  const all = el('button', {class:'chip' + (state.sessionFilter ? '' : ' on'), onclick: () => { state.sessionFilter = null; renderProject(); }}, tr('allSessions'));
  chips.append(all);
  p.sessions.forEach((s, i) => {
    const turns = p.turns.filter(t => t.sid === s.id && HUMAN_KINDS.has(t.kind)).length;
    const cost = s.cost && s.cost.usd != null ? ' · $' + s.cost.usd.toFixed(2) : '';
    const title = tr('chipTitle', {id: s.id, from: fmtDT(s.firstTs), to: fmtDT(s.lastTs), n: turns, cost, compact: s.compactions ? tr('compactions', {n: s.compactions}) : '', cont: s.continuedIn ? tr('continuedIn') + s.continuedIn : '', file: s.file});
    const multi = (p.roots || []).length > 1;
    const mi = p.group ? p.members.findIndex(m => m.id === s.projectDir) : -1;
    const c = el('button', {class:'chip' + (state.sessionFilter === s.id ? ' on' : ''), title, onclick: () => { state.sessionFilter = state.sessionFilter === s.id ? null : s.id; renderProject(); }},
      el('span', {class:'dot', style:'background:' + sessionColor(s.id)}), `S${i+1} `, el('span', {class:'muted'}, (s.title || s.id.slice(0,8)).slice(0, 28)), el('span', {class:'muted'}, ` ${fmtDT(s.firstTs).slice(0,10)} · ${turns}`),
      mi >= 0 ? el('span', {class:'badge', title: p.members[mi].path}, '📂' + (mi + 1)) : null,
      multi ? el('span', {class:'badge', title: s.root}, '📁' + (p.roots.indexOf(s.root) + 1)) : null);
    chips.append(c);
  });
  const human = p.turns.filter(t => HUMAN_KINDS.has(t.kind));
  const first = p.turns.length ? p.turns[0].ts : null, last = p.turns.length ? p.turns[p.turns.length-1].endTs || p.turns[p.turns.length-1].ts : null;
  const cost = p.sessions.reduce((a, s) => a + ((s.cost && s.cost.usd) || 0), 0);
  const tools = p.turns.reduce((a, t) => a + (t.toolCount || 0), 0);
  $('#projStats').textContent = tr('stats', {sessions: p.sessions.length, prompts: human.length, tools, from: fmtDT(first).slice(0,10), to: fmtDT(last).slice(0,10)}) + (cost ? tr('statsCost', {cost: cost.toFixed(2)}) : '') + ((p.roots || []).length > 1 ? tr('statsRoots') + p.roots.map((r, i) => '📁' + (i+1) + ' ' + r).join('  ') : '');
  renderTimeline();
}

// ------------------------------------------------------------ filtering / search
function stepText(s){
  let t = '';
  if(s.text) t += s.text + '\n';
  if(s.kind === 'tool'){ t += (s.name || '') + '\n' + (typeof s.input === 'string' ? s.input : JSON.stringify(s.input || {})) + '\n' + (s.result || '') + '\n'; if(s.subagent) t += (s.subagent.description || '') + '\n' + s.subagent.steps.map(stepText).join('\n'); }
  return t;
}
function turnText(t, scope){
  if(scope === 'prompt') return t.prompt || '';
  if(scope === 'response') return t.responses.map(r => r.text).join('\n');
  if(t._all == null){
    const sc = (t.agents || []).map(a => (a.description || '') + '\n' + a.steps.map(stepText).join('\n')).join('\n');
    t._all = (t.prompt || '') + '\n' + (t.recap || '') + '\n' + (t.steps || []).map(stepText).join('\n') + sc;
  }
  return t._all;
}
function matches(t){
  if(!state.terms.length) return true;
  if(state.scope === 'all' && !EMBEDDED) return state.allMatch ? state.allMatch.has(t.id) : true;
  const hay = turnText(t, state.scope).toLowerCase();
  return state.terms.every(k => hay.includes(k));
}
function visibleTurnsAsc(){
  const p = state.project; if(!p) return [];
  const from = $('#dateFrom').value, to = $('#dateTo').value;
  const pinOnly = $('#pinOnly').checked, humanOnly = $('#humanOnly').checked, showPeer = $('#showPeer').checked;
  return p.turns.filter(t => {
    if(state.sessionFilter && t.sid !== state.sessionFilter) return false;
    if(t.kind === 'peer'){ if(!showPeer) return false; }
    else if(humanOnly && !HUMAN_KINDS.has(t.kind)) return false;
    if(pinOnly && !state.pins.has(t.id)) return false;
    const dk = dayKey(t.ts);
    if(from && dk && dk < from) return false;
    if(to && dk && dk > to) return false;
    return matches(t);
  });
}
function visibleTurns(){
  const list = visibleTurnsAsc();
  return $('#order').value === 'desc' ? list.slice().reverse() : list;
}

// ------------------------------------------------------------ timeline
function renderTimeline(){
  const tl = $('#timeline'); tl.innerHTML = '';
  const turns = visibleTurns();
  const hasQ = state.terms.length > 0;
  $('#matchCount').textContent = hasQ ? tr('matched', {n: turns.length}) : tr('count', {n: turns.length});
  let lastDay = null; let dayCount = 0; let dayHead = null;
  const frag = document.createDocumentFragment();
  for(const t of turns){
    const dk = dayKey(t.ts);
    if(dk !== lastDay){
      if(dayHead) dayHead.querySelector('.cnt').textContent = tr('count', {n: dayCount});
      dayHead = el('div', {class:'dayhead'}, fmtDay(t.ts), el('span', {class:'cnt'}, ''));
      frag.append(dayHead); lastDay = dk; dayCount = 0;
    }
    dayCount++;
    if(hasQ){ const o = state.open[t.id] || (state.open[t.id] = {}); if(state.scope === 'response') o.r = true; if(state.scope === 'all') o.d = true; }
    frag.append(renderTurn(t));
  }
  if(dayHead) dayHead.querySelector('.cnt').textContent = tr('count', {n: dayCount});
  if(!turns.length) frag.append(el('div', {class:'muted', style:'padding:30px;text-align:center'}, tr('noTurns')));
  tl.append(frag);
}
function renderTurn(t){
  const o = state.open[t.id] || {};
  const folded = t.kind === 'peer' && !o.unfold && !state.terms.length;
  const card = el('article', {class:'turn kind-' + t.kind + (state.pins.has(t.id) ? ' pinned' : '') + (state.terms.length ? ' match' : '') + (folded ? ' folded' : ''), id:'t-' + t.id, tabindex:0, 'data-id': t.id});
  const head = el('div', {class:'thead'},
    el('span', {class:'time', title: t.ts}, fmtT(t.ts)),
    el('span', {class:'badge kind-' + t.kind}, kindLabel(t.kind) + (t.sender ? ': ' + t.sender : '')),
    el('span', {class:'schip', title: tr('session') + t.sid}, el('span', {class:'dot', style:'background:' + sessionColor(t.sid)}), sessionLabel(t.sid)),
  );
  if(t.kind === 'peer'){
    const tog = el('button', {class:'icon', title: folded ? tr('unfold') : tr('fold'), onclick: ev => { ev.stopPropagation(); const oo = state.open[t.id] || (state.open[t.id] = {}); oo.unfold = !oo.unfold; card.replaceWith(renderTurn(t)); }}, folded ? '▸' : '▾');
    head.prepend(tog);
    if(folded){ head.append(el('span', {class:'preview muted'}, (t.prompt || '').split('\n').find(l => l.trim()) || '')); head.addEventListener('click', ev => { if(ev.target.closest('button')) return; tog.click(); }); }
  }
  if(t.images) head.append(el('span', {class:'badge'}, tr('images', {n: t.images})));
  if(t.interrupted) head.append(el('span', {class:'badge err'}, tr('interrupted')));
  const meta = el('span', {class:'meta'});
  if(t.durationMs != null) meta.append(el('span', {title: tr('durationTitle')}, '⏱ ' + fmtDur(t.durationMs)));
  if(t.toolCount) meta.append(el('span', {title: tr('toolsTitle')}, '🔧 ' + t.toolCount));
  if(t.model) meta.append(el('span', {title: tr('modelTitle')}, t.model.replace(/^claude-/, '')));
  const pinB = el('button', {class:'icon', title: tr('pinTitle'), onclick: ev => { ev.stopPropagation(); togglePin(t, card); }}, state.pins.has(t.id) ? '★' : '☆');
  pinB.style.color = state.pins.has(t.id) ? 'var(--pin)' : '';
  meta.append(pinB, copyBtn(() => t.prompt, tr('copyPrompt')));
  head.append(meta);
  card.append(head);

  const ptext = t.prompt || turnLabel(t);
  const prompt = el('div', {class:'prompt', html: hl(ptext)});
  const long = ptext.length > 500 || (ptext.match(/\n/g) || []).length > 7;
  if(long && !state.terms.length){ prompt.classList.add('clamp'); const mb = el('button', {class:'morebtn small', onclick: () => { const c = prompt.classList.toggle('clamp'); mb.textContent = c ? tr('showFull') : tr('collapse'); }}, tr('showFull')); card.append(prompt, mb); }
  else card.append(prompt);
  const thumbs = renderImages(t.sid, t.imageRefs); if(thumbs) card.append(thumbs);
  if(t.recap) card.append(el('div', {class:'recap', html: '<b>' + tr('recap') + '</b>' + hl(t.recap)}));

  const nResp = t.responses.length, nSteps = t.stepCount != null ? t.stepCount : (t.steps || []).length;
  const btnR = el('button', {class:'small' + (o.r ? ' on' : ''), onclick: () => toggle(t, card, 'r')}, (o.r ? '▾' : '▸') + tr('responses') + nResp);
  const btnD = el('button', {class:'small' + (o.d ? ' on' : ''), onclick: () => toggle(t, card, 'd')}, (o.d ? '▾' : '▸') + tr('details') + nSteps);
  const btns = el('div', {class:'tbtns'}, btnR, btnD, el('span', {class:'sp'}), el('span', {class:'muted small', title: t.ts}, fmtDT(t.ts)));
  card.append(btns);
  const pr = el('div', {class:'panel panel-r' + (o.r ? '' : ' hidden')}); const pd = el('div', {class:'panel panel-d' + (o.d ? '' : ' hidden')});
  card.append(pr, pd);
  if(o.r) fillResponses(t, pr);
  if(o.d){ if(t.steps) fillDetails(t, pd); else { pd.textContent = tr('fetching'); ensureDetails([t]).then(() => fillDetails(t, pd)).catch(e => pd.textContent = tr('fetchFailed') + e.message); } }
  return card;
}
async function toggle(t, card, which){
  const o = state.open[t.id] || (state.open[t.id] = {});
  o[which] = !o[which];
  const panel = card.querySelector(which === 'r' ? '.panel-r' : '.panel-d');
  const btn = card.querySelectorAll('.tbtns button')[which === 'r' ? 0 : 1];
  btn.classList.toggle('on', o[which]); btn.textContent = (o[which] ? '▾' : '▸') + btn.textContent.slice(1);
  panel.classList.toggle('hidden', !o[which]);
  if(o[which] && !panel.childNodes.length){
    if(which === 'r') fillResponses(t, panel);
    else { if(!t.steps){ panel.textContent = tr('fetching'); try{ await ensureDetails([t]); }catch(e){ panel.textContent = tr('fetchFailed') + e.message; return; } } fillDetails(t, panel); }
  }
}
function togglePin(t, card){
  if(state.pins.has(t.id)) state.pins.delete(t.id); else state.pins.add(t.id);
  savePins();
  const b = card.querySelector('.thead .meta button'); b.textContent = state.pins.has(t.id) ? '★' : '☆'; b.style.color = state.pins.has(t.id) ? 'var(--pin)' : '';
  card.classList.toggle('pinned', state.pins.has(t.id));
  if($('#pinOnly').checked) renderTimeline();
}
function fillResponses(t, panel){
  panel.innerHTML = '';
  if(!t.responses.length){ panel.append(el('div', {class:'muted small'}, tr('noTextResponse'))); return; }
  const all = () => t.responses.map(r => r.text).join('\n\n');
  panel.append(el('h4', null, tr('responsesN', {n: t.responses.length}), copyBtn(all, tr('copyAll'))));
  t.responses.forEach((r, i) => {
    const body = el('div', {class:'md', html: md(r.text)}); hlNode(body);
    panel.append(el('div', {class:'resp'}, el('div', {class:'rhead'}, el('span', null, '#' + (i+1)), el('span', {title: r.ts}, fmtDT(r.ts)), el('span', {class:'sp'}), copyBtn(() => r.text)), body));
  });
}
function toolSummary(s){
  const inp = s.input || {};
  if(typeof inp === 'string') return inp.split('\n')[0];
  const pick = inp.command || inp.file_path || inp.path || inp.pattern || inp.description || inp.prompt || inp.query || inp.url || inp.title || inp.skill;
  if(pick) return String(pick).split('\n')[0];
  const k = Object.keys(inp); if(!k.length) return '';
  const v = inp[k[0]]; return k[0] + ': ' + (typeof v === 'string' ? v.split('\n')[0] : JSON.stringify(v));
}
function renderStep(s, depth, sid){
  const showSys = $('#showSys').checked;
  if(!showSys && (s.kind === 'notification' || s.kind === 'system' || s.kind === 'meta')) return null;
  if(s.kind === 'compact_boundary') return el('div', {class:'step s-compact_boundary'}, '— ' + s.text + ' —');
  const step = el('div', {class:'step s-' + s.kind});
  const head = el('div', {class:'shead'}, el('span', {class:'tri'}, '▸'), el('span', {class:'badge'}, stepLabel(s.kind)));
  const body = el('div', {class:'sbody'});
  head.addEventListener('click', ev => { if(ev.target.closest('button')) return; step.classList.toggle('open'); head.querySelector('.tri').textContent = step.classList.contains('open') ? '▾' : '▸'; });
  if(s.kind === 'tool'){
    const inputStr = typeof s.input === 'string' ? s.input : JSON.stringify(s.input || {}, null, 2);
    const cmd = s.input && typeof s.input === 'object' && typeof s.input.command === 'string' ? s.input.command : null;
    head.append(el('span', {class:'name'}, s.name || '?'), el('span', {class:'sum', html: hl(toolSummary(s))}));
    if(s.isError) head.append(el('span', {class:'badge err'}, tr('error')));
    if(s.subagent) head.append(el('span', {class:'badge'}, tr('subagentN', {n: s.subagent.steps.length})));
    const dur = s.resultTs && s.ts ? new Date(s.resultTs) - new Date(s.ts) : null;
    head.append(el('span', {class:'stime', title: s.ts}, fmtT(s.ts) + (dur != null && dur >= 0 ? ' · ' + fmtDur(dur) : '')));
    body.append(el('div', {class:'lab'}, tr('input'), el('span', {class:'sp'}), copyBtn(() => cmd != null ? cmd : inputStr, '⧉ ' + (cmd != null ? tr('command') : tr('input')))));
    body.append(el('pre', {html: hl(cmd != null && Object.keys(s.input).length <= 2 ? cmd + (s.input.description ? '\n# ' + s.input.description : '') : inputStr)}));
    if(s.result != null){
      body.append(el('div', {class:'lab'}, s.isError ? tr('resultError') : tr('result'), el('span', {class:'sp'}), s.resultTs ? el('span', null, fmtT(s.resultTs)) : null, copyBtn(() => s.result, tr('copyResult'))));
      body.append(el('pre', {html: hl(s.result || tr('emptyResult'))}));
      const th = renderImages(sid, s.images); if(th) body.append(th);
    } else body.append(el('div', {class:'lab'}, tr('noResult')));
    if(s.subagent){
      const a = s.subagent;
      const sub = el('div', {class:'subagent'}, el('div', {class:'lab'}, tr('subagentHead', {type: a.type || '', model: a.model ? '(' + a.model + ')' : '', desc: a.description || '', from: fmtDT(a.firstTs), to: fmtT(a.lastTs)})));
      for(const ss of a.steps){ const n = renderStep(ss, (depth || 0) + 1, sid); if(n) sub.append(n); }
      body.append(sub);
    }
  } else {
    const first = (s.text || '').split('\n').find(l => l.trim()) || '';
    if(s.name) head.append(el('span', {class:'name'}, s.name));
    if(s.status) head.append(el('span', {class:'badge'}, s.status));
    head.append(el('span', {class:'sum', html: hl(first.slice(0, 200))}), el('span', {class:'stime', title: s.ts}, fmtT(s.ts)));
    if(s.kind === 'text' || s.kind === 'prompt'){ const b = el('div', {class:'md', html: md(s.text)}); hlNode(b); body.append(el('div', {class:'lab'}, el('span', {class:'sp'}), copyBtn(() => s.text)), b); }
    else body.append(el('div', {class:'lab'}, el('span', {class:'sp'}), copyBtn(() => s.text)), el('pre', {html: hl(s.text || '')}));
  }
  step.append(head, body);
  if(state.terms.length && state.scope === 'all' && s.kind !== 'text'){ const hay = stepText(s).toLowerCase(); if(state.terms.some(k => hay.includes(k))){ step.classList.add('open'); head.querySelector('.tri').textContent = '▾'; } }
  return step;
}
function fillDetails(t, panel){
  panel.innerHTML = '';
  if(!(t.steps || []).length && !(t.agents || []).length){ panel.append(el('div', {class:'muted small'}, tr('noSteps'))); return; }
  const tools = t.steps.filter(s => s.kind === 'tool').length, thinks = t.steps.filter(s => s.kind === 'thinking').length;
  const h = el('h4', null, tr('stepsHead', {n: t.steps.length, tools, thinks}));
  const openAll = el('button', {class:'icon small', onclick: () => { const on = !panel._allOpen; panel._allOpen = on; $$('.step', panel).forEach(st => { st.classList.toggle('open', on); const tri = st.querySelector('.tri'); if(tri) tri.textContent = on ? '▾' : '▸'; }); openAll.textContent = on ? tr('closeAll') : tr('openAll'); }}, tr('openAll'));
  h.append(openAll);
  panel.append(h);
  for(const s of t.steps){ const n = renderStep(s, 0, t.sid); if(n) panel.append(n); }
  for(const a of (t.agents || [])){
    const sub = el('div', {class:'subagent'}, el('div', {class:'lab'}, tr('subagentLegacy', {type: a.type || '', desc: a.description || a.id})));
    for(const ss of a.steps){ const n = renderStep(ss, 1, t.sid); if(n) sub.append(n); }
    panel.append(sub);
  }
}

// ------------------------------------------------------------ export
function csvEscape(v){ v = String(v == null ? '' : v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
function stitle(sid){ const s = state.project.sessions.find(x => x.id === sid); return s ? (s.title || s.id.slice(0,8)) : sid; }
async function exportCSV(mode){
  const turns = visibleTurns(); const rows = [];
  if(mode === 'full'){ try{ await ensureDetails(turns); }catch(e){ alert(tr('fetchFailed') + e.message); return; } }
  if(mode === 'prompts'){
    rows.push(tr('csvHeadPrompts'));
    for(const t of turns) rows.push([fmtDT(t.ts), stitle(t.sid), kindLabel(t.kind), t.prompt || turnLabel(t)]);
  } else if(mode === 'pairs'){
    rows.push(tr('csvHeadPairs'));
    for(const t of turns) rows.push([fmtDT(t.ts), stitle(t.sid), kindLabel(t.kind), t.prompt || turnLabel(t), t.responses.length ? fmtDT(t.responses[t.responses.length-1].ts) : '', t.responses.map(r => r.text).join('\n\n'), t.recap || '', t.durationMs != null ? Math.round(t.durationMs/1000) : '', t.toolCount]);
  } else {
    rows.push(tr('csvHeadFull'));
    turns.forEach((t, i) => {
      rows.push([fmtDT(t.ts), stitle(t.sid), i+1, tr('csvPromptKind', {k: kindLabel(t.kind)}), '', t.prompt || turnLabel(t)]);
      for(const s of (t.steps || [])){
        if(s.kind === 'tool'){
          rows.push([fmtDT(s.ts), stitle(t.sid), i+1, tr('csvToolCall'), s.name, typeof s.input === 'string' ? s.input : JSON.stringify(s.input)]);
          if(s.result != null) rows.push([fmtDT(s.resultTs || s.ts), stitle(t.sid), i+1, s.isError ? tr('csvToolResultErr') : tr('csvToolResult'), s.name, s.result]);
        } else rows.push([fmtDT(s.ts), stitle(t.sid), i+1, stepLabel(s.kind), s.name || '', s.text || '']);
      }
    });
  }
  const text = '﻿' + rows.map(r => r.map(csvEscape).join(',')).join('\r\n');
  download(`${state.project.name}-${mode}-${dayKey(new Date().toISOString())}.csv`, text, 'text/csv;charset=utf-8');
}
function exportMD(mode){
  const turns = visibleTurns(); const out = [`# ${state.project.name} — ${mode === 'prompts' ? tr('mdPromptsTitle') : tr('mdPairsTitle')}`, ''];
  for(const t of turns){
    out.push(`## ${fmtDT(t.ts)} [${kindLabel(t.kind)}] (${sessionLabel(t.sid)})`, '', t.prompt || turnLabel(t), '');
    if(mode === 'pairs'){ if(t.recap) out.push(tr('mdRecap') + t.recap, ''); for(const r of t.responses) out.push(tr('mdResponse') + fmtDT(r.ts), '', r.text, ''); }
  }
  copyText(out.join('\n'));
}
function exportPlain(){ copyText(visibleTurns().map(t => (t.prompt || turnLabel(t)).replace(/\s*\n\s*/g, ' ')).join('\n')); }

// ------------------------------------------------------------ events
let searchSeq = 0;
async function applySearch(){
  const q = $('#q').value.trim();
  state.terms = q ? q.split(/\s+/).map(s => s.toLowerCase()) : [];
  state.scope = $('#scope').value;
  state.allMatch = null;
  if(!state.project) return;
  if(state.scope === 'all' && state.terms.length && !EMBEDDED){
    const seq = ++searchSeq; $('#matchCount').textContent = tr('searching');
    try{ const ids = await apiSearch(state.pid, q, 'all'); if(seq !== searchSeq) return; state.allMatch = new Set(ids); }
    catch(e){ $('#matchCount').textContent = tr('searchFailed') + e.message; return; }
    const vs = visibleTurns();
    try{ await ensureDetails(vs); }catch(e){}
    if(seq !== searchSeq) return;
  }
  renderTimeline();
}
let searchTimer;
$('#q').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(applySearch, 250); });
$('#scope').addEventListener('change', applySearch);
for(const id of ['dateFrom','dateTo','pinOnly','humanOnly','showPeer','showSys']) $('#' + id).addEventListener('change', () => { if(state.project) renderTimeline(); });
try{ const v = localStorage.getItem('cldviewer.showImg'); if(v === '0') $('#showImg').checked = false; }catch(e){}
$('#showImg').addEventListener('change', () => { try{ localStorage.setItem('cldviewer.showImg', $('#showImg').checked ? '1' : '0'); }catch(e){} if(state.project) renderTimeline(); });
$('#lightbox').addEventListener('click', ev => { if(!ev.target.closest('a')) closeLightbox(); });
$('#lbClose').addEventListener('click', closeLightbox);
try{ const o = localStorage.getItem('cldviewer.order'); if(o === 'asc' || o === 'desc') $('#order').value = o; }catch(e){}
$('#order').addEventListener('change', () => { try{ localStorage.setItem('cldviewer.order', $('#order').value); }catch(e){} if(state.project) renderTimeline(); });
$('#projFilter').addEventListener('input', renderProjectList);
$('#btnReloadList').addEventListener('click', loadProjects);
$('#btnRootAdd').addEventListener('click', () => changeRoot('add', $('#rootInput').value.trim()));
$('#btnMerge').addEventListener('click', () => { if(EMBEDDED){ toast(tr('noMergeEmbedded')); return; } state.mergeMode ? exitMerge() : enterMerge(); });
$('#btnMergeCancel').addEventListener('click', exitMerge);
$('#btnLang').addEventListener('click', () => setLang(LANG === 'ja' ? 'en' : 'ja'));
$('#btnMergeDo').addEventListener('click', () => { if(state.mergeSel.size < 2){ alert(tr('selectTwo')); return; } changeGroup({action:'create', name: $('#mergeName').value.trim(), members: [...state.mergeSel]}); });
$('#rootInput').addEventListener('keydown', ev => { if(ev.key === 'Enter') changeRoot('add', $('#rootInput').value.trim()); });
$('#btnRefresh').addEventListener('click', () => { if(state.pid) selectProject(state.pid, true); });
$('#btnSide').addEventListener('click', () => $('#side').classList.toggle('hidden'));
$('#btnHelp').addEventListener('click', ev => { ev.preventDefault(); $('#help').classList.toggle('show'); });
$('#expandResp').addEventListener('click', () => { for(const t of visibleTurns()) (state.open[t.id] || (state.open[t.id] = {})).r = true; renderTimeline(); });
$('#expandDetail').addEventListener('click', async () => { const vs = visibleTurns(); try{ await ensureDetails(vs); }catch(e){ alert(tr('fetchFailed') + e.message); return; } for(const t of vs) { const o = state.open[t.id] || (state.open[t.id] = {}); o.r = true; o.d = true; } renderTimeline(); });
$('#collapseAll').addEventListener('click', () => { state.open = {}; renderTimeline(); });
$('#exportDD > button').addEventListener('click', ev => { ev.stopPropagation(); $('#exportDD').classList.toggle('open'); });
document.addEventListener('click', ev => { if(!ev.target.closest('#exportDD')) $('#exportDD').classList.remove('open'); });
$$('#exportDD .menu button').forEach(b => b.addEventListener('click', () => { $('#exportDD').classList.remove('open'); if(b.dataset.csv) exportCSV(b.dataset.csv); else if(b.dataset.md) exportMD(b.dataset.md); else if(b.dataset.plain) exportPlain(); }));
document.addEventListener('keydown', ev => {
  const tag = (ev.target.tagName || '').toLowerCase();
  if(tag === 'input' || tag === 'select' || tag === 'textarea'){ if(ev.key === 'Escape'){ ev.target.blur(); if(ev.target.id === 'q'){ $('#q').value = ''; applySearch(); } } return; }
  if(ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const cards = $$('.turn'); const cur = document.activeElement && document.activeElement.classList.contains('turn') ? document.activeElement : null;
  const idx = cur ? cards.indexOf(cur) : -1;
  const focus = c => { if(c){ c.focus(); c.scrollIntoView({block:'center'}); } };
  const turnOf = c => c && state.project.turns.find(t => t.id === c.dataset.id);
  if(ev.key === '/'){ ev.preventDefault(); $('#q').focus(); $('#q').select(); }
  else if(ev.key === 'j'){ ev.preventDefault(); focus(cards[Math.min(idx + 1, cards.length - 1)]); }
  else if(ev.key === 'k'){ ev.preventDefault(); focus(cards[Math.max(idx - 1, 0)]); }
  else if(ev.key === 'o' && cur){ toggle(turnOf(cur), cur, 'r'); }
  else if(ev.key === 'd' && cur){ toggle(turnOf(cur), cur, 'd'); }
  else if(ev.key === 'p' && cur){ togglePin(turnOf(cur), cur); }
  else if(ev.key === 'c' && cur){ copyText(turnOf(cur).prompt); }
  else if(ev.key === '?'){ $('#help').classList.toggle('show'); }
  else if(ev.key === 'Escape'){ $('#help').classList.remove('show'); closeLightbox(); }
});

// ------------------------------------------------------------ init
(async function(){
  applyI18n();
  await loadProjects();
  const m = location.hash.match(/p=([^&]+)/);
  if(m){ const pid = decodeURIComponent(m[1]); if(state.projects.some(p => p.id === pid)) selectProject(pid); }
  else if(EMBEDDED && state.projects.length === 1) selectProject(state.projects[0].id);
  window.addEventListener('hashchange', () => { const m = location.hash.match(/p=([^&]+)/); if(!m) return; const pid = decodeURIComponent(m[1]); if(pid !== state.pid && state.projects.some(p => p.id === pid)) selectProject(pid); });
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
