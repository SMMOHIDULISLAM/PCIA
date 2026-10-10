from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .models import ManifestItem
from .utils import ensure_within_directory, sha256_file


class PackageIngestor:
    def __init__(self, max_nested_depth: int = 4) -> None:
        self.max_nested_depth = max_nested_depth

    def ingest(self, proposal_path: Path, work_dir: Path) -> tuple[Path, list[ManifestItem]]:
        source_dir = work_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        if proposal_path.suffix.lower() == ".zip":
            self._extract_zip(proposal_path, source_dir, depth=0)
        elif proposal_path.is_file():
            shutil.copy2(proposal_path, source_dir / proposal_path.name)
        else:
            raise FileNotFoundError(f"Proposal package not found: {proposal_path}")

        manifest: list[ManifestItem] = []
        for file_path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            relative = file_path.relative_to(source_dir).as_posix()
            manifest.append(
                ManifestItem(
                    relative_path=relative,
                    file_type=file_path.suffix.lower().lstrip(".") or "unknown",
                    size_bytes=file_path.stat().st_size,
                    sha256=sha256_file(file_path),
                    status="inventoried",
                )
            )
        return source_dir, manifest

    def _extract_zip(self, zip_path: Path, destination: Path, depth: int) -> None:
        if depth > self.max_nested_depth:
            raise ValueError(f"Nested ZIP depth exceeds {self.max_nested_depth}: {zip_path}")

        with zipfile.ZipFile(zip_path) as archive:
            for member in sorted(archive.infolist(), key=lambda x: x.filename.casefold()):
                if member.is_dir():
                    continue
                target = destination / member.filename
                ensure_within_directory(destination, target)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        nested = sorted(destination.rglob("*.zip"))
        for nested_zip in nested:
            nested_destination = nested_zip.with_suffix("")
            nested_destination.mkdir(parents=True, exist_ok=True)
            self._extract_zip(nested_zip, nested_destination, depth + 1)
