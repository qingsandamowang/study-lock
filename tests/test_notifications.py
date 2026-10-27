import json
from datetime import date
from pathlib import Path

from study_lock.notifications import (
    PushPlusConfig,
    build_pushplus_payload,
    load_pushplus_config,
    pushplus_config_path,
    save_pushplus_config,
    send_pushplus,
    mark_missed_notification_sent,
    missed_notification_marker_path,
    should_send_missed_notification,
)


def test_pushplus_config_is_saved_under_runtime_and_loaded(tmp_path: Path):
    config = PushPlusConfig(token="secret-token", enabled=True)

    save_pushplus_config(tmp_path, config)

    assert pushplus_config_path(tmp_path) == tmp_path / "study-lock/runtime/pushplus.json"
    assert load_pushplus_config(tmp_path) == config
    payload = json.loads(pushplus_config_path(tmp_path).read_text(encoding="utf-8"))
    assert payload == {"enabled": True, "token": "secret-token"}


def test_pushplus_payload_uses_text_template():
    assert build_pushplus_payload("学习提醒", "今天还有 2 个任务") == {
        "token": "token",
        "title": "学习提醒",
        "content": "今天还有 2 个任务",
        "template": "txt",
    }


def test_send_pushplus_posts_json_and_returns_success(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"code": 200, "msg": "success"}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("study_lock.notifications.urllib.request.urlopen", fake_urlopen)

    result = send_pushplus(PushPlusConfig(token="token", enabled=True), "标题", "内容")

    assert result.ok is True
    assert captured == {
        "url": "https://www.pushplus.plus/send",
        "body": {"token": "token", "title": "标题", "content": "内容", "template": "txt"},
        "timeout": 10,
    }


def test_disabled_or_empty_pushplus_config_does_not_send(monkeypatch):
    monkeypatch.setattr(
        "study_lock.notifications.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not send")),
    )

    disabled = send_pushplus(PushPlusConfig(token="token", enabled=False), "标题", "内容")
    empty = send_pushplus(PushPlusConfig(token="", enabled=True), "标题", "内容")

    assert disabled.ok is False
    assert empty.ok is False


def test_missed_notification_marker_is_scoped_to_the_plan_date(tmp_path: Path):
    marker = missed_notification_marker_path(tmp_path, date(2026, 7, 29))

    assert should_send_missed_notification(marker) is True
    mark_missed_notification_sent(marker)
    assert marker.is_file()
    assert should_send_missed_notification(marker) is False
