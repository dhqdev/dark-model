"""Armazenamento dos arquivos gerados. Hoje: disco local (volume Docker).

A interface é pequena de propósito para permitir trocar por S3/R2 no futuro.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from .config import get_settings


class StorageError(Exception):
    pass


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise StorageError(f"caminho fora do storage: {rel}")
        return p

    def write_bytes(self, rel: str, data: bytes) -> int:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return len(data)

    def import_file(self, rel: str, src: Path) -> int:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), p)
        return p.stat().st_size

    def read_bytes(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()

    def exists(self, rel: str) -> bool:
        try:
            return self.path(rel).exists()
        except StorageError:
            return False

    def size(self, rel: str) -> int:
        return self.path(rel).stat().st_size

    def delete(self, rel: str) -> None:
        try:
            self.path(rel).unlink(missing_ok=True)
        except StorageError:
            pass

    def delete_tree(self, rel: str) -> None:
        p = self.path(rel)
        if p.exists() and p != self.root:
            shutil.rmtree(p, ignore_errors=True)

    def tmp_dir(self) -> Path:
        d = self.root / ".tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def usage_bytes(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.root):
            for f in files:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    pass
        return total


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    root = get_settings().storage_dir
    if _storage is None or _storage.root != root.resolve():
        _storage = LocalStorage(root)
    return _storage


def project_dir(project_id: int) -> str:
    return f"projects/{project_id}"
