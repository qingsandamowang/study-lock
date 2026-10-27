# Portfolio Upgrade Implementation Plan

> **For agentic workers:** 按任务使用 executing-plans 或 subagent-driven-development 执行；每个独立项目都有单独计划，必须先完成安全测试再集成。

**Goal:** 修复恢复和记录缺陷，增加配置预检、故障降级与统计导出。
**Architecture:** 复用现有状态/解析模块，新增doctor.py与analytics.py；CLI增加doctor/stats；后台异常用已有SAFE_CONFIG公开状态表示。
**Tech Stack:** Python标准库、Tkinter、psutil、pytest。

### Task 1: 已发现的缺陷
Files: ui.py; records.py; tests/test_recovery.py; tests/test_records.py。
- [x] 无GUI回归：59.5秒不能提前允许恢复，取消/错短语后可重试，首栏目真实笔记可识别。
- [x] 实现倒计时ceil/单调时钟、异常提示与gate复位，统一模板栏目匹配；跑测试。

### Task 2: 配置预检与可靠性
Files: doctor.py; runtime.py; state.py; progress.py; cli.py; tests/test_doctor.py; tests/test_runtime.py。
- [x] 先测坏计划/路径越界/日期不符，以及守卫故障不会静默失效。
```text
python -m study_lock.cli doctor --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
```
- [x] 实现doctor只读检查和机器可读输出；无效配置返回非零。
- [x] 原子状态写入；守卫异常安全降级、资源清理和幂等stop；使用假进程验证。

### Task 3: 统计与演示
Files: analytics.py; cli.py; tests/test_analytics.py; examples/。
- [x] 先测日期过滤、任务计数、分钟聚合、缺失/损坏记录与CSV转义。
```text
python -m study_lock.cli stats --workspace examples/demo-workspace --from 2026-07-28 --to 2026-07-30 --out OUTPUT
```
- [x] 生成JSON、CSV、HTML统计；只用通用示例生成可公开演示。
- [x] 完整测试、模拟命令、doctor、stats验收；禁止真实enforce/通知/开机安装。
- [x] 更新README/学习说明，完成独立审查并本地提交；按主任务指令，推送由主任务统一处理。

### 验收记录（2026-10-27）

- 完整 pytest：153 passed；禁用 cacheprovider 并使用独立 basetemp；compileall 与 git diff --check 通过。
- doctor 通用示例：正常日期 PASS/退出码0；错误日期 FAIL/退出码1；`--mode enforce` 只选择预检规则，也通过。未启动强制模式。
- simulate 通用示例：LOCKED，明确 simulation only，无进程或浏览器变更。
- stats 通用工作区：0/15项任务、0天打卡、0个数据问题；生成JSON/CSV/HTML。
- 合成示例报告：3/6项任务、45分钟、1天打卡；明确为虚构数据，生成过程仅使用临时工作区。
- 独立审查发现的重复计时窗口、非80/443端口误判均先回归复现后修复；新增即时守护失败状态返回、巨大数值损坏恢复回归。
- 未运行真实enforce、通知发送或开机安装；进程相关测试均隔离主机并使用假对象。本子任务未推送远端。
