from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess
from typing import Iterable


class TmuxError(RuntimeError):
    pass


@dataclass(slots=True)
class PaneStatus:
    dead: bool
    exit_status: int


def _run_tmux(args: list[str]) -> str:
    cmd = ["tmux", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise TmuxError(f"tmux {' '.join(args)} failed: {stderr}")
    return proc.stdout.strip()


def session_exists(session_name: str) -> bool:
    proc = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def ensure_session(session_name: str, remain_on_exit: bool = True) -> None:
    remain = "on" if remain_on_exit else "off"
    if session_exists(session_name):
        _run_tmux(
            ["set-window-option", "-t", session_name, "-g", "remain-on-exit", remain]
        )
        return
    _run_tmux(["new-session", "-d", "-s", session_name, "-n", "orchestrator"])
    _run_tmux(
        ["set-window-option", "-t", session_name, "-g", "remain-on-exit", remain]
    )


def kill_session(session_name: str) -> None:
    if not session_exists(session_name):
        return
    _run_tmux(["kill-session", "-t", session_name])


def create_window(
    session_name: str,
    window_name: str,
    command: str,
    workdir: str | None = None,
    env: dict[str, str] | None = None,
    exit_grace_sec: float | None = None,
) -> str:
    shell_command = _build_shell_command(command, workdir, env, exit_grace_sec)

    window_idx = _run_tmux(
        [
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{window_index}",
            "-t",
            session_name,
            "-n",
            window_name,
            shell_command,
        ]
    )
    return f"{session_name}:{window_idx}"


def run_command_in_window0(
    session_name: str,
    command: str,
    workdir: str | None = None,
    env: dict[str, str] | None = None,
    exit_grace_sec: float | None = None,
) -> str:
    shell_command = _build_shell_command(command, workdir, env, exit_grace_sec)
    target = f"{session_name}:0"
    _run_tmux(["respawn-pane", "-k", "-t", target, shell_command])
    return target


def capture_pane(target: str, lines: int = 3000) -> str:
    start = f"-{max(200, lines)}"
    return _run_tmux(["capture-pane", "-p", "-t", target, "-S", start])


def get_pane_status(target: str) -> PaneStatus:
    output = _run_tmux(["list-panes", "-t", target, "-F", "#{pane_dead} #{pane_dead_status}"])
    first = output.splitlines()[0].strip() if output else "0 0"
    bits = first.split()
    dead = bits[0] == "1"
    status = int(bits[1]) if len(bits) > 1 else 0
    return PaneStatus(dead=dead, exit_status=status)


def send_lines(target: str, lines: Iterable[str]) -> None:
    for line in lines:
        _run_tmux(["send-keys", "-t", target, line, "C-m"])


def _safe_name(raw: str, max_len: int, fallback: str) -> str:
    cleaned = []
    for ch in raw:
        if ch.isalnum() or ch in {"_", "-"}:
            cleaned.append(ch)
        else:
            cleaned.append("-")
    out = "".join(cleaned).strip("-")
    return out[:max_len] if out else fallback


def safe_window_name(task_id: str) -> str:
    return _safe_name(task_id, max_len=40, fallback="task")


def safe_session_name(raw: str, max_len: int = 32, fallback: str = "session") -> str:
    return _safe_name(raw, max_len=max_len, fallback=fallback)


def build_task_session_name(
    base_session: str,
    workflow_name: str,
    task_idx: int,
    task_id: str,
) -> str:
    base = safe_session_name(base_session, max_len=24, fallback="agent-graph")
    workflow = safe_session_name(workflow_name, max_len=20, fallback="workflow")
    task = safe_session_name(task_id, max_len=24, fallback=f"task{task_idx}")
    return f"{base}-{workflow}-{task_idx}-{task}"


def build_task_session_pattern(base_session: str, workflow_name: str) -> str:
    base = safe_session_name(base_session, max_len=24, fallback="agent-graph")
    workflow = safe_session_name(workflow_name, max_len=20, fallback="workflow")
    return f"{base}-{workflow}-<idx>-<id>"


def _build_shell_command(
    command: str,
    workdir: str | None,
    env: dict[str, str] | None,
    exit_grace_sec: float | None = None,
) -> str:
    env_prefix = ""
    if env:
        env_bits = [f"{k}={shlex.quote(v)}" for k, v in env.items()]
        env_prefix = " ".join(env_bits) + " "

    shell_command = f"{env_prefix}{command}".strip()
    if workdir:
        shell_command = f"cd {shlex.quote(workdir)} && {shell_command}"
    if exit_grace_sec is not None and exit_grace_sec > 0:
        grace = f"{float(exit_grace_sec):.2f}".rstrip("0").rstrip(".")
        shell_command = (
            f"( {shell_command} ); __agent_graph_ec=$?; sleep {grace}; "
            "exit $__agent_graph_ec"
        )
    return shell_command
