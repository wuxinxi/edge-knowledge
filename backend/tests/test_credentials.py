import json

import pytest
from conftest import MemoryCredentials

from edge_knowledge.domain.models import AppError
from edge_knowledge.infrastructure.credentials import SystemCredentialStore
from edge_knowledge.infrastructure.settings import JsonSettingsStore


def test_legacy_key_migrates_without_plaintext_and_removal_survives_reload(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"api_key": "legacy-fixture-secret", "top_k": 3}))
    credentials = MemoryCredentials()
    settings = JsonSettingsStore(tmp_path, "env-fixture", credentials)
    assert credentials.get() == "legacy-fixture-secret"
    assert "legacy-fixture-secret" not in path.read_text() and "api_key" not in json.loads(
        path.read_text()
    )
    assert settings.read()["credential_migration_pending"] is False
    assert "legacy-fixture-secret" not in json.dumps(settings.read())
    assert (
        JsonSettingsStore(tmp_path, "env-fixture", credentials).api_key() == "legacy-fixture-secret"
    )
    settings.update({"api_key": ""})
    assert credentials.get() is None
    assert JsonSettingsStore(tmp_path, "env-fixture", credentials).api_key() == ""


def test_failed_migration_preserves_old_file_and_blocks_overwrite(tmp_path):
    class Unavailable(MemoryCredentials):
        def set(self, value):
            raise AppError("System unavailable", 503, "credential_unavailable")

    path = tmp_path / "settings.json"
    original = json.dumps({"api_key": "legacy-fixture-secret", "top_k": 3})
    path.write_text(original)
    settings = JsonSettingsStore(tmp_path, credentials=Unavailable())
    assert settings.read()["credential_migration_pending"] is True
    assert settings.api_key() == "" and path.read_text() == original
    with pytest.raises(AppError):
        settings.update({"top_k": 7})
    assert path.read_text() == original
    settings.credentials = MemoryCredentials()
    settings.update({"api_key": "replacement-fixture"})
    assert "api_key" not in json.loads(path.read_text())
    assert settings.api_key() == "replacement-fixture"


def test_write_failure_rolls_credential_back(tmp_path, monkeypatch):
    credentials = MemoryCredentials()
    settings = JsonSettingsStore(tmp_path, credentials=credentials)
    settings.update({"api_key": "original-fixture"})
    original = settings.path.read_text()

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(settings, "_write", fail)
    with pytest.raises(AppError):
        settings.update({"api_key": "replacement-fixture", "top_k": 8})
    assert credentials.get() == "original-fixture"
    assert settings.api_key() == "original-fixture"
    assert settings.path.read_text() == original


def test_missing_system_store_never_falls_back_to_plaintext(tmp_path):
    settings = JsonSettingsStore(tmp_path)
    with pytest.raises(AppError) as error:
        settings.update({"api_key": "fixture-secret"})
    assert error.value.code == "credential_unavailable"
    assert not settings.path.exists()


def test_adapter_scopes_accounts_and_sanitizes_driver_errors(tmp_path):
    first = SystemCredentialStore(tmp_path / "one")
    second = SystemCredentialStore(tmp_path / "two")
    assert first.account != second.account

    class Failing:
        def get_password(self, *_):
            raise RuntimeError("driver-secret-must-not-escape")

    first._backend = Failing()
    with pytest.raises(AppError) as error:
        first.get()
    assert "driver-secret" not in str(error.value)


def test_adapter_verifies_writes_and_removes_only_its_entry(tmp_path):
    store = SystemCredentialStore(tmp_path)
    calls = []

    class Backend:
        value = None

        def get_password(self, service, account):
            calls.append((service, account))
            return self.value

        def set_password(self, service, account, value):
            calls.append((service, account))
            self.value = value

        def delete_password(self, service, account):
            calls.append((service, account))
            self.value = None

    store._backend = Backend()
    store.set("fixture-secret")
    assert store.get() == "fixture-secret"
    store.delete()
    assert store.get() is None
    assert all(call == (store.service, store.account) for call in calls)


def test_partial_driver_failure_rolls_back_previous_credential(tmp_path):
    class Partial(MemoryCredentials):
        def set(self, value):
            self.value = value
            if value == "failing-replacement":
                raise AppError("Verification failed", 503, "credential_unavailable")

    credentials = Partial()
    settings = JsonSettingsStore(tmp_path, credentials=credentials)
    settings.update({"api_key": "previous-fixture"})
    with pytest.raises(AppError):
        settings.update({"api_key": "failing-replacement"})
    assert credentials.get() == "previous-fixture"
    assert settings.api_key() == "previous-fixture"
