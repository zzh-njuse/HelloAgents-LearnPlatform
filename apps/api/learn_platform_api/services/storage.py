import os
import shutil
from pathlib import Path
from uuid import uuid4


def safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".pdf", ".md", ".txt"} else ""


def resolve_storage_path(root: Path, relative_uri: str) -> Path:
    root_path = root.resolve()
    target = (root_path / relative_uri).resolve()
    if root_path not in target.parents:
        raise ValueError("invalid_storage_uri")
    return target


def atomic_write(root: Path, relative_uri: str, content: bytes) -> None:
    target = resolve_storage_path(root, relative_uri)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_original(root: Path, relative_uri: str, content: bytes) -> None:
    atomic_write(root, relative_uri, content)


def write_parsed(root: Path, relative_uri: str, content: str) -> None:
    atomic_write(root, relative_uri, content.encode("utf-8"))


def read_bytes(root: Path, relative_uri: str) -> bytes:
    return resolve_storage_path(root, relative_uri).read_bytes()


def remove_file(root: Path, relative_uri: str) -> None:
    target = resolve_storage_path(root, relative_uri)
    if target.exists():
        target.unlink()


def remove_tree(root: Path, relative_uri: str) -> None:
    target = resolve_storage_path(root, relative_uri)
    if target.exists():
        shutil.rmtree(target)
