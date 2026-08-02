from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretBox:
    def __init__(self, key_path: Path | None = None):
        self.key_path = key_path or settings.data_dir / ".secret_key"
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
        self._fernet = Fernet(key)

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return value
        if value.startswith("enc:"):
            return value
        return "enc:" + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value or not value.startswith("enc:"):
            return value
        try:
            return self._fernet.decrypt(value[4:].encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None


secret_box = SecretBox()

SENSITIVE_KEYS = {"token", "api_key", "password", "access_token", "tmdb_token"}


def protect_config(config: dict) -> dict:
    return {k: secret_box.encrypt(v) if k in SENSITIVE_KEYS and isinstance(v, str) else v for k, v in config.items()}


def reveal_config(config: dict) -> dict:
    return {k: secret_box.decrypt(v) if k in SENSITIVE_KEYS and isinstance(v, str) else v for k, v in config.items()}


def sanitize_config(config: dict) -> dict:
    result = dict(config)
    for key in SENSITIVE_KEYS:
        if result.get(key):
            result[key] = "••••••••"
    return result
