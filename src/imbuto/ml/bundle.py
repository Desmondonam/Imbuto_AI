"""A bundle is the unit of deployment: model files, a model card and their checksums.

The service loads bundles, never loose files, so a running prediction can always be traced to
exact bytes, and a corrupted or edited artifact stops the service at startup, not in the field.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path


class BundleError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bundle(directory: Path, name: str, version: str, card: dict) -> dict:
    """Seal the files already in `directory` by recording their checksums."""
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.name != "bundle.json")
    manifest = {
        "name": name,
        "version": version,
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "files": {p.name: _sha256(p) for p in files},
        "card": card,
    }
    (directory / "bundle.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def load_bundle(directory: Path) -> dict:
    """Return the verified manifest, or raise if anything is missing or changed."""
    manifest_path = directory / "bundle.json"
    if not manifest_path.exists():
        raise BundleError(f"No bundle at {directory}")
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["files"].items():
        path = directory / name
        if not path.exists() or _sha256(path) != expected:
            raise BundleError(f"{manifest['name']}: {name} is missing or has been altered")
    return manifest
