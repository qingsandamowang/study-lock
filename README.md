# Study Lock：本地学习模式工具

**Windows study planner · application/domain rules · progress and recovery**

读取每日 Markdown 学习计划，展示学习资料和待办任务，记录进度，并提供提醒、模拟和强制模式。代码由 Codex Agent 协助开发。工具运行依据明确规则，没有训练判断学习状态的 AI 模型。

## 功能

- 解析每日目标、执行清单、允许的应用/域名和学习记录路径。
- 展示资料按钮、学习计时、复盘与计划编辑界面。
- 通过本地代理和进程守卫实现可选限制；默认 UI 使用提醒模式。
- 检查当天日期、任务勾选状态和非空学习记录，决定是否解锁。
- 提供等待 60 秒并输入确认短语的紧急恢复，保存事件日志。

## 安装与安全演示

需要 Windows、Python 3.11+ 和 Tkinter。以下命令在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e . pytest
python -m pytest -q
python -m study_lock.cli simulate --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
```

示例日期是固定测试日期；示例资料和记录全部为通用演示文本。模拟模式只记录规则判断，不结束进程。查看演示界面：

```powershell
python -m study_lock.cli ui --mode simulate --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
```

日常使用时，将示例计划复制到自己的工作区 `study-plans/daily/YYYY-MM-DD.md`，同步标题日期、记录路径和白名单。推荐从 `--mode reminder` 提醒模式开始。

## 强制模式与边界

`ui --mode enforce` 会启动网站代理及进程守卫，可能结束白名单外的普通用户进程；应先保存其他应用的工作，确认规则和恢复流程。系统进程、Python、工具自身等受保护。

解锁要求当天计划的任务全部勾选，且指定学习记录非空。紧急恢复需要等待 60 秒并输入 `I ACCEPT RECOVERY`。这是增加分心成本的个人工具，不能保证无法绕过。

自动化测试覆盖解析、代理规则、进程检查、状态流转、恢复、界面辅助和集成流程。测试通过不代表在所有 Windows 环境完成强制模式验收；本仓库不包含个人浏览器资料、推送令牌、实际学习记录或本机运行状态。

## 仓库结构

```text
src/study_lock/          解析、控制、代理、界面等模块
tests/                  自动化测试，使用通用演示工作区
examples/demo-workspace/ 可运行的示例计划与资料
launcher.py             提醒模式启动入口，默认使用仓库父目录作为工作区
```

如需开机启动，可按自己的解释器路径调用 `python -m study_lock.cli startup install --launcher ./launcher.py`；这一步由使用者主动执行。原始本机快捷方式安装器及论文资料生成脚本不在公开包中。

[内容包格式](CONTENT-COCKPIT.md) · [界面使用说明](USAGE-A-PLUS.md) · [来源与归属](THIRD_PARTY_NOTICES.md)
