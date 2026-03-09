# Codex 真实 CLI 端到端验证报告（2026-03-09）

## 结论先说

本轮用真实 `codex` CLI（不是 mock agent）对 `agent-graph-tmux` 做了两层验证：

1. **最小真实用例**：在 `/tmp/ag-codex-before` 中让 Codex 创建 `hello.txt`
2. **复杂真实 DAG**：在 `/tmp/ag-complex-prime` 中完成“建项目 → 并行审查/扩展建议 → 汇总”四阶段任务

最终结论：

- 发现并修复了 **3 个会导致真实 Codex 场景失败的关键问题**。
- 修复后，真实 Codex DAG **4/4 任务全部成功**。
- 同时回归验证了原有 mock agent 路径，**4/4 任务全部成功**，没有被新逻辑带坏。

---

## 本次发现的关键问题

### 1. 多行 prompt 通过 tmux 逐行回车发送时，Codex 不会自动提交

### 现象

旧实现会把 prompt `splitlines()` 后逐行 `tmux send-keys ... C-m` 发给 agent。

对 `scripts/mock_agent.py` 这类“按 stdin 行读取”的程序没问题；但对真实 `codex` 交互 TUI，这样做只会把内容放进多行输入框，**不会真正提交任务**。

### 复现结果

我直接手工起了一个 `tmux + codex` 会话，观察到：

- 发第一行后，Codex 只是把这行放进输入框
- 再发第二行，输入框变成两行
- 但任务没有开始执行

随后又用旧版编排器做真实复现：

- 任务状态停在 `prompt sent`
- `/tmp/ag-codex-before` 没有产物落盘
- pane 中能看到 prompt 已出现在 Codex 输入框里，但没有进入执行阶段

### 修复

新增 `agent.prompt_mode`：

- `auto`
- `stdin_lines`
- `command_arg`

默认使用 `auto`，当检测到 agent 可执行命令是 `codex` 时，改为把完整 prompt **作为启动参数传入**，而不是走 stdin 多行发送。

### 修复后结果

最小真实用例成功：

- Codex 自动开始执行
- 在 `/tmp/ag-codex-before/hello.txt` 成功写入 `hello`
- 编排器能正确判定 `task succeeded`

---

### 2. 默认 `DONE_COMMAND` 使用相对路径，切到 `/tmp` 工作目录后会失效

### 现象

旧默认值是：

```bash
python3 scripts/report_done.py --marker {marker_shell}
```

如果任务工作目录是仓库根目录，这条命令能运行；但如果真实任务在 `/tmp/...` 或其他项目目录执行，`scripts/report_done.py` 就找不到。

### 风险

这会导致：

- agent 任务本身可能已经做完
- 但 done marker 无法打印
- 编排器最终误判为失败或一直 running

### 修复

把默认 `done_command_template` 改成纯 shell 版本：

```bash
printf '%s\n' {marker_shell}
```

这样不再依赖仓库内相对脚本路径，工作目录切到哪里都能输出 marker。

---

### 3. Codex 会给 shell 输出加 TUI 装饰前缀，导致 done marker 严格等值匹配失效

### 现象

旧逻辑要求 pane 中出现“整行完全等于 marker”才算完成。

但真实 Codex 执行 `DONE_COMMAND` 后，pane 中看到的是类似：

```text
└ AGENT_DONE:write:...
```

前面多了 TUI 装饰字符，不再是“裸 marker 行”。

### 修复

放宽 done marker 检测逻辑：

- 跳过 `DONE_COMMAND:` 指令行
- 去掉常见 TUI 装饰前缀（如 `│`、`└`、`├`、`─`、`•`）
- 再与 marker 比较

### 修复后结果

最小真实用例在 marker 被 Codex TUI 包装后，仍能被 runner 正确识别并结束任务。

---

## 顺手发现的环境问题（已在文档/示例规避）

### 4. Codex 启动时可能弹升级提示，阻塞无人值守执行

直接运行真实 `codex` 时，我首次遇到了版本更新提示：

- `0.111.0 -> 0.112.0`
- 阻塞在“Press enter to continue”界面

这不是编排器本体 bug，但对无人值守场景是实打实的问题。

### 处理方式

在 README 和 `examples/dag_codex_template.json` 中，示例命令改为推荐：

```bash
codex -c check_for_update_on_startup=false --yolo --no-alt-screen
```

补充说明：

- `-c check_for_update_on_startup=false`：避免升级弹窗卡住
- `--no-alt-screen`：让 tmux `capture-pane` 与滚动历史更稳定

---

## 真实验证一：最小 Codex 用例

### 目标

在 `/tmp/ag-codex-before` 中让真实 Codex：

