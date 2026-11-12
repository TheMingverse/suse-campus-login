import base64
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

from .models import Settings, valid_service_name
from .windows import protect


def data_dir() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SUSECampusLogin"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SettingsStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_dir()
        self.path = self.directory / "settings.json"

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        password = protect(base64.b64decode(data["protected_password"], validate=True), decrypt=True).decode("utf-8")
        service = data.get("service", "宜宾移动")
        if not valid_service_name(service):
            raise ValueError("保存的运营商无法识别，请重新选择")
        enabled = data.get("notifications_enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("系统通知设置格式无效")
        return Settings(data["username"], password, service, bool(data.get("autostart", True)), enabled)

    def save(self, settings: Settings):
        if not valid_service_name(settings.service):
            raise ValueError("上网服务名称格式无效")
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1, "username": settings.username, "service": settings.service,
            "autostart": settings.autostart,
            "notifications_enabled": settings.notifications_enabled,
            "protected_password": base64.b64encode(protect(settings.password.encode("utf-8"))).decode("ascii"),
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def status_logger():
    logger = logging.getLogger("campus_status")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(data_dir() / "status.log", maxBytes=128000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger

