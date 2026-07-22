from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
WORKBOOK_PATH = ROOT / "TEPS_Voca(통합).xlsx"
PRONUNCIATION_PATH = ROOT / "pronunciations.json"
MEANING_OVERRIDE_PATH = ROOT / "meaning_overrides.json"
EXAMPLE_OVERRIDE_PATH = ROOT / "example_overrides.json"
OUTPUT_PATH = ROOT / "words-data.js"

FREQUENT_SHEET = "어휘단어장(통합)"
ROUTINE_CHUNK_COUNT = 10
CLOZE_TOKEN_OVERRIDES = {
    "cloak a in the guise of b": "cloak",
    "give ~ a shot": "give",
    "jump the gun": "the",
    "keep one's fingers crossed": "fingers",
    "take ~for a ride": "take",
    "throw one's weight behind": "weight",
}


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_key(value) -> str:
    return clean(value).lower()


def load_pronunciations() -> dict[str, str]:
    if not PRONUNCIATION_PATH.exists():
        return {}

    payload = json.loads(PRONUNCIATION_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("entries"), dict):
        return {normalize_key(key): clean(value) for key, value in payload["entries"].items()}
    if isinstance(payload, dict):
        return {normalize_key(key): clean(value) for key, value in payload.items()}
    return {}


def load_meaning_overrides() -> dict[str, str]:
    if not MEANING_OVERRIDE_PATH.exists():
        return {}

    payload = json.loads(MEANING_OVERRIDE_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("entries"), dict):
        return {normalize_key(key): clean(value) for key, value in payload["entries"].items()}
    if isinstance(payload, dict):
        return {normalize_key(key): clean(value) for key, value in payload.items()}
    return {}


def load_example_overrides() -> dict[str, dict[str, str]]:
    if not EXAMPLE_OVERRIDE_PATH.exists():
        return {}

    payload = json.loads(EXAMPLE_OVERRIDE_PATH.read_text(encoding="utf-8"))
    raw_entries = payload.get("entries", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_entries, dict):
        return {}

    entries: dict[str, dict[str, str]] = {}
    for key, value in raw_entries.items():
        if not isinstance(value, dict):
            continue
        entries[normalize_key(key)] = {
            field: clean(value.get(field))
            for field in ("word", "exampleEn", "exampleKo")
            if clean(value.get(field))
        }
    return entries


def get_example_override(
    overrides: dict[str, dict[str, str]],
    word_id: str,
    word: str,
) -> dict[str, str]:
    return overrides.get(normalize_key(word_id)) or overrides.get(normalize_key(word)) or {}


def find_cloze_target(term: str, sentence: str) -> tuple[str, int, int] | None:
    if not term or not sentence:
        return None

    override_token = CLOZE_TOKEN_OVERRIDES.get(normalize_key(term))
    if override_token:
        override = re.search(rf"\b{re.escape(override_token)}\b", sentence, flags=re.IGNORECASE)
        if override:
            return override.group(0), override.start(), override.end()

    exact_pattern = re.escape(term).replace(r"\ ", r"\s+")
    exact = re.search(exact_pattern, sentence, flags=re.IGNORECASE)
    if exact:
        return exact.group(0), exact.start(), exact.end()

    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", term)
    matches = []
    for token in dict.fromkeys(tokens):
        match = re.search(rf"\b{re.escape(token)}\b", sentence, flags=re.IGNORECASE)
        if match:
            matches.append((token, match))
    if matches:
        max_length = max(len(token) for token, _ in matches)
        _, match = max(
            ((token, match) for token, match in matches if len(token) == max_length),
            key=lambda item: item[1].start(),
        )
        return match.group(0), match.start(), match.end()

    return None


def make_cloze(term: str, sentence: str) -> tuple[str, str]:
    target = find_cloze_target(term, sentence)
    if not target:
        return sentence, term

    answer, start, end = target
    return f"{sentence[:start]}____{sentence[end:]}", answer


