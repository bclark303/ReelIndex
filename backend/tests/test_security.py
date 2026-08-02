from pathlib import Path

from app.core.security import SecretBox


def test_secret_box_roundtrip(tmp_path: Path):
    box = SecretBox(tmp_path / "key")
    encrypted = box.encrypt("secret-token")
    assert encrypted and encrypted.startswith("enc:")
    assert box.decrypt(encrypted) == "secret-token"
