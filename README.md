# agent-graph-tmux

一个用 Python 实现的静态任务编排器：
- 输入可以是简单任务列表，或带依赖的 DAG（JSON）。
- 每个任务会在 `tmux` 新窗口中启动一个 agent 进程。
- 支持 `single_group`（同一 session 多窗口）和 `multi_session`（每任务独立 session）。
- 支持用户手动 `tmux attach` 直接干预进行中的 agent。
- 支持并行度控制、依赖触发、失败阻断。
- 提供简易 Web UI 展示任务进展。

## 设计目标

适用于「大任务拆成多 agent 子任务」场景：
- 可并行：例如升级模块 1/2/3。
- 有依赖：例如先完成 `prepare`，再并行模块升级，最后 `integration`。

## 关键特性

1. `agent` 可替换，不写死
- 默认命令是 `codex --yolo`，但可通过配置或 CLI 覆盖为任意命令。
- 例如可改成 `claude ...`、`aider ...`、自定义脚本等。

2. prompt 输入支持两种来源
- 静态文本：`prompt`
- 动态命令：`prompt_command`（读取 stdout）
- 两者可组合，`prompt` 里可使用 `{command_output}` 占位符。

3. 完成检测（done marker）
- 每个任务启动时都会生成独立 marker：
  `AGENT_DONE:<task_id>:<hmac截断值>`
- 编排器会在 prompt 末尾自动追加 `DONE_COMMAND`，要求 agent 在完成后执行该命令。
- 默认命令模板：`python3 scripts/report_done.py --marker {marker_shell}`
- 模板变量：
  - `{marker}`：原始 marker
  - `{marker_shell}`：已做 shell 转义的 marker（推荐）
- 编排器轮询 `tmux capture-pane`，命中 marker 视为任务完成。

4. Web 进度页
- 默认地址：`http://127.0.0.1:8765`
- 展示任务状态、依赖、tmux 窗口、错误信息。

## 项目结构

- `agent_graph/config.py`：配置加载与 DAG 校验
- `agent_graph/tmux.py`：tmux 操作封装
- `agent_graph/orchestrator.py`：调度主循环
- `agent_graph/webui.py`：简易 HTTP 状态页
- `scripts/mock_agent.py`：本地联调用 mock agent
- `scripts/mock_slow_agent.py`：每任务固定耗时 30 秒（方便在 UI/tmux 观察状态）
- `scripts/report_done.py`：agent 完成后调用的标记输出命令
- `examples/*.json`：示例配置

## 快速开始

### 1) 验证配置

```bash
python3 main.py validate --config examples/dag_mock_agent.json
```

### 2) 运行（mock agent 演示）

```bash
python3 main.py run --config examples/dag_mock_agent.json
```

然后可以：

```bash
# 默认是 multi_session，可先看当前 session 列表
tmux ls
# 再 attach 到某个任务 session（示例）
tmux attach -t agent-graph-demo-dag_mock_agent-1-prepare
```

### 3) 使用 Codex 作为 agent

```bash
python3 main.py run --config examples/dag_codex_template.json
```

或临时替换 agent 命令：

```bash
python3 main.py run \
  --config examples/dag_codex_template.json \
  --agent-command "codex --yolo"
```

### 4) 慢速 mock（每任务 30 秒）

```bash
python3 main.py run --config examples/dag_mock_slow_agent.json
```

该示例总时长约 90~110 秒（4 个任务，含依赖与并行）。

查看 UI：

```bash
http://127.0.0.1:8766
```

## 配置格式

### 简单列表模式

`examples/simple_list.json` 就是最小格式：根节点直接是数组。

### DAG 模式

```json
{
  "agent": {
    "command": "codex --yolo",
    "startup_wait_sec": 2.0,
    "default_workdir": "/abs/path/to/repo",
    "env": {
      "GLOBAL_FLAG": "1"
    }
  },
  "runtime": {
    "parallelism": 3,
    "poll_interval_sec": 2.0,
    "tmux_session": "agent-graph",
    "tmux_mode": "multi_session",
    "remain_on_exit": true,
    "done_prefix": "AGENT_DONE:",
    "done_command_template": "python3 scripts/report_done.py --marker {marker_shell}",
    "cleanup_session_on_success": true,
    "capture_lines": 3000
  },
  "web": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765
  },
  "tasks": [
    {
      "id": "prepare",
      "prompt": "准备改造计划"
    },
    {
      "id": "module-1",
      "deps": ["prepare"],
      "prompt": "升级模块 1"
    }
  ]
}
```

