from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from typing import Any

from .config import ConfigError, load_config
from .orchestrator import Orchestrator
from . import tmux
from .webui import start_web_server


def _log(msg: str) -> None:
    print(msg, flush=True)


def _apply_overrides(config: Any, args: argparse.Namespace) -> None:
    if args.parallelism is not None:
        config.runtime.parallelism = args.parallelism
    if args.session:
        config.runtime.tmux_session = args.session

    if args.agent_command:
        config.agent.command = args.agent_command

    if args.no_web:
        config.web.enabled = False
    if args.web_host:
        config.web.host = args.web_host
    if args.web_port is not None:
        config.web.port = args.web_port


def run(args: argparse.Namespace) -> int:
    if not shutil.which("tmux"):
        print("error: tmux not found in PATH", file=sys.stderr)
        return 2

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    _apply_overrides(config, args)
    if config.runtime.parallelism < 1:
        print("config error: runtime.parallelism must be >= 1", file=sys.stderr)
        return 2
    if config.web.port < 1 or config.web.port > 65535:
        print("config error: web.port must be 1-65535", file=sys.stderr)
        return 2

    workflow_name = Path(args.config).stem
    orch = Orchestrator(config=config, workflow_name=workflow_name, log_fn=_log)

    server = None
    if config.web.enabled:
        try:
            server = start_web_server(config.web.host, config.web.port, orch.status.snapshot)
        except OSError as exc:
            print(f"web error: cannot bind {config.web.host}:{config.web.port} ({exc})", file=sys.stderr)
            return 2
        _log(f"web ui: http://{config.web.host}:{config.web.port}")

    if config.runtime.tmux_mode == "single_group":
        _log(
            "attach tmux: "
            f"tmux attach -t {config.runtime.tmux_session}"
        )
    else:
        _log(
            "attach tmux: use per-task session from task window target "
            "(example: tmux attach -t <session_name>)"
        )
    summary = orch.run()

    if server:
        server.shutdown()

    if summary.success and config.runtime.cleanup_session_on_success:
        cleaned: list[str] = []
        sessions = summary.sessions or [config.runtime.tmux_session]
        for session_name in sessions:
            try:
                tmux.kill_session(session_name)
                cleaned.append(session_name)
            except Exception as exc:
                _log(
                    "warning: failed to cleanup tmux session "
                    f"{session_name}: {exc}"
                )
        if cleaned:
            _log(f"tmux session cleaned: {', '.join(cleaned)}")

    _log(
        "summary: "
        f"total={summary.total} succeeded={summary.succeeded} "
        f"failed={summary.failed} blocked={summary.blocked}"
    )
    return 0 if summary.success else 1


def validate(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    print(
        "config ok: "
        f"tasks={len(config.tasks)} parallelism={config.runtime.parallelism} "
        f"session={config.runtime.tmux_session} "
        f"mode={config.runtime.tmux_mode} "
        f"remain_on_exit={config.runtime.remain_on_exit} "
        f"cleanup_on_success={config.runtime.cleanup_session_on_success} "
        f"agent='{config.agent.command}'"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-graph",
        description="Run static list/DAG tasks with tmux-driven agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run workflow")
    p_run.add_argument("--config", default="workflow.json", help="path to workflow JSON")
    p_run.add_argument("--parallelism", type=int, help="override runtime.parallelism")
    p_run.add_argument("--session", help="override runtime.tmux_session")
    p_run.add_argument(
        "--agent-command",
        help="override agent.command (supports any CLI agent, not hardcoded)",
    )
    p_run.add_argument("--no-web", action="store_true", help="disable web status page")
    p_run.add_argument("--web-host", help="override web.host")
    p_run.add_argument("--web-port", type=int, help="override web.port")
    p_run.set_defaults(handler=run)

    p_validate = sub.add_parser("validate", help="validate workflow JSON")
    p_validate.add_argument("--config", default="workflow.json", help="path to workflow JSON")
    p_validate.set_defaults(handler=validate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
