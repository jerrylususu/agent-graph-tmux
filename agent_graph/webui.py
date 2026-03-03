from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Callable

SnapshotGetter = Callable[[], dict]


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Graph Runner</title>
  <style>
    :root {
      --bg: #f4f6fb;
      --card: #ffffff;
      --text: #122130;
      --muted: #5a6c80;
      --ok: #178a45;
      --warn: #a86800;
      --bad: #b82323;
      --running: #004fb8;
      --line: #d8e0ea;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "SF Mono", "Menlo", "Consolas", monospace;
      background: radial-gradient(circle at 10% 10%, #dde6f8, var(--bg));
      color: var(--text);
      padding: 20px;
    }
    .wrap {
      max-width: 1080px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(18, 33, 48, 0.08);
      overflow: hidden;
    }
    header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }
    th { background: #eef3fb; }
    .status { font-weight: 700; }
    .pending { color: var(--warn); }
    .running { color: var(--running); }
    .succeeded { color: var(--ok); }
    .failed, .blocked { color: var(--bad); }
    .dim { color: var(--muted); }
    .badge {
      border-radius: 6px;
      padding: 2px 6px;
      border: 1px solid var(--line);
      margin-right: 6px;
      display: inline-block;
      margin-bottom: 6px;
    }
    @media (max-width: 800px) {
      table, thead, tbody, th, td, tr { display: block; }
      thead { display: none; }
      tr { border-bottom: 1px solid var(--line); padding: 8px; }
      td { border-bottom: 0; padding: 4px 10px; }
      td::before { content: attr(data-label) ": "; font-weight: bold; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <div id="title" style="font-size:16px;font-weight:800;">Agent Graph Runner</div>
        <div id="meta" class="meta"></div>
      </div>
      <div id="counts" class="meta"></div>
    </header>
    <div style="overflow:auto;">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>依赖</th>
            <th>tmux</th>
            <th>开始/结束</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>
  <script>
    const rows = document.getElementById('rows');
    const title = document.getElementById('title');
    const meta = document.getElementById('meta');
    const counts = document.getElementById('counts');

    function render(data) {
      title.textContent = `Workflow: ${data.workflow_name}`;
      meta.textContent = `tmux session/pattern: ${data.session_name} | created: ${data.created_at}`;
      const c = data.counts;
      counts.innerHTML = `
        <span class="badge">pending ${c.pending || 0}</span>
        <span class="badge">running ${c.running || 0}</span>
        <span class="badge">succeeded ${c.succeeded || 0}</span>
        <span class="badge">failed ${c.failed || 0}</span>
        <span class="badge">blocked ${c.blocked || 0}</span>
      `;

      rows.innerHTML = '';
      for (const t of data.tasks) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td data-label="任务"><strong>${t.id}</strong></td>
          <td data-label="状态"><span class="status ${t.status}">${t.status}</span></td>
          <td data-label="依赖" class="dim">${(t.deps || []).join(', ') || '-'}</td>
          <td data-label="tmux" class="dim">${t.window_target || '-'}</td>
          <td data-label="开始/结束" class="dim">${t.started_at || '-'}<br/>${t.finished_at || '-'}</td>
          <td data-label="错误" class="dim">${t.error || '-'}</td>
        `;
        rows.appendChild(tr);
      }
    }

    async function tick() {
      try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        render(data);
      } catch (err) {
        console.error(err);
      }
    }

    tick();
    setInterval(tick, 1500);
  </script>
</body>
</html>
"""


class StatusHandler(BaseHTTPRequestHandler):
    status_getter: SnapshotGetter

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/status":
            payload = json.dumps(self.status_getter(), ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/":
            payload = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def start_web_server(host: str, port: int, status_getter: SnapshotGetter) -> ThreadingHTTPServer:
    class _Handler(StatusHandler):
        pass

    _Handler.status_getter = staticmethod(status_getter)
    server = ThreadingHTTPServer((host, port), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
