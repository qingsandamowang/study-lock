from pathlib import Path

from study_lock.cli import main


def test_cli_startup_install_dispatches_without_running_real_schtasks(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(
        "study_lock.cli.install_startup",
        lambda python_executable, launcher: calls.append((python_executable, launcher)),
    )

    result = main(
        [
            "startup",
            "install",
            "--python",
            "python.exe",
            "--launcher",
            str(tmp_path / "launcher.py"),
        ]
    )

    assert result == 0
    assert calls == [("python.exe", tmp_path / "launcher.py")]


def test_cli_startup_remove_dispatches_to_exact_task(monkeypatch):
    called = []
    monkeypatch.setattr("study_lock.cli.remove_startup", lambda: called.append(True))

    assert main(["startup", "remove"]) == 0
    assert called == [True]
