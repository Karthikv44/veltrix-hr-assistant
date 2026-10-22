"""Script to programmatically create a mutated corpus to prove zero hard-coding (Must-Pass Check 5).

Usage:
    uv run python scripts/mutate_corpus.py --target-dir ./data_mutated
"""

import argparse
import shutil
from pathlib import Path


def mutate_corpus(source_dir: Path, target_dir: Path) -> None:
    """Create a mutated copy of the corpus and manifest."""
    source_corpus = source_dir / "corpus"
    source_manifest = source_dir / "manifest.json"

    target_corpus = target_dir / "corpus"
    target_manifest = target_dir / "manifest.json"

    if target_dir.exists():
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_corpus, target_corpus)
    shutil.copy2(source_manifest, target_manifest)

    # 1. Mutate a holiday calendar
    holidays_file = target_corpus / "cal_holidays_in_2026.csv"
    if holidays_file.exists():
        content = holidays_file.read_text(encoding="utf-8")
        mutated_content = content + "\n2026-11-15,Founders Day,Public,IN\n"
        holidays_file.write_text(mutated_content, encoding="utf-8")
        print(f"Mutated {holidays_file.name}: appended Founders Day holiday.")

    # 2. Mutate a policy document
    md_files = list(target_corpus.glob("*.md"))
    if md_files:
        p = md_files[0]
        text = p.read_text(encoding="utf-8")
        p.write_text(
            text
            + "\n\n## Mutated Special Benefit\nAll employees receive 42 wellness stipends annually.\n",
            encoding="utf-8",
        )
        print(f"Mutated {p.name}: appended mutated policy section.")

    print(f"Mutated corpus created successfully at {target_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mutate corpus to test dynamic ingestion.")
    parser.add_argument(
        "--source-dir", type=Path, default=Path("./data"), help="Path to original data directory"
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("./data_mutated"),
        help="Path to mutated target directory",
    )
    args = parser.parse_args()

    mutate_corpus(args.source_dir, args.target_dir)


if __name__ == "__main__":
    main()
