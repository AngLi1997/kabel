from pathlib import Path

from kabel.internal.common.config import (
    _AUTO_SECRET_KEY_FILE,
    _PROJECT_ROOT,
    ensure_password_secret_key,
    settings,
)
from kabel.internal.common.crypto import decrypt_value, encrypt_value


def test_backend_env_file_is_independent_of_working_directory():
    env_files = settings.model_config["env_file"]

    assert env_files[0] == _PROJECT_ROOT / ".env"
    assert env_files[1] == ".env"


def test_auto_generated_secret_key_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BASE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PASSWORD_SECRET_KEY", "")

    assert ensure_password_secret_key() == "generated"
    first_key = settings.PASSWORD_SECRET_KEY
    ciphertext = encrypt_value("secret-access-key")

    key_path = Path(tmp_path) / _AUTO_SECRET_KEY_FILE
    assert key_path.read_text(encoding="utf-8") == first_key
    assert key_path.stat().st_mode & 0o777 == 0o600

    # Simulate a fresh process whose Settings object has no configured key.
    monkeypatch.setattr(settings, "PASSWORD_SECRET_KEY", "")

    assert ensure_password_secret_key() == "loaded"
    assert settings.PASSWORD_SECRET_KEY == first_key
    assert decrypt_value(ciphertext) == "secret-access-key"


def test_configured_secret_key_does_not_create_fallback_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "BASE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PASSWORD_SECRET_KEY", "configured-secret")

    assert ensure_password_secret_key() == "configured"
    assert not (Path(tmp_path) / _AUTO_SECRET_KEY_FILE).exists()