完整注释模板见：`examples/workflow.full.json.example`（使用 `//` 注释，给人看，不用于程序直接读取）。

### 配置项说明（完整）

`agent`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `command` | `string` | `codex --yolo` | 默认 agent 启动命令，可被任务级 `agent_command` 覆盖 |
| `startup_wait_sec` | `number` | `2.0` | 启动后等待多久再发送 prompt |
| `default_workdir` | `string \| null` | `null` | 默认工作目录，可被任务级 `workdir` 覆盖 |
| `env` | `object<string,string>` | `{}` | 全局环境变量，可被任务级 `env` 追加/覆盖 |

`runtime`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `parallelism` | `int` | `2` | 最大并发任务数（>=1） |
| `poll_interval_sec` | `number` | `2.0` | 调度轮询间隔（>0） |
| `tmux_session` | `string` | `agent-graph` | tmux session 基础名 |
| `tmux_mode` | `string` | `multi_session` | `multi_session`=每任务独立 session；`single_group`=单 session 多窗口 |
| `remain_on_exit` | `bool` | `true` | 是否保留退出后的 pane（`true` 便于排障，`false` 可减少 dead pane；runner 会在进程退出前加短暂缓冲避免采集竞态） |
| `done_prefix` | `string` | `AGENT_DONE:` | done marker 前缀 |
| `done_command_template` | `string` | `python3 scripts/report_done.py --marker {marker_shell}` | 完成命令模板，支持 `{marker}` / `{marker_shell}` |
| `cleanup_session_on_success` | `bool` | `true` | 全部成功后是否清理 tmux session |
| `capture_lines` | `int` | `3000` | `capture-pane` 回看行数（>=200） |

`web`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | `bool` | `true` | 是否启用内置 Web UI |
| `host` | `string` | `127.0.0.1` | Web 监听地址 |
| `port` | `int` | `8765` | Web 监听端口（1-65535） |

`tasks[]`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `id` | `string` | 无 | 任务唯一 ID（必填） |
| `prompt` | `string \| null` | `null` | 静态 prompt |
| `prompt_command` | `string \| null` | `null` | 动态 prompt 生成命令，读取 stdout |
| `deps` | `string[]` | `[]` | 依赖任务 ID 列表 |
| `agent_command` | `string \| null` | `null` | 覆盖 `agent.command` |
| `workdir` | `string \| null` | `null` | 覆盖 `agent.default_workdir` |
| `env` | `object<string,string>` | `{}` | 任务级环境变量，覆盖同名全局变量 |

## CLI

```bash
python3 main.py validate --config <file>
python3 main.py run --config <file> [--parallelism N] [--session NAME]
python3 main.py run --config <file> [--agent-command "..."]
python3 main.py run --config <file> [--no-web | --web-host H --web-port P]
```

## 注意事项

- 依赖必须是静态 DAG；不支持运行中动态改图。
- 判定完成依赖 agent 执行 `DONE_COMMAND` 并输出 marker；若未输出，任务会停在 running 或在 pane 退出后失败。
- `scripts/mock_agent.py` / `scripts/mock_slow_agent.py` 都是通过解析 `DONE_COMMAND:` 后真正执行命令来完成任务，不是硬编码直接打印 marker。
- `runtime.tmux_mode` 默认是 `multi_session`：每个任务创建独立 session，命名后缀是 `<workflow_name>-<idx>-<task_id>`，并默认在该 session 的 `window 0` 运行任务（不再额外开 window/pane）。
- 如需旧行为（单 session 多窗口），设置 `runtime.tmux_mode = "single_group"`。
- `runtime.remain_on_exit` 默认是 `true`；如果你更关注不留 dead pane，可设为 `false`。
- `runtime.cleanup_session_on_success` 默认是 `true`，即全部成功后自动销毁 tmux session；设为 `false` 可保留 session 便于回看。
- 本工具不接管 `tmux` 交互，你可以直接 attach 干预。
- 需要本机安装 `tmux`。
