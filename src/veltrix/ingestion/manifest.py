"""Manifest loading, validation, hashing, and metadata enrichment."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veltrix.core.logging import get_logger

logger = get_logger("manifest")

AUTHORITY_RANKS = {
    "policy": 5,
    "addendum": 5,
    "memo": 5,
    "handbook": 5,
    "calendar": 5,
    "faq": 1,
    "wiki": 1,
}

ACCESS_RANKS = {
    "all": 0,
    "managers": 1,
    "hr": 2,
}


@dataclass(frozen=True)
class ManifestItem:
    """Validated metadata for a document from manifest.json."""

    doc_id: str
    file: str
    title: str
    doc_type: str
    regions: list[str]
    effective_date: str  # 'YYYY-MM-DD'
    access_level: str  # 'all' | 'managers' | 'hr'

    @property
    def authority_rank(self) -> int:
        return AUTHORITY_RANKS.get(self.doc_type.lower(), 1)

    @property
    def access_rank(self) -> int:
        return ACCESS_RANKS.get(self.access_level.lower(), 0)

    @property
    def effective_int(self) -> int:
        return int(self.effective_date.replace("-", ""))

    def to_scalar_metadata(self, all_known_regions: set[str] | None = None) -> dict[str, Any]:
        """Convert manifest item into scalar metadata for ChromaDB."""
        regions = {r.upper() for r in self.regions}
        known = all_known_regions or {"IN", "US", "DE", "GLOBAL"}

        meta: dict[str, Any] = {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "authority_rank": self.authority_rank,
            "access_rank": self.access_rank,
            "effective_int": self.effective_int,
            "effective_date": self.effective_date,
        }

        # Add region booleans for filtering
        meta["region_GLOBAL"] = "GLOBAL" in regions
        for r in known:
            if r != "GLOBAL":
                meta[f"region_{r}"] = (r in regions) or ("GLOBAL" in regions)

        return meta


class ManifestLoader:
    """Loads and hashes manifest.json and corpus files."""

    def __init__(self, manifest_path: Path | str, corpus_dir: Path | str) -> None:
        self.manifest_path = Path(manifest_path)
        self.corpus_dir = Path(corpus_dir)

    def load(self) -> list[ManifestItem]:
        """Load and parse manifest.json into ManifestItem instances."""
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest file not found: {self.manifest_path}")

        with open(self.manifest_path, encoding="utf-8") as f:
            data = json.load(f)

        items: list[ManifestItem] = []
        for raw in data:
            item = ManifestItem(
                doc_id=raw["doc_id"].strip(),
                file=raw["file"].strip(),
                title=raw["title"].strip(),
                doc_type=raw["doc_type"].strip().lower(),
                regions=[r.strip().upper() for r in raw.get("regions", ["GLOBAL"])],
                effective_date=raw["effective_date"].strip(),
                access_level=raw.get("access_level", "all").strip().lower(),
            )
            items.append(item)
        return items

    def compute_corpus_hash(self) -> str:
        """Compute SHA256 digest of manifest and all referenced corpus files for idempotency."""
        hasher = hashlib.sha256()

        # Hash manifest contents
        if self.manifest_path.exists():
            with open(self.manifest_path, "rb") as f:
                hasher.update(f.read())

        # Hash each corpus file in deterministic order
        items = self.load()
        for item in sorted(items, key=lambda x: x.file):
            file_path = self.corpus_dir / item.file
            if file_path.exists():
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
            else:
                logger.warning("Corpus file missing during hash computation", file=item.file)

        return hasher.hexdigest()
