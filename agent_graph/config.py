from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class AgentConfig:
    command: str = "codex --yolo"
    startup_wait_sec: float = 2.0
    prompt_mode: str = "auto"
    default_workdir: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeConfig:
    parallelism: int = 2
    poll_interval_sec: float = 2.0
    tmux_session: str = "agent-graph"
    tmux_mode: str = "multi_session"
    remain_on_exit: bool = True
    done_prefix: str = "AGENT_DONE:"
    done_command_template: str = "printf '%s\\n' {marker_shell}"
    cleanup_session_on_success: bool = True
    capture_lines: int = 3000


@dataclass(slots=True)
class WebConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass(slots=True)
class TaskConfig:
    id: str
    prompt: str | None = None
    prompt_command: str | None = None
    deps: list[str] = field(default_factory=list)
    agent_command: str | None = None
    workdir: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AppConfig:
    tasks: list[TaskConfig]
    agent: AgentConfig = field(default_factory=AgentConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    web: WebConfig = field(default_factory=WebConfig)


DEFAULT_AGENT = AgentConfig()
DEFAULT_RUNTIME = RuntimeConfig()
DEFAULT_WEB = WebConfig()


def _expect_dict(data: Any, context: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(f"{context} must be an object")
    return data


def _expect_list(data: Any, context: str) -> list[Any]:
    if not isinstance(data, list):
        raise ConfigError(f"{context} must be an array")
    return data


def _expect_str(data: Any, context: str) -> str:
    if not isinstance(data, str) or not data.strip():
        raise ConfigError(f"{context} must be a non-empty string")
    return data


def _expect_env(data: Any, context: str) -> dict[str, str]:
    if data is None:
        return {}
    raw = _expect_dict(data, context)
    env: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ConfigError(f"{context} key must be a non-empty string")
        if not isinstance(value, str):
            raise ConfigError(f"{context}.{key} must be a string")
        env[key] = value
    return env


def _parse_task(item: Any, idx: int) -> TaskConfig:
    raw = _expect_dict(item, f"tasks[{idx}]")
    task_id = _expect_str(raw.get("id"), f"tasks[{idx}].id")

    prompt = raw.get("prompt")
    prompt_command = raw.get("prompt_command")
    if prompt is not None and not isinstance(prompt, str):
        raise ConfigError(f"tasks[{idx}].prompt must be a string")
    if prompt_command is not None and not isinstance(prompt_command, str):
        raise ConfigError(f"tasks[{idx}].prompt_command must be a string")
    if not prompt and not prompt_command:
        raise ConfigError(
            f"tasks[{idx}] must provide prompt or prompt_command"
        )

    deps_raw = raw.get("deps", [])
    deps = _expect_list(deps_raw, f"tasks[{idx}].deps")
    dep_ids: list[str] = []
    for dep in deps:
        dep_ids.append(_expect_str(dep, f"tasks[{idx}].deps[]"))

    agent_command = raw.get("agent_command")
    if agent_command is not None and not isinstance(agent_command, str):
        raise ConfigError(f"tasks[{idx}].agent_command must be a string")

    workdir = raw.get("workdir")
    if workdir is not None and not isinstance(workdir, str):
        raise ConfigError(f"tasks[{idx}].workdir must be a string")

    env = _expect_env(raw.get("env", {}), f"tasks[{idx}].env")

    return TaskConfig(
        id=task_id,
        prompt=prompt,
        prompt_command=prompt_command,
        deps=dep_ids,
        agent_command=agent_command,
        workdir=workdir,
        env=env,
    )


def _parse_agent(raw: dict[str, Any]) -> AgentConfig:
    agent_raw = _expect_dict(raw.get("agent", {}), "agent")
    command = agent_raw.get("command", DEFAULT_AGENT.command)
    if not isinstance(command, str) or not command.strip():
        raise ConfigError("agent.command must be a non-empty string")

    startup_wait_sec = agent_raw.get("startup_wait_sec", DEFAULT_AGENT.startup_wait_sec)
    if not isinstance(startup_wait_sec, (int, float)) or startup_wait_sec < 0:
        raise ConfigError("agent.startup_wait_sec must be >= 0")

    prompt_mode = agent_raw.get("prompt_mode", DEFAULT_AGENT.prompt_mode)
    if not isinstance(prompt_mode, str) or prompt_mode not in {
        "auto",
        "stdin_lines",
        "command_arg",
    }:
        raise ConfigError(
            "agent.prompt_mode must be one of: auto, stdin_lines, command_arg"
        )

    default_workdir = agent_raw.get("default_workdir")
    if default_workdir is not None and not isinstance(default_workdir, str):
        raise ConfigError("agent.default_workdir must be a string")

    env = _expect_env(agent_raw.get("env", {}), "agent.env")

    return AgentConfig(
        command=command.strip(),
        startup_wait_sec=float(startup_wait_sec),
        prompt_mode=prompt_mode,
        default_workdir=default_workdir,
        env=env,
    )


def _parse_runtime(raw: dict[str, Any]) -> RuntimeConfig:
    runtime_raw = _expect_dict(raw.get("runtime", {}), "runtime")

    parallelism = runtime_raw.get("parallelism", DEFAULT_RUNTIME.parallelism)
    if not isinstance(parallelism, int) or parallelism < 1:
        raise ConfigError("runtime.parallelism must be >= 1")

    poll_interval = runtime_raw.get(
        "poll_interval_sec", DEFAULT_RUNTIME.poll_interval_sec
    )
    if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
        raise ConfigError("runtime.poll_interval_sec must be > 0")

    tmux_session = runtime_raw.get("tmux_session", DEFAULT_RUNTIME.tmux_session)
    if not isinstance(tmux_session, str) or not tmux_session.strip():
        raise ConfigError("runtime.tmux_session must be a non-empty string")

    tmux_mode = runtime_raw.get("tmux_mode", DEFAULT_RUNTIME.tmux_mode)
    if not isinstance(tmux_mode, str) or tmux_mode not in {
        "multi_session",
        "single_group",
    }:
        raise ConfigError(
            "runtime.tmux_mode must be one of: multi_session, single_group"
        )

    remain_on_exit = runtime_raw.get("remain_on_exit", DEFAULT_RUNTIME.remain_on_exit)
    if not isinstance(remain_on_exit, bool):
        raise ConfigError("runtime.remain_on_exit must be true/false")

    done_prefix = runtime_raw.get("done_prefix", DEFAULT_RUNTIME.done_prefix)
    if not isinstance(done_prefix, str) or not done_prefix:
        raise ConfigError("runtime.done_prefix must be a non-empty string")

    done_command_template = runtime_raw.get(
        "done_command_template", DEFAULT_RUNTIME.done_command_template
    )
    if not isinstance(done_command_template, str) or not done_command_template.strip():
        raise ConfigError("runtime.done_command_template must be a non-empty string")

    cleanup_session_on_success = runtime_raw.get(
        "cleanup_session_on_success", DEFAULT_RUNTIME.cleanup_session_on_success
    )
    if not isinstance(cleanup_session_on_success, bool):
        raise ConfigError("runtime.cleanup_session_on_success must be true/false")

    capture_lines = runtime_raw.get("capture_lines", DEFAULT_RUNTIME.capture_lines)
    if not isinstance(capture_lines, int) or capture_lines < 200:
        raise ConfigError("runtime.capture_lines must be >= 200")

    return RuntimeConfig(
        parallelism=parallelism,
        poll_interval_sec=float(poll_interval),
        tmux_session=tmux_session.strip(),
        tmux_mode=tmux_mode,
        remain_on_exit=remain_on_exit,
        done_prefix=done_prefix,
        done_command_template=done_command_template.strip(),
        cleanup_session_on_success=cleanup_session_on_success,
        capture_lines=capture_lines,
    )


def _parse_web(raw: dict[str, Any]) -> WebConfig:
    web_raw = _expect_dict(raw.get("web", {}), "web")

    enabled = web_raw.get("enabled", DEFAULT_WEB.enabled)
    if not isinstance(enabled, bool):
        raise ConfigError("web.enabled must be true/false")

    host = web_raw.get("host", DEFAULT_WEB.host)
    if not isinstance(host, str) or not host.strip():
        raise ConfigError("web.host must be a non-empty string")

    port = web_raw.get("port", DEFAULT_WEB.port)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("web.port must be 1-65535")

    return WebConfig(enabled=enabled, host=host.strip(), port=port)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config file not found: {config_path}")

    try:
        raw_data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON: {exc}") from exc

    if isinstance(raw_data, list):
        # simple list mode
        raw_data = {"tasks": raw_data}

    root = _expect_dict(raw_data, "root")
    task_items = _expect_list(root.get("tasks"), "tasks")
    if not task_items:
        raise ConfigError("tasks must not be empty")

    tasks = [_parse_task(item, idx) for idx, item in enumerate(task_items)]

    config = AppConfig(
        tasks=tasks,
        agent=_parse_agent(root),
        runtime=_parse_runtime(root),
        web=_parse_web(root),
    )
    _validate_dag(config.tasks)

    return config


def _validate_dag(tasks: list[TaskConfig]) -> None:
    ids = [t.id for t in tasks]
    unique = set(ids)
    if len(unique) != len(ids):
        seen: set[str] = set()
        dupes: list[str] = []
        for task_id in ids:
            if task_id in seen and task_id not in dupes:
                dupes.append(task_id)
            seen.add(task_id)
        raise ConfigError(f"duplicate task ids: {', '.join(dupes)}")

    task_map = {task.id: task for task in tasks}
    for task in tasks:
        if task.id in task.deps:
            raise ConfigError(f"task {task.id} cannot depend on itself")
        for dep in task.deps:
            if dep not in task_map:
                raise ConfigError(f"task {task.id} depends on missing task: {dep}")

    # cycle check
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, chain: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join(chain + [node])
            raise ConfigError(f"cycle detected: {cycle}")
        visiting.add(node)
        for dep in task_map[node].deps:
            dfs(dep, chain + [node])
        visiting.remove(node)
        visited.add(node)

    for task_id in ids:
        dfs(task_id, [])
