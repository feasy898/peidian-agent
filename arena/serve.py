#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""arena/serve.py · 人类体验模式服务（HTTP + SSE，零依赖 stdlib）。

端点（前端 ui/ 唯一消费面）：
  GET  /api/scenarios            场景库清单（arena/scenarios/*.yaml）
  GET  /api/parks                园区 DSL 样例清单（dsl/examples/*.yaml）
  GET  /api/faults               故障库清单（arena/faults，供注入面板）
  POST /api/runs                 启动一次 run {scenario, seed?, agent_enabled?}
  GET  /api/runs/<id>/events     事件流增量（?since=seq）
  GET  /api/runs/<id>/stream     SSE 实时推送（EventBus 订阅）
  POST /api/runs/<id>/actions    人工动作 {op,target,reason} / {op:inject,fault_id}
  POST /api/runs/<id>/agent      {enabled: bool} agent 开关
  GET  /api/runs/<id>/eval       run 摘要（eval.json）

安全边界：只读仓库内文件、只写 runs/；无真实系统接口（契约 §4）。
用法: python arena/serve.py --port 8790
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.engine import ArenaEngine, ScenarioRejected, load_scenario  # noqa: E402
from arena.faultlib import load_fault_library  # noqa: E402

UI_DIR = ROOT / "ui"


class Hub:
    """run 注册表 + 线程安全的事件订阅。"""

    def __init__(self) -> None:
        self.runs: dict[str, ArenaEngine] = {}
        self.results: dict[str, dict] = {}
        self.subs: dict[str, list] = {}
        self.lock = threading.Lock()

    def subscribe(self, run_id: str, q: list) -> None:
        with self.lock:
            self.subs.setdefault(run_id, []).append(q)

    def unsubscribe(self, run_id: str, q: list) -> None:
        with self.lock:
            if run_id in self.subs and q in self.subs[run_id]:
                self.subs[run_id].remove(q)

    def publish(self, run_id: str, evt: dict) -> None:
        with self.lock:
            for q in list(self.subs.get(run_id, [])):
                q.append(evt)


HUB = Hub()


def _json(handler, code: int, payload) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "arena-serve/0.1"

    def log_message(self, fmt, *args):  # 静默访问日志（事件流已足够）
        pass

    # ---------------------------------------------------------------- 工具
    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _run_of(self, run_id: str) -> ArenaEngine | None:
        return HUB.runs.get(run_id)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/api/scenarios":
            d = ROOT / "arena" / "scenarios"
            items = []
            if d.is_dir():
                for f in sorted(d.glob("*.yaml")):
                    try:
                        cfg = load_scenario(f)
                        sc = cfg.get("scenario") or {}
                        items.append({"id": f.stem, "file": f.name,
                                      "park": (cfg.get("park") or {}).get("name", ""),
                                      "duration_sim_s": sc.get("duration_sim_s"),
                                      "clock_speed": sc.get("clock_speed"),
                                      "injections": len(sc.get("injections") or [])})
                    except ScenarioRejected:
                        continue
            return _json(self, 200, {"scenarios": items})
        if path == "/api/parks":
            d = ROOT / "dsl" / "examples"
            items = []
            if d.is_dir():
                for f in sorted(d.glob("*.yaml")):
                    try:
                        cfg = load_scenario(f)
                        items.append({"id": f.stem, "file": f.name,
                                      "park": (cfg.get("park") or {}).get("name", ""),
                                      "tier": (cfg.get("park") or {}).get("tier", "")})
                    except ScenarioRejected:
                        continue
            return _json(self, 200, {"parks": items})
        if path == "/api/faults":
            lib = load_fault_library()
            items = [{"engine_type": k, "title": v.get("title", ""),
                      "class": v.get("class", ""), "detection": v.get("detection", {})}
                     for k, v in sorted(lib.entries.items())]
            return _json(self, 200, {"faults": items})
        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            run_id = parts[2]
            tail = parts[3] if len(parts) > 3 else ""
            ae = self._run_of(run_id)
            if tail == "events":
                q = parse_qs(u.query)
                since = int((q.get("since") or ["0"])[0])
                if ae is not None:
                    return _json(self, 200, {"events": ae.engine.stream.since(since)})
                p = self._run_dir(run_id) / "events.jsonl"
                if p.exists():
                    evts = [json.loads(x) for x in
                            p.read_text(encoding="utf-8").splitlines() if x.strip()]
                    return _json(self, 200, {"events": [e for e in evts if e["seq"] > since]})
                return _json(self, 404, {"error": "run not found"})
            if tail == "eval":
                res = HUB.results.get(run_id)
                if res is not None:
                    return _json(self, 200, res)
                p = self._run_dir(run_id) / "eval.json"
                if p.exists():
                    return _json(self, 200, json.loads(p.read_text(encoding="utf-8")))
                return _json(self, 404, {"error": "run not found"})
            if tail == "stream":
                return self._sse(run_id)
            return _json(self, 404, {"error": "unknown run endpoint"})
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.endswith((".js", ".css")):
            return self._static(path.lstrip("/"))
        return _json(self, 404, {"error": "not found"})

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        body = self._body()
        if path == "/api/runs":
            name = str(body.get("scenario") or "")
            if not name.endswith(".yaml"):
                name += ".yaml"
            src = ROOT / "arena" / "scenarios" / name
            if not src.exists():
                src = ROOT / "dsl" / "examples" / name
            if not src.exists():
                return _json(self, 400, {"error": f"场景不存在: {name}"})
            try:
                cfg = load_scenario(src)
                agent_on = body.get("agent_enabled")
                ae = ArenaEngine(cfg, seed=body.get("seed"),
                                 agent_enabled=None if agent_on is None else bool(agent_on),
                                 runs_root=self.server.runs_root)
            except ScenarioRejected as exc:
                return _json(self, 400, {"error": "场景被拒", "reasons": exc.reasons})
            run_id = ae.run_id
            HUB.runs[run_id] = ae

            def on_evt(evt, _rid=run_id):
                HUB.publish(_rid, evt)

            ae.engine.stream._subs.append(on_evt)

            def worker():
                try:
                    res = ae.run()
                    HUB.results[run_id] = res.to_dict()
                except Exception as exc:  # noqa: BLE001
                    HUB.publish(run_id, {"channel": "control", "type": "run.failed",
                                         "payload": {"error": str(exc)}, "sim_s": -1,
                                         "seq": -1})
                finally:
                    try:
                        ae.engine.stream._subs.remove(on_evt)
                    except ValueError:
                        pass

            threading.Thread(target=worker, daemon=True).start()
            return _json(self, 200, {"run_id": run_id,
                                     "agent_enabled": ae.agent_enabled,
                                     "faults": sorted(ae.faults)})
        if path.startswith("/api/runs/") and path.endswith("/actions"):
            run_id = path.strip("/").split("/")[2]
            ae = self._run_of(run_id)
            if ae is None:
                return _json(self, 404, {"error": "run not found"})
            ae.submit_human(body)
            return _json(self, 202, {"queued": body})
        if path.startswith("/api/runs/") and path.endswith("/agent"):
            run_id = path.strip("/").split("/")[2]
            ae = self._run_of(run_id)
            if ae is None:
                return _json(self, 404, {"error": "run not found"})
            ae.submit_human({"op": "agent", "value": "on" if body.get("enabled") else "off"})
            return _json(self, 202, {"agent_enabled": bool(body.get("enabled"))})
        return _json(self, 404, {"error": "not found"})

    # ---------------------------------------------------------------- 辅助
    def _run_dir(self, run_id: str) -> Path:
        return Path(self.server.runs_root) / run_id

    def _static(self, rel: str):
        p = (UI_DIR / rel).resolve()
        try:
            p.relative_to(UI_DIR.resolve())
        except ValueError:
            return _json(self, 404, {"error": "not found"})
        if not p.is_file():
            return _json(self, 404, {"error": "not found"})
        ctype = ("text/html" if p.suffix == ".html" else
                 "text/css" if p.suffix == ".css" else
                 "application/javascript" if p.suffix == ".js" else "text/plain")
        body = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, run_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q: list = []
        HUB.subscribe(run_id, q)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                if q:
                    evt = q.pop(0)
                    self.wfile.write(
                        ("data: " + json.dumps(evt, ensure_ascii=False) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                else:
                    time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            HUB.unsubscribe(run_id, q)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="serve.py", description="人类体验模式服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--runs-root", default=str(ROOT / "runs" / "arena"))
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.runs_root = Path(args.runs_root)
    print(f"arena serve -> http://{args.host}:{args.port}  (UI: {UI_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n(serve stopped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