def assign_routine_chunks(words: list[dict]) -> None:
    chunk_size = max(1, math.ceil(len(words) / ROUTINE_CHUNK_COUNT))
    for index, word in enumerate(words):
        chunk = (index // chunk_size) + 1
        word["chunk"] = min(ROUTINE_CHUNK_COUNT, chunk)


def build_words() -> list[dict]:
    workbook = load_workbook(WORKBOOK_PATH, read_only=True, data_only=True)
    sheet = workbook[FREQUENT_SHEET]

    pronunciation_lookup = load_pronunciations()
    meaning_overrides = load_meaning_overrides()
    example_overrides = load_example_overrides()

    words: list[dict] = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        rank = row[0] if len(row) > 0 else None
        word = clean(row[2] if len(row) > 2 else None)
        if not rank or not word:
            continue

        word_id = f"F{int(rank):04d}"
        override = get_example_override(example_overrides, word_id, word)
        word = override.get("word", word)

        sheet_meaning = clean(row[3] if len(row) > 3 else None)
        meaning = meaning_overrides.get(normalize_key(word)) or sheet_meaning

        example_cell = row[4] if len(row) > 4 else None
        example_raw = "" if example_cell is None else str(example_cell)
        sheet_example_en, _, sheet_example_ko = example_raw.partition("\n")
        example_en = override.get("exampleEn") or clean(sheet_example_en)
        example_ko = override.get("exampleKo") or clean(sheet_example_ko)
        if example_en:
            cloze, cloze_answer = make_cloze(word, example_en)
        else:
            cloze, cloze_answer = "", ""

        words.append(
            {
                "id": word_id,
                "source": "frequent",
                "sourceLabel": "빈출",
                "rank": int(rank),
                "chunk": 0,
                "word": word,
                "meaning": meaning,
                "pronunciation": pronunciation_lookup.get(normalize_key(word), ""),
                "group": clean(row[1] if len(row) > 1 else None),
                "exampleEn": example_en,
                "exampleKo": example_ko,
                "clozeExample": cloze,
                "clozeAnswer": cloze_answer,
                "expression": "",
                "duplicateFileCount": (row[5] if len(row) > 5 else 0) or 0,
                "appearanceCount": (row[6] if len(row) > 6 else 0) or 0,
            }
        )

    assign_routine_chunks(words)
    return words


def main() -> None:
    words = build_words()
    chunk_counts = {
        str(chunk): sum(1 for word in words if word["chunk"] == chunk)
        for chunk in range(1, ROUTINE_CHUNK_COUNT + 1)
    }
    meaning_coverage = sum(1 for word in words if word["meaning"])
    pronunciation_coverage = sum(1 for word in words if word["pronunciation"])

    meta = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceFile": "src/TEPS_Voca(통합).xlsx",
        "sourceFiles": ["src/TEPS_Voca(통합).xlsx"],
        "total": len(words),
        "counts": {
            "frequent": len(words),
        },
        "coverage": {
            "meaning": meaning_coverage,
            "pronunciation": pronunciation_coverage,
        },
        "chunkCounts": chunk_counts,
        "chunkRule": {
            "routine": f"split the frequent-word list evenly across a {ROUTINE_CHUNK_COUNT}-day cycle",
        },
    }

    js = (
        "// Generated from src/TEPS_Voca(통합).xlsx by src/generate_words_data.py\n"
        f"window.TEPS_META = {json.dumps(meta, ensure_ascii=False, indent=2)};\n"
        f"window.TEPS_WORDS = {json.dumps(words, ensure_ascii=False, indent=2)};\n"
    )
    OUTPUT_PATH.write_text(js, encoding="utf-8")
    print(f"Wrote {len(words)} words to {OUTPUT_PATH}")
    print(f"Meaning coverage: {meaning_coverage}/{len(words)}")
    print(f"Pronunciation coverage: {pronunciation_coverage}/{len(words)}")


if __name__ == "__main__":
    main()
