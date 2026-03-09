from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
import shlex
import subprocess
import time
from typing import Callable

from .config import AppConfig, TaskConfig
from .state import StatusStore, TaskRuntime
from . import tmux


LogFn = Callable[[str], None]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RunSummary:
    success: bool
    total: int
    succeeded: int
    failed: int
    blocked: int
    sessions: list[str]


class Orchestrator:
    def __init__(self, config: AppConfig, workflow_name: str, log_fn: LogFn) -> None:
        self.config = config
        self.workflow_name = workflow_name
        self.log_fn = log_fn
        self.secret = secrets.token_bytes(32)
        self.task_map: dict[str, TaskConfig] = {task.id: task for task in config.tasks}
        self._task_indexes: dict[str, int] = {
            task.id: idx for idx, task in enumerate(config.tasks, start=1)
        }
        ordered_ids = [task.id for task in config.tasks]
        session_name = config.runtime.tmux_session
        if config.runtime.tmux_mode == "multi_session":
            session_name = tmux.build_task_session_pattern(
                config.runtime.tmux_session,
                workflow_name,
            )

        self.status = StatusStore(
            workflow_name=workflow_name,
            session_name=session_name,
            task_ids=ordered_ids,
        )
        runtime_map = {
            task.id: TaskRuntime(id=task.id, deps=list(task.deps)) for task in config.tasks
        }
        self.status.set_tasks(runtime_map)

        self._startup_time: dict[str, float] = {}
        self._prompts: dict[str, list[str]] = {}
        self._sessions_for_cleanup: set[str] = set()

    def run(self) -> RunSummary:
        if self.config.runtime.tmux_mode == "single_group":
            tmux.ensure_session(
                self.config.runtime.tmux_session,
                remain_on_exit=self.config.runtime.remain_on_exit,
            )
            self._sessions_for_cleanup.add(self.config.runtime.tmux_session)
            self.log_fn(
                f"tmux session ready: {self.config.runtime.tmux_session} | "
                f"parallelism={self.config.runtime.parallelism}"
            )
        else:
            self.log_fn(
                "tmux session mode: multi_session | "
                f"pattern={self.status.session_name} | "
                f"parallelism={self.config.runtime.parallelism}"
            )

        while True:
            self._apply_blocked_tasks()
            self._launch_ready_tasks()
            self._poll_running_tasks()

            snapshot = self.status.snapshot()
            if snapshot["is_finished"]:
                counts = snapshot["counts"]
                success = counts.get("failed", 0) == 0 and counts.get("blocked", 0) == 0
                return RunSummary(
                    success=success,
                    total=len(snapshot["tasks"]),
                    succeeded=counts.get("succeeded", 0),
                    failed=counts.get("failed", 0),
                    blocked=counts.get("blocked", 0),
                    sessions=sorted(self._sessions_for_cleanup),
                )
            time.sleep(self.config.runtime.poll_interval_sec)

    def _apply_blocked_tasks(self) -> None:
        for task_id, task in self.task_map.items():
            runtime = self.status.get_task(task_id)
            if runtime.status != "pending":
                continue
            dep_states = [self.status.get_task(dep).status for dep in task.deps]
            if any(state in {"failed", "blocked"} for state in dep_states):
                self.status.update_task(
                    task_id,
                    status="blocked",
                    error="dependency failed",
                    finished_at=utc_now_iso(),
                )
                self.log_fn(f"task blocked: {task_id} (dependency failed)")

    def _launch_ready_tasks(self) -> None:
        running_count = len(
            [
                1
                for task_id in self.task_map
                if self.status.get_task(task_id).status == "running"
            ]
        )
        slots = self.config.runtime.parallelism - running_count
        if slots <= 0:
            return

        ready: list[TaskConfig] = []
        for task in self.config.tasks:
            runtime = self.status.get_task(task.id)
            if runtime.status != "pending":
                continue
            dep_states = [self.status.get_task(dep).status for dep in task.deps]
            if dep_states and not all(state == "succeeded" for state in dep_states):
                continue
            ready.append(task)

        for task in ready[:slots]:
            self._launch_task(task)

    def _launch_task(self, task: TaskConfig) -> None:
        runtime = self.status.get_task(task.id)
        marker = self._gen_done_marker(task.id)

        command = task.agent_command or self.config.agent.command
        prompt_text = self._build_prompt_text(task, marker)
        prompt_mode = self._resolve_prompt_mode(command)
        launch_command = command
        prompt_lines: list[str] = []
        prompt_sent = False

        if prompt_mode == "command_arg":
            launch_command = f"{command} {shlex.quote(prompt_text)}"
            prompt_sent = True
        else:
            prompt_lines = self._prompt_text_to_lines(prompt_text)

        exit_grace_sec = self._resolve_exit_grace_sec()
        workdir = self._resolve_workdir(task)
        env = dict(self.config.agent.env)
        env.update(task.env)
        session_name = self._resolve_session_name(task.id)

        try:
            tmux.ensure_session(
                session_name,
                remain_on_exit=self.config.runtime.remain_on_exit,
            )
            self._sessions_for_cleanup.add(session_name)
            if self.config.runtime.tmux_mode == "single_group":
                target = tmux.create_window(
                    session_name=session_name,
                    window_name=tmux.safe_window_name(task.id),
                    command=launch_command,
                    workdir=workdir,
                    env=env,
                    exit_grace_sec=exit_grace_sec,
                )
            else:
                target = tmux.run_command_in_window0(
                    session_name=session_name,
                    command=launch_command,
                    workdir=workdir,
                    env=env,
                    exit_grace_sec=exit_grace_sec,
                )
        except Exception as exc:
            self.status.update_task(
                task.id,
                status="failed",
                error=f"launch failed: {exc}",
                finished_at=utc_now_iso(),
            )
            self.log_fn(f"task failed to launch: {task.id} | {exc}")
            return

        if prompt_lines:
            self._prompts[task.id] = prompt_lines
        self._startup_time[task.id] = time.monotonic()

        self.status.update_task(
            task.id,
            status="running",
            attempts=runtime.attempts + 1,
            window_target=target,
            command=command,
            workdir=workdir,
            done_marker=marker,
            started_at=utc_now_iso(),
            error=None,
            prompt_sent=prompt_sent,
        )
        self.log_fn(
            f"task started: {task.id} | window={target} | prompt_mode={prompt_mode}"
        )

    def _poll_running_tasks(self) -> None:
        for task in self.config.tasks:
            runtime = self.status.get_task(task.id)
            if runtime.status != "running" or not runtime.window_target:
                continue

            try:
                if not runtime.prompt_sent:
                    elapsed = time.monotonic() - self._startup_time.get(task.id, 0)
                    if elapsed >= self.config.agent.startup_wait_sec:
                        tmux.send_lines(runtime.window_target, self._prompts[task.id])
                        self.status.update_task(task.id, prompt_sent=True)
                        self.log_fn(f"prompt sent: {task.id}")

                pane_output = tmux.capture_pane(
                    runtime.window_target,
                    lines=self.config.runtime.capture_lines,
                )
                if runtime.done_marker and self._done_marker_seen(
                    pane_output, runtime.done_marker
                ):
                    self.status.update_task(
                        task.id,
                        status="succeeded",
                        finished_at=utc_now_iso(),
                    )
                    self.log_fn(f"task succeeded: {task.id}")
                    continue

                pane_status = tmux.get_pane_status(runtime.window_target)
                if pane_status.dead:
                    self.status.update_task(
                        task.id,
                        status="failed",
                        error=(
                            "pane exited before done marker"
                            f" (exit={pane_status.exit_status})"
                        ),
                        finished_at=utc_now_iso(),
                    )
                    self.log_fn(
                        f"task failed: {task.id} | pane exited {pane_status.exit_status}"
                    )
            except Exception as exc:
                self.status.update_task(
                    task.id,
                    status="failed",
                    error=f"runtime error: {exc}",
                    finished_at=utc_now_iso(),
                )
                self.log_fn(f"task failed: {task.id} | runtime error: {exc}")

    def _resolve_workdir(self, task: TaskConfig) -> str | None:
        base = task.workdir or self.config.agent.default_workdir
        if not base:
            return None
        return str(Path(base).expanduser().resolve())

    def _build_prompt_text(self, task: TaskConfig, marker: str) -> str:
        prompt_text = task.prompt or ""
        workdir = self._resolve_workdir(task)

        if task.prompt_command:
            output = self._run_prompt_command(task.prompt_command, workdir)
            if "{command_output}" in prompt_text:
                prompt_text = prompt_text.replace("{command_output}", output)
            elif prompt_text.strip():
                prompt_text = (
                    f"{prompt_text.rstrip()}\n\n[command_output]\n{output}".strip()
                )
            else:
                prompt_text = output

        prompt_text = prompt_text.strip()
        if not prompt_text:
            raise ValueError(f"task {task.id} resolved prompt is empty")

        done_command = self._build_done_command(marker)
        completion = (
            "\n\n[runner requirement]\n"
            "When the task is fully complete, run this command in shell and then exit:\n"
            f"DONE_COMMAND: {done_command}\n"
            "The command output is used by runner as completion signal."
        )

        return f"{prompt_text}{completion}".strip("\n")

    def _prompt_text_to_lines(self, prompt_text: str) -> list[str]:
        return prompt_text.splitlines() or [prompt_text]

    def _run_prompt_command(self, command: str, workdir: str | None) -> str:
        proc = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            cwd=workdir,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "prompt_command failed"
                f" (exit={proc.returncode}): {proc.stderr.strip()}"
            )
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError("prompt_command produced empty stdout")
        return output

    def _gen_done_marker(self, task_id: str) -> str:
        payload = f"{task_id}:{time.time_ns()}".encode("utf-8")
        digest = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()[:24]
        return f"{self.config.runtime.done_prefix}{task_id}:{digest}"

    def _build_done_command(self, marker: str) -> str:
        template = self.config.runtime.done_command_template
        return (
            template.replace("{marker_shell}", shlex.quote(marker))
            .replace("{marker}", marker)
            .strip()
        )

    def _resolve_prompt_mode(self, command: str) -> str:
        configured = self.config.agent.prompt_mode
        if configured != "auto":
            return configured

        executable = self._extract_command_executable(command)
        if executable == "codex":
            return "command_arg"
        return "stdin_lines"

    def _extract_command_executable(self, command: str) -> str | None:
        try:
            parts = shlex.split(command)
        except ValueError:
            return None

        if not parts:
            return None

        idx = 0
        if parts[0] == "env":
            idx = 1
            while idx < len(parts) and "=" in parts[idx] and not parts[idx].startswith("-"):
                idx += 1
        else:
            while idx < len(parts) and "=" in parts[idx] and not parts[idx].startswith("-"):
                idx += 1

        if idx >= len(parts):
            return None
        return Path(parts[idx]).name

    def _done_marker_seen(self, pane_output: str, marker: str) -> bool:
        for raw_line in pane_output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("DONE_COMMAND:"):
                continue

            normalized = line.lstrip("│└├─• ").strip()
            if normalized == marker:
                return True
        return False

    def _resolve_session_name(self, task_id: str) -> str:
        if self.config.runtime.tmux_mode == "single_group":
            return self.config.runtime.tmux_session
        return tmux.build_task_session_name(
            base_session=self.config.runtime.tmux_session,
            workflow_name=self.workflow_name,
            task_idx=self._task_indexes[task_id],
            task_id=task_id,
        )

    def _resolve_exit_grace_sec(self) -> float | None:
        if self.config.runtime.remain_on_exit:
            return None
        # Avoid race when panes disappear instantly after exit.
        return max(1.0, min(5.0, self.config.runtime.poll_interval_sec * 2))
