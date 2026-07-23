import os
import secrets
import tempfile
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kabel.internal.common.io import get_data_dir

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AUTO_SECRET_KEY_FILE = ".password_secret_key"
SecretKeySource = Literal["configured", "loaded", "generated"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        # Load the backend's .env regardless of the directory from which the
        # CLI is launched. A .env in the current working directory remains the
        # higher-priority override for installed/deployed instances.
        env_file=(_PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    SCHEME: str = "http"
    HOST: str = "localhost"
    PORT: str = "8000"
    API_V1_STR: str = "/api/v1"
    MEDIA_HOST: str = f"{SCHEME}://{HOST}:{PORT}"

    BASE_DATA_DIR: str = get_data_dir()
    MEDIA_ROOT: Path = Path(BASE_DATA_DIR).joinpath("media")
    UPLOAD_DIR: str = "upload"
    EXPORT_DIR: str = "export"
    UPLOAD_FILE_MAX_SIZE: int = 200_000_000  # ~200MB
    THUMBNAIL_HEIGH_PIXEL: int = 120
    STORAGE_BACKEND: str = "local"

    S3_ENDPOINT: str = ""
    S3_REGION: str = ""
    S3_BUCKET: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PUBLIC_BASE_URL: str = ""
    S3_PRESIGN_EXPIRE_SECONDS: int = 3600
    S3_PATH_STYLE: bool = False
    S3_USE_SSL: bool = True

    # Allow user-configured data-source S3 endpoints to point at private
    # networks (RFC1918 / ULA / loopback). Enabled by default for on-prem
    # deployments that use an internal MinIO/S3-compatible store. Even when
    # enabled, link-local (cloud metadata 169.254.0.0/16), multicast,
    # reserved and unspecified addresses are always rejected. Set to false to
    # restrict data-source endpoints to public hosts only (strict SSRF mode).
    ALLOW_PRIVATE_S3_ENDPOINT: bool = True

    AI_AUTO_LABEL_ENABLED: bool = False
    AI_PROVIDER: str = "local_http"
    AI_MODEL_ENDPOINT: str = ""
    AI_MODEL_TIMEOUT_SECONDS: int = 300
    AI_MODEL_NAME: str = ""
    AI_IMAGE_URL_EXPIRE_SECONDS: int = 300

    DATABASE_URL: str = Field(
        default="mysql+pymysql://root:root@localhost:3306/kabel",
        description="Database connection URL. Supports SQLite and MySQL."
    )

    PASSWORD_SECRET_KEY: str = Field(
        default="",
        description="JWT secret key. Generate with: openssl rand -hex 32. MUST be set in production."
    )

    TOKEN_GENERATE_ALGORITHM: str = "HS256"
    TOKEN_ACCESS_EXPIRE_MINUTES: int = 30
    # Sliding refresh: when an authenticated request arrives with a token whose
    # remaining lifetime is below this many minutes, a freshly issued token is
    # returned via the `X-New-Token` response header so active users never get
    # logged out. Should be smaller than TOKEN_ACCESS_EXPIRE_MINUTES.
    TOKEN_REFRESH_THRESHOLD_MINUTES: int = 15
    TOKEN_TYPE: str = "Bearer"
    EXPOSE_INTERNAL_ERRORS: bool = False

    @property
    def need_migration_to_mysql(self) -> bool:
        sqlite_path = Path(self.BASE_DATA_DIR) / "kabel.sqlite"
        return (
            self.DATABASE_URL.startswith('mysql') and 
            sqlite_path.exists()
        )


settings = Settings()
os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
logger.info("Database and media directory: {}", settings.BASE_DATA_DIR)


def ensure_password_secret_key() -> SecretKeySource:
    """Ensure an unconfigured secret key remains stable across restarts.

    Production deployments should set ``PASSWORD_SECRET_KEY`` explicitly. For
    local installations that do not, persist the generated fallback alongside
    the application's data instead of replacing it on every process start.
    """
    if settings.PASSWORD_SECRET_KEY:
        return "configured"

    data_dir = Path(settings.BASE_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / _AUTO_SECRET_KEY_FILE

    if key_path.exists():
        secret_key = key_path.read_text(encoding="utf-8").strip()
        if not secret_key:
            raise RuntimeError(
                f"Auto-generated secret key file is empty: {key_path}"
            )
        settings.PASSWORD_SECRET_KEY = secret_key
        return "loaded"

    secret_key = secrets.token_hex(32)
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{_AUTO_SECRET_KEY_FILE}.",
            dir=data_dir,
        )
        temp_path = Path(temp_name)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as secret_file:
            secret_file.write(secret_key)
            secret_file.flush()
            os.fsync(secret_file.fileno())

        try:
            # A hard link publishes the fully-written file atomically and lets
            # concurrent workers agree on whichever key was created first.
            os.link(temp_path, key_path)
        except FileExistsError:
            secret_key = key_path.read_text(encoding="utf-8").strip()
            if not secret_key:
                raise RuntimeError(
                    f"Auto-generated secret key file is empty: {key_path}"
                )
            settings.PASSWORD_SECRET_KEY = secret_key
            return "loaded"
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    settings.PASSWORD_SECRET_KEY = secret_key
    return "generated"
