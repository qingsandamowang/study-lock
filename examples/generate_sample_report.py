"""Build a deterministic, synthetic report without touching the demo workspace."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from study_lock.analytics import collect_stats, export_stats
from study_lock.progress import DailyProgress, save_daily_progress


def main() -> None:
    output = Path(__file__).resolve().parent / "sample-report"
    with TemporaryDirectory(prefix="study-lock-synthetic-") as temporary:
        workspace = Path(temporary)
        daily = workspace / "study-plans" / "daily"
        daily.mkdir(parents=True)
        for day_number, complete, seconds in ((28, 2, 1800), (29, 1, 900), (30, 0, 0)):
            day = date(2026, 7, day_number)
            tasks = "\n".join(f"- [{'x' if index < complete else ' '}] {label}（{minutes} 分钟）" for index, (label, minutes) in enumerate((("Read generic guide", 10), ("Run sample experiment", 20))))
            (daily / f"{day}.md").write_text(f"# {day} Synthetic demo — day {day_number - 27}\n\n## 任务\n{tasks}\n\n## 允许的应用\n- `code.exe`\n\n## 允许的网站\n- example.com\n\n## 学习记录\n- `notes/{day}.md`\n", encoding="utf-8")
            if complete:
                record = workspace / "notes" / f"{day}.md"
                record.parent.mkdir(exist_ok=True)
                record.write_text("## 今天完成了什么\n- Synthetic example only: compared two outputs.\n", encoding="utf-8")
            save_daily_progress(workspace, DailyProgress(day, checked_in=complete == 2, focus_seconds=seconds))
        report = collect_stats(workspace, date(2026, 7, 28), date(2026, 7, 30))
        report["data_source"] = "Synthetic public demonstration. All task completion and focus values are invented examples, not user activity."
        for path in export_stats(report, output):
            print(path)


if __name__ == "__main__":
    main()
