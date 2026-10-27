# Study Lock 学习与验证路线

这是一个本地 Python 项目：Markdown 提供计划，Tkinter 展示任务，JSON 保存每日进度，规则模块决定允许行为。没有训练模型或云端学习数据服务。

## 先运行只读预检

在仓库根目录安装 `python -m pip install -e . pytest`，再运行：

```powershell
python -m study_lock.cli doctor --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
python -m study_lock.cli doctor --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28 --json
```

doctor 检查工作区与计划路径、计划语法和日期、记录路径、每项本地资源、应用名与域名规则。路径越出工作区、资源缺失和日期不匹配会返回退出码 1；计划合法时，尚未创建的学习记录只是 warning。浏览器检查默认跳过；可用 `--check-browser` 自动定位 Chrome，或用 `--browser C:/path/chrome.exe` 验证指定文件存在。

预检不创建目录、不修复文件、不发送请求、不启动代理、不枚举进程，也不启动浏览器。URL 只检查语法，浏览器只检查文件存在；不会验证网络可达性、浏览器版本或运行权限。

用 `--mode enforce` 可以针对强制模式做预检，仍不会启动限制。受控代理只支持端口 80/443；其他端口的资源在强制模式预检时报错，在默认提醒模式预检时提示 warning。

## 按数据流读代码

1. `models.py` → `plan_parser.py`：学习日期、任务、白名单、资源如何从 Markdown 变成 Python 对象。存在“执行流程”时，它是任务进度的唯一计数来源，避免与“任务”重复统计。
2. `records.py` → `unlock.py`：完成任务后，检查真实笔记。新模板的“今天完成了什么”和旧版“今日完成”都接受；模板说明、空项目符号、空复选框和预填任务不算笔记。旧版无模板的纯文本笔记仍可使用，不需要迁移文件。
3. `state.py` → `progress.py` → `storage.py`：运行状态和每日进度先写同目录临时文件、flush/fsync，再原子替换。进度保留上一份有效 JSON 的 `.bak`；主文件内容或字段类型损坏时尝试备份，统计报告会说明降级。完全不可用时读为空进度，不把字符串 `"false"` 当成已打卡。
4. `recovery.py` → `ui.py`：恢复条件使用单调时钟和 `gate.ready()`，界面剩余秒数向上取整。59.5 秒不会提前弹出确认；取消、短语错误或写入失败后都能重新请求并开始完整倒计时。
5. `browser.py` → `process_guard.py` → `runtime.py`：浏览器归属记录 PID 与创建时间，每轮刷新集合；当前受控 profile 参数可以提供新的归属证据。关闭前再次核验身份，失效 PID 不会永久保留。守护线程异常会记录 `guard_failed`、进入 SAFE_CONFIG、停止限制并尽力清理资源；界面显示错误并允许关闭。磁盘不可写时仍保留内存中的错误状态，`health_error`/`cleanup_errors` 可用于诊断。
6. `doctor.py` → `analytics.py` → `cli.py`：把检查、聚合、导出与有副作用的运行会话分开。HTML 转义标题；CSV 用标准库处理引号/逗号，对公式前缀加单引号。

## 学习统计的含义

```powershell
python -m study_lock.cli stats --workspace examples/demo-workspace --from 2026-07-28 --to 2026-07-30 --out reports/demo
```

日期范围含首尾两天。输出 `summary.json`（完整汇总、每日数据与问题列表）、`daily.csv`（一日一行）、`report.html`（可离线打开，无外部资源）。源计划、笔记和进度保持只读；仅指定输出目录会写文件。报告包含计划标题，不包含笔记正文或事件日志。导出个人计划前应自行检查标题是否适合分享。

| 字段 | 定义 |
| --- | --- |
| `tasks_total` / `tasks_completed` | 执行流程或任务中的总数与已勾选数 |
| `planned_minutes` | 标签中明确写出的分钟，如 `阅读（10 分钟）`，无时长标签计 0 |
| `completed_planned_minutes` | 已勾选任务的计划分钟估算，不代表真实学习时间 |
| `focus_minutes` | 界面计时器运行时记录的单调时钟秒数 ÷ 60；暂停不累计，旧数据缺字段计 0 |
| `checked_in_days` | 每日进度中明确保存为布尔 `true` 的打卡天数，独立于勾选比例 |
| `carryovers_total` / `carryovers_completed` | 顺延项目的数量；与当天任务分列，避免重复加到任务分母 |

缺失或损坏的计划仍保留当天行，异常数据列入 `warnings`。缺失学习记录显示 `record_has_notes=false`。统计完成不等于数据完整，应同时查看问题列表。计时器数据是本地应用记录，不是人在电脑前持续学习的证明；异常退出可能丢失最后一次回调后的少量秒数，系统暂停可能影响测量，不做跨进程同时写入合并。

同一主窗口只保留一个计时器，重复点击会聚焦已有窗口；切换日期或关闭主窗口时先结算并关闭计时器，避免同一段时间被多个窗口重复累计。

直接查看 [合成示例报告](examples/sample-report/report.html)。重建它：`python examples/generate_sample_report.py`。脚本只在临时目录创建通用计划和虚构的进度值，生成固定的 3/6 项任务、45 分钟计时与 1 天打卡示例，不读个人工作区。示例数值仅用于说明字段。

## 安全回归与边界

```powershell
python -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/study-lock-check-$([guid]::NewGuid().ToString('N'))"
python -m study_lock.cli simulate --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
```

测试夹具将进程枚举置空、真实 `psutil.Process` 查询置为不存在，并阻止真实 terminate/kill；需要进程行为的用例只注入假对象。强制模式的测试调用同样只使用假浏览器与假进程。测试不会安装开机任务，也不会发送通知。默认 UI 仍是提醒模式。

故障降级不是操作系统级沙箱：清理失败时记录错误并继续处理其他资源，后台线程 join 有超时，Python 无法强行终止阻塞的第三方线程。浏览器 PID/创建时间及 profile 检查缩小误认范围，不能消除所有操作系统级竞态；强制模式仍需要用户在目标机器独立验收。这里的验收只使用回归测试、只读预检和模拟命令。