- 创建 `hello.txt`
- 写入 `hello`
- 执行 `DONE_COMMAND`

### 结果

修复后成功：

- `hello.txt` 已生成
- 文件内容正确
- runner 输出：

```text
task succeeded: write
summary: total=1 succeeded=1 failed=0 blocked=0
```

这说明：

- `command_arg` 路径可用
- `/tmp` 工作目录下 done marker 可用
- Codex TUI 包装后的 marker 也能被识别

---

## 真实验证二：复杂 Codex DAG

### DAG 设计

工作目录：`/tmp/ag-complex-prime`

任务图：

1. `create-project`
   - 用真实 Codex 从零创建一个小型 Python 项目 `primekit`
   - 主题：素数筛 / prime sieve
2. `review-project`
   - 依赖 `create-project`
   - 生成 `REVIEW.md`
3. `extension-ideas`
   - 依赖 `create-project`
   - 生成 `EXTENSIONS.md`
4. `final-summary`
   - 依赖 `review-project` 和 `extension-ideas`
   - 生成 `FINAL_SUMMARY.md`

其中：

- `parallelism=2`
- `review-project` 与 `extension-ideas` 并行
- `review-project` / `extension-ideas` 都使用了 `prompt_command`

### 最终结果

日志结果：

```text
summary: total=4 succeeded=4 failed=0 blocked=0
ELAPSED=8:15.11
```

生成产物：

- `README.md`
- `pyproject.toml`
- `primekit/__init__.py`
- `primekit/sieve.py`
- `primekit/cli.py`
- `REVIEW.md`
- `EXTENSIONS.md`
- `FINAL_SUMMARY.md`

### 说明

这次复杂验证覆盖了：

- 真实 `codex` CLI
- 多行 prompt
- `/tmp` 工作目录
- 并行任务
- DAG 依赖触发
- `prompt_command`
- done marker 检测
- 最终汇总任务

换句话说，这已经不是“简单 hello world”，而是真实多阶段 agent 编排验证。

---

## 对生成项目本身的审查结论（来自真实 Codex 的二级任务）

真实 Codex 在 `/tmp/ag-complex-prime` 生成并审查了 `primekit` 项目，结论里有几个值得记录的问题：

### 已验证的优点

- 项目结构清晰：算法与 CLI 分离
- 埃拉托斯特尼筛法实现简洁
- 正常输入下行为正确
- 打包入口可用

### 已发现的风险

- `bool` 会被当作整数接受
- 超大整数输入会触发 `OverflowError`
- CLI 对底层异常缺少兜底
- 没有自动化测试
- README 中直接运行示例写的是 `python -m ...`，而当前环境实际只有 `python3`

### 扩展建议方向

- 先补测试体系
- 再补更多素数相关 API（`is_prime` / `count_primes` / `nth_prime` / `prime_factors`）
- 再把 CLI 升级为子命令形式
- 更后面再做缓存和高性能筛法

这些内容已经分别落到：

- `/tmp/ag-complex-prime/REVIEW.md`
- `/tmp/ag-complex-prime/EXTENSIONS.md`
- `/tmp/ag-complex-prime/FINAL_SUMMARY.md`

---

## 回归验证：mock agent 没被修坏

我还回跑了原有示例：

```bash
python3 main.py validate --config examples/dag_mock_agent.json
python3 main.py run --config examples/dag_mock_agent.json --no-web
```

结果：

```text
summary: total=4 succeeded=4 failed=0 blocked=0
```

这说明：

- 非 Codex agent 仍然走 `stdin_lines`
- 旧示例没有被 `prompt_mode=auto` 的新逻辑破坏

---

## 本次代码改动摘要

### 已修改文件

- `agent_graph/config.py`
- `agent_graph/orchestrator.py`
- `README.md`
- `examples/dag_codex_template.json`

### 核心变更

1. 新增 `agent.prompt_mode`
2. 默认 `done_command_template` 改为 `printf '%s\n' {marker_shell}`
3. `auto` 模式下自动识别 `codex` 并改走 `command_arg`
4. done marker 检测兼容 Codex TUI 装饰字符
5. README / 示例补充无人值守运行建议

---

## 最终判断

现在这套编排器对真实 `codex` CLI 已经从“mock 场景可用”提升到“真实多阶段 DAG 可用”。

如果只看这次验证结论：

- **真实 Codex 已跑通**
- **多行 prompt 问题已修复**
- **`/tmp` 工作目录下 done marker 问题已修复**
- **Codex TUI 输出包装导致的 marker 识别问题已修复**
- **旧 mock agent 路径回归通过**

当前我认为这版已经可以作为“用 tmux 驱动真实 agent CLI 跑静态 DAG”的可用基础版本继续往前迭代。
