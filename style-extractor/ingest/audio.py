"""Podcast ingestion — reads pre-made .txt transcripts from raw_content/podcasts/."""
from __future__ import annotations

import json
from pathlib import Path

import config


def ingest_podcasts(skip_diarization: bool = False) -> list[dict]:
    """
    Read all .txt transcript files from raw_content/podcasts/.
    Returns list of transcript dicts (cached to processed/transcripts/).
    The skip_diarization flag is accepted for CLI compatibility but ignored.
    """
    config.ensure_dirs()

    txt_files = sorted(
        f for f in config.PODCASTS_RAW_DIR.iterdir()
        if f.suffix.lower() == ".txt"
    )

    if not txt_files:
        print("  [podcasts] No .txt files found in raw_content/podcasts/")
        return []

    results = []
    for txt_file in txt_files:
        cache_path = config.TRANSCRIPTS_DIR / f"{txt_file.stem}.json"

        if cache_path.exists():
            print(f"  [podcasts] Using cached → {cache_path.name}")
            with open(cache_path, "r", encoding="utf-8") as fh:
                results.append(json.load(fh))
            continue

        print(f"  [podcasts] Reading: {txt_file.name}")
        text = txt_file.read_text(encoding="utf-8", errors="ignore").strip()

        result = {
            "text":     text,
            "language": "he",
            "diarized": False,
            "source":   txt_file.name,
        }

        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"  [podcasts] Saved → {cache_path.name}")
        results.append(result)

    print(f"  [podcasts] Loaded {len(results)} transcript(s).")
    return results
