# Portfolio Upgrade Implementation Plan

> **For agentic workers:** 按任务使用 executing-plans 或 subagent-driven-development 执行；每个独立项目都有单独计划，必须先完成安全测试再集成。

**Goal:** 修复恢复和记录缺陷，增加配置预检、故障降级与统计导出。
**Architecture:** 复用现有状态/解析模块，新增doctor.py与analytics.py；CLI增加doctor/stats；后台异常用已有SAFE_CONFIG公开状态表示。
**Tech Stack:** Python标准库、Tkinter、psutil、pytest。

### Task 1: 已发现的缺陷
Files: ui.py; records.py; tests/test_recovery.py; tests/test_records.py。
- [ ] 无GUI回归：59.5秒不能提前允许恢复，取消/错短语后可重试，首栏目真实笔记可识别。
- [ ] 实现倒计时ceil/单调时钟、异常提示与gate复位，统一模板栏目匹配；跑测试。

### Task 2: 配置预检与可靠性
Files: doctor.py; runtime.py; state.py; progress.py; cli.py; tests/test_doctor.py; tests/test_runtime.py。
- [ ] 先测坏计划/路径越界/日期不符，以及守卫故障不会静默失效。
```text
python -m study_lock.cli doctor --workspace examples/demo-workspace --plan examples/demo-workspace/study-plans/daily/2026-07-28.md --date 2026-07-28
```
- [ ] 实现doctor只读检查和机器可读输出；无效配置返回非零。
- [ ] 原子状态写入；守卫异常安全降级、资源清理和幂等stop；使用假进程验证。

### Task 3: 统计与演示
Files: analytics.py; cli.py; tests/test_analytics.py; examples/。
- [ ] 先测日期过滤、任务计数、分钟聚合、缺失/损坏记录与CSV转义。
```text
python -m study_lock.cli stats --workspace examples/demo-workspace --from 2026-07-28 --to 2026-07-30 --out OUTPUT
```
- [ ] 生成JSON、CSV、HTML统计；只用通用示例生成可公开演示。
- [ ] 完整测试、模拟命令、doctor、stats验收；禁止真实enforce/通知/开机安装。
- [ ] 更新README/学习说明，独立审查后提交并推送。
