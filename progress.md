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


## 2026-03-09

15. 真实 Codex CLI 端到端修复与验证
- 复现并确认：`codex` 在 tmux 中通过逐行 `send-keys + Enter` 注入多行 prompt 时，只会进入多行编辑态，不会自动提交任务。
- 新增 `agent.prompt_mode` 配置项：`auto` / `stdin_lines` / `command_arg`。
- 默认 `auto`：检测到 agent 可执行命令是 `codex` 时，改为把完整 prompt 作为启动参数传入；其他命令仍走 stdin 多行发送。
- 修复默认完成命令模板：从依赖相对路径脚本改为 `printf '%s\n' {marker_shell}`，避免任务工作目录切到 `/tmp` 后 `scripts/report_done.py` 找不到。
- 修复 done marker 检测：兼容 Codex TUI 对 shell 输出增加的前缀装饰（如 `└ `、`│ `），避免任务实际完成后仍无法命中 marker。
- README 与 `examples/dag_codex_template.json` 更新为更适合无人值守的 Codex 示例：推荐 `-c check_for_update_on_startup=false --yolo --no-alt-screen`。

16. 真实 Codex 最小用例验证
- 在 `/tmp/ag-codex-before` 使用真实 `codex` 创建 `hello.txt`，实测 runner 正确识别 done marker。
- 运行结果：`summary: total=1 succeeded=1 failed=0 blocked=0`。

17. 真实 Codex 复杂 DAG 验证
- 在 `/tmp/ag-complex-prime` 设计并执行 4 阶段 DAG：`create-project -> (review-project, extension-ideas) -> final-summary`。
- `review-project` 与 `extension-ideas` 并行执行，并使用 `prompt_command` 注入动态文件清单。
- 真实产物包括：`README.md`、`pyproject.toml`、`primekit/*`、`REVIEW.md`、`EXTENSIONS.md`、`FINAL_SUMMARY.md`。
- 最终结果：`summary: total=4 succeeded=4 failed=0 blocked=0`，总耗时 `8:15.11`。

18. 回归验证
- 回跑 `examples/dag_mock_agent.json`，确认非 Codex agent 仍然走 `stdin_lines` 路径。
- 运行结果：`summary: total=4 succeeded=4 failed=0 blocked=0`。

19. 报告沉淀
- 新增 `codex_e2e_report.md`，完整记录问题复现、修复方案、真实验证过程和测试结论（中文）。
