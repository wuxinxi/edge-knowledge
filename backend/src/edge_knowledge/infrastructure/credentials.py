"""Explicit OS credential backends. Never select third-party/plaintext fallbacks."""

import hashlib
import sys
from pathlib import Path

from edge_knowledge.domain.models import AppError


class SystemCredentialStore:
    def __init__(self, directory: Path):
        self.service = "com.tangren.edgeknowledge.deepseek"
        self.account = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
        self._backend = None
        self.backend_name = "system-keychain"

    def _selected(self):
        if self._backend is None:
            if sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
            elif sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring as Keyring
            elif sys.platform.startswith("linux"):
                from keyring.backends.SecretService import Keyring
            else:
                raise RuntimeError("Unsupported system")
            self._backend = Keyring()
        return self._backend

    def get(self) -> str | None:
        try:
            return self._selected().get_password(self.service, self.account)
        except Exception as exc:
            raise AppError(
                "系统凭据库不可用或访问被拒绝，请解锁后重试。", 503, "credential_unavailable"
            ) from exc

    def set(self, value: str) -> None:
        try:
            self._selected().set_password(self.service, self.account, value)
            if self.get() != value:
                raise RuntimeError("Credential verification failed")
        except Exception as exc:
            raise AppError(
                "密钥未能保存到系统凭据库，未写入明文配置。", 503, "credential_unavailable"
            ) from exc

    def delete(self) -> None:
        try:
            if self.get() is not None:
                self._selected().delete_password(self.service, self.account)
            if self.get() is not None:
                raise RuntimeError("Credential removal failed")
        except Exception as exc:
            raise AppError(
                "无法移除系统凭据，请解锁后重试。", 503, "credential_unavailable"
            ) from exc
