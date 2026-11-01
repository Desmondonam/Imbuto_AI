"""Runtime configuration, read once from the environment."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(os.environ.get("IMBUTO_ROOT", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"
KNOWLEDGE = ROOT / "knowledge"
LOCALE = ROOT / "locale"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"IMBUTO_{name}", default)


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ENV", "development"))
    db_path: Path = field(default_factory=lambda: Path(_env("DB_PATH", str(DATA / "imbuto.sqlite"))))
    phone_hash_key: str = field(default_factory=lambda: _env("PHONE_HASH_KEY", "dev-only-key"))
    gateway_token: str = field(default_factory=lambda: _env("GATEWAY_TOKEN"))
    ops_token: str = field(default_factory=lambda: _env("OPS_TOKEN"))
    demo_content: bool = field(default_factory=lambda: _env("DEMO_CONTENT", "1") == "1")

    def validate(self) -> None:
        """Refuse to start in production on development secrets."""
        if self.env != "production":
            return
        missing = [
            name
            for name, value in {
                "IMBUTO_PHONE_HASH_KEY": self.phone_hash_key != "dev-only-key",
                "IMBUTO_GATEWAY_TOKEN": self.gateway_token,
                "IMBUTO_OPS_TOKEN": self.ops_token,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Set these before running in production: {', '.join(missing)}")
