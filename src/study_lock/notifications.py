from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path


PUSHPLUS_ENDPOINT = "https://www.pushplus.plus/send"


@dataclass(frozen=True)
class PushPlusConfig:
    token: str = ""
    enabled: bool = False


@dataclass(frozen=True)
class NotificationResult:
    ok: bool
    message: str


def pushplus_config_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / "study-lock" / "runtime" / "pushplus.json"


def load_pushplus_config(workspace_root: Path) -> PushPlusConfig:
    path = pushplus_config_path(workspace_root)
    if not path.is_file():
        return PushPlusConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PushPlusConfig(
            token=str(payload.get("token", "")).strip(),
            enabled=bool(payload.get("enabled", False)),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return PushPlusConfig()


def save_pushplus_config(workspace_root: Path, config: PushPlusConfig) -> Path:
    path = pushplus_config_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"enabled": bool(config.enabled), "token": config.token.strip()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def missed_notification_marker_path(workspace_root: Path, plan_date: date) -> Path:
    return Path(workspace_root) / "study-lock" / "runtime" / f"pushplus-missed-{plan_date.isoformat()}.marker"


def should_send_missed_notification(marker: Path) -> bool:
    return not Path(marker).is_file()


def mark_missed_notification_sent(marker: Path) -> None:
    marker = Path(marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("missed notification sent\n", encoding="utf-8")


def build_pushplus_payload(title: str, content: str, *, token: str = "token") -> dict[str, str]:
    return {
        "token": token,
        "title": title,
        "content": content,
        "template": "txt",
    }


def send_pushplus(config: PushPlusConfig, title: str, content: str, *, timeout: int = 10) -> NotificationResult:
    token = config.token.strip()
    if not config.enabled:
        return NotificationResult(False, "微信通知未启用")
    if not token:
        return NotificationResult(False, "PushPlus Token 为空")

    payload = build_pushplus_payload(title, content, token=token)
    request = urllib.request.Request(
        PUSHPLUS_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return NotificationResult(False, f"微信通知发送失败：{exc}")

    if str(result.get("code")) == "200":
        return NotificationResult(True, "微信通知已发送")
    return NotificationResult(False, f"PushPlus 返回失败：{result.get('msg', '未知错误')}")
