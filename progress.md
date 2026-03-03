# 进展记录

## 2026-03-03

1. 初始化项目骨架
- 建立 `agent_graph` 包结构。
- 增加 `agent-graph` CLI 入口。

2. 完成配置与校验
- 支持根节点为 `tasks` 对象格式和纯数组简单列表格式。
- 支持任务字段：`id`、`deps`、`prompt`、`prompt_command`、`agent_command`、`workdir`、`env`。
- 加入 DAG 校验：重复 ID、缺失依赖、自依赖、环检测。

3. 完成 tmux 调度器
- 自动创建/复用 tmux session。
- 按依赖和并行度启动任务窗口。
- 支持任务失败后阻断下游任务（`blocked`）。
- 任务完成检测使用 per-task done marker（HMAC 截断）。

4. 完成进度可视化
- 内置 HTTP 服务。
- `/` 页面展示任务表格。
- `/api/status` 输出实时 JSON 状态。

5. 完成示例和文档
- `examples/simple_list.json`
- `examples/dag_mock_agent.json`
- `examples/dag_codex_template.json`
- `scripts/mock_agent.py` 用于本地联调。
- README 使用中文完整说明使用方式与设计。

6. 回归验证
- 执行配置校验命令。
- 执行 mock agent DAG 运行，验证依赖触发与完成检测。
- 运行结果：`total=4 succeeded=4 failed=0 blocked=0`。

7. 调试修复
- 修复 `dataclass(slots=True)` 默认值读取导致的配置解析错误（改为显式默认实例）。
- 修复示例配置中的解释器命令，从 `python` 调整为 `python3` 以匹配当前环境。

8. 完成信号机制升级（按 goal 建议）
- 从“要求 agent 直接打印 marker”升级为“要求 agent 执行 DONE_COMMAND”。
- 新增 `runtime.done_command_template` 配置项，默认使用：
  `python3 scripts/report_done.py --marker {marker_shell}`。
- 新增 `scripts/report_done.py`，用于标准化输出 marker。

9. 新增慢速联调 agent
- 新增 `scripts/mock_slow_agent.py`，每个任务固定耗时 15 秒。
- 新增 `examples/dag_mock_slow_agent.json`，用于在 Web UI 观察运行中状态。

10. 竞态与误判修复
- 修复“marker 出现在 prompt 文本中导致提前成功”的误判，改为按“整行完全等于 marker”判定完成。
- 修复“任务结束太快导致 window 被回收，capture-pane 找不到窗口”的竞态，设置 tmux `remain-on-exit`。

11. 追加验证
- `examples/dag_mock_agent.json` 跑通：`total=4 succeeded=4 failed=0 blocked=0`。
- `examples/dag_mock_slow_agent.json` 跑通：`total=4 succeeded=4 failed=0 blocked=0`。
- 慢速场景实测耗时约 `51.57s`，可在 UI 中观察 running 状态。

12. tmux session 收尾策略
- 新增 `runtime.cleanup_session_on_success` 配置项，默认 `true`。
- 默认行为改为：全任务成功后自动销毁 session；失败时保留便于排查。
- `examples/dag_mock_slow_agent.json` 显式设置为 `false`，方便联调后回看窗口内容。

13. tmux 多 session 模式
- 新增 `runtime.tmux_mode` 配置项：`multi_session` / `single_group`。
- 默认改为 `multi_session`（每任务独立 session）；兼容旧行为 `single_group`（单 session 多窗口）。
- 多 session 命名规则：`<tmux_session>-<workflow_name>-<idx>-<task_id>`。
- 多 session 启动策略调整为固定复用 `window 0`，不再额外创建 window/pane。

14. remain-on-exit 可配置化与文档补齐
- 新增 `runtime.remain_on_exit` 配置项（默认 `true`），用于控制 tmux `remain-on-exit`。
- 在 `remain_on_exit=false` 时增加短暂退出缓冲，降低 pane/session 快速回收导致的采集竞态。
- README 补齐所有配置项说明（agent/runtime/web/tasks 全覆盖）。
- 新增 `examples/workflow.full.json.example`（带 `//` 注释的完整模板）。
