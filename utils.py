from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


SPACE_RE = re.compile(r"\s+")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_filename(value: str, default: str = "case") -> str:
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:100] or default


def normalize_spaces(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()




def normalize_document_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [normalize_spaces(line) for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("–", "-").replace("—", "-")
    return normalize_spaces(text).casefold()


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def ensure_within_directory(base_dir: Path, target: Path) -> None:
    base = base_dir.resolve()
    resolved = target.resolve()
    if os.path.commonpath([str(base), str(resolved)]) != str(base):
        raise ValueError(f"Unsafe archive path: {target}")
