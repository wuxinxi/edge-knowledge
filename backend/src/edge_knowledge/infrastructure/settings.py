import json
import os
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from edge_knowledge.application.ports import CredentialStore
from edge_knowledge.domain.models import AppError


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "https://api.deepseek.com"
    model: str = Field(default="deepseek-flash", min_length=1, max_length=100)
    image_qa_mode: Literal["local_ocr", "cloud_vision"] = "local_ocr"
    stream: bool = True
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.2, ge=-1, le=1)
    chunk_size: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)

    @model_validator(mode="after")
    def validate_rules(self):
        # Only the declared cloud destination can receive retrieved document text.
        if self.base_url not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise ValueError("仅支持官方 DeepSeek HTTPS 地址。")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("重叠长度必须小于切片长度。")
        if self.model != self.model.strip():
            raise ValueError("模型名不能包含首尾空格。")
        return self


class JsonSettingsStore:
    def __init__(
        self, directory: Path, initial_key: str = "", credentials: CredentialStore | None = None
    ):
        self.path = directory / "settings.json"
        self._lock = RLock()
        self._initial_key = initial_key
        self.credentials = credentials
        self._key: str | None = None
        self._override = False
        self._credential_error = ""
        self._migration_pending = False
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._data = UserSettings().model_dump()
        legacy_present, legacy_key = False, None
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                legacy_present = "api_key" in saved
                legacy_key = saved.pop("api_key", None)
                self._override = saved.pop("credential_override", False)
                if not isinstance(self._override, bool) or (
                    legacy_key is not None and not isinstance(legacy_key, str)
                ):
                    raise ValueError("Invalid credential metadata")
                self._data = UserSettings.model_validate(saved).model_dump()
            except (ValueError, TypeError) as exc:
                raise AppError("本地配置文件无效，请检查 settings.json。", 500) from exc
        try:
            if legacy_present:
                if legacy_key is not None:
                    self._credential_store().set(
                        legacy_key.strip()
                    ) if legacy_key.strip() else self._credential_store().delete()
                    self._override = True
                    self._key = legacy_key.strip()
                self._write(self._data, self._override)
            elif self._override:
                self._key = self._credential_store().get() or ""
        except AppError as exc:
            self._credential_error = exc.message
            self._migration_pending = legacy_present and legacy_key is not None
            self._key = ""
        except OSError as exc:
            raise AppError("配置迁移未完成，原文件已保留，请检查磁盘空间和权限。", 500) from exc

    def _credential_store(self) -> CredentialStore:
        if self.credentials is None:
            raise AppError("系统凭据库尚未配置，不能保存密钥。", 503, "credential_unavailable")
        return self.credentials

    def _write(self, values: dict, override: bool):
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(
                    {**values, "credential_override": override},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self) -> dict:
        with self._lock:
            return {
                **self._data,
                "api_key_configured": bool(self.api_key()),
                "credential_storage": self.credentials.backend_name
                if self.credentials and not self._credential_error
                else "unavailable",
                "credential_message": self._credential_error,
                "credential_migration_pending": self._migration_pending,
            }

    def api_key(self) -> str:
        with self._lock:
            if self._credential_error:
                return ""
            return (self._key or "") if self._override else self._initial_key

    def update(self, changes: dict) -> dict:
        with self._lock:
            values = {**self._data, **{k: v for k, v in changes.items() if k != "api_key"}}
            try:
                validated = UserSettings.model_validate(values).model_dump()
            except ValidationError as exc:
                raise AppError("配置参数无效，请检查切片长度、模型名称和地址。") from exc
            if self._migration_pending and "api_key" not in changes:
                raise AppError(
                    "旧密钥尚未迁移，请先解锁凭据库并重新保存密钥。",
                    409,
                    "credential_migration_pending",
                )
            changed = "api_key" in changes and changes["api_key"] is not None
            override = self._override or changed
            previous = None
            key = self._key
            if changed:
                credential = self._credential_store()
                previous = credential.get()
                key = changes["api_key"].strip()
            try:
                if changed:
                    credential.set(key) if key else credential.delete()
                self._write(validated, override)
            except (OSError, AppError) as exc:
                if changed:
                    try:
                        credential.set(previous) if previous else credential.delete()
                    except AppError:
                        self._credential_error = "配置写入失败，凭据回滚未完成，请重新保存密钥。"
                if isinstance(exc, AppError):
                    raise
                raise AppError("配置保存失败，请检查磁盘空间和权限。", 500) from exc
            self._data, self._override, self._key = validated, override, key
            if changed:
                self._credential_error = ""
                self._migration_pending = False
            return self.read()
