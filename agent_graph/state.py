from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


TERMINAL_STATES = {"succeeded", "failed", "blocked"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskRuntime:
    id: str
    deps: list[str]
    status: str = "pending"
    attempts: int = 0
    window_target: str | None = None
    command: str | None = None
    workdir: str | None = None
    done_marker: str | None = None
    prompt_sent: bool = False
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class StatusStore:
    workflow_name: str
    session_name: str
    task_ids: list[str]
    _lock: Lock = field(default_factory=Lock)
    _tasks: dict[str, TaskRuntime] = field(default_factory=dict)
    _created_at: str = field(default_factory=utc_now_iso)

    def set_tasks(self, tasks: dict[str, TaskRuntime]) -> None:
        with self._lock:
            self._tasks = tasks

    def get_task(self, task_id: str) -> TaskRuntime:
        with self._lock:
            return self._tasks[task_id]

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        with self._lock:
            task = self._tasks[task_id]
            for key, value in kwargs.items():
                setattr(task, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tasks = []
            counts = {
                "pending": 0,
                "running": 0,
                "succeeded": 0,
                "failed": 0,
                "blocked": 0,
            }
            done = True
            for task_id in self.task_ids:
                task = self._tasks[task_id]
                counts[task.status] = counts.get(task.status, 0) + 1
                if task.status not in TERMINAL_STATES:
                    done = False
                tasks.append(
                    {
                        "id": task.id,
                        "deps": task.deps,
                        "status": task.status,
                        "window_target": task.window_target,
                        "command": task.command,
                        "workdir": task.workdir,
                        "done_marker": task.done_marker,
                        "prompt_sent": task.prompt_sent,
                        "error": task.error,
                        "started_at": task.started_at,
                        "finished_at": task.finished_at,
                        "attempts": task.attempts,
                    }
                )
            return {
                "workflow_name": self.workflow_name,
                "session_name": self.session_name,
                "created_at": self._created_at,
                "is_finished": done,
                "counts": counts,
                "tasks": tasks,
            }
