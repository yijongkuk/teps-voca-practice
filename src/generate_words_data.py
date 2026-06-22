from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
WORKBOOK_PATH = ROOT / "TEPS_VOCA.xlsx"
FREQUENT_WORKBOOK_PATH = ROOT / "TEPS_VOCA(O).xlsx"
PRONUNCIATION_PATH = ROOT / "pronunciations.json"
MEANING_OVERRIDE_PATH = ROOT / "meaning_overrides.json"
EXAMPLE_OVERRIDE_PATH = ROOT / "example_overrides.json"
OUTPUT_PATH = ROOT / "words-data.js"

VOCAB_SHEET = "어휘단어장(통합)"
READING_SHEET = "독해단어장(통합)"
FREQUENT_SHEET = "빈출단어"
ROUTINE_CHUNK_COUNT = 7


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


def split_example(value) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", ""

    english_lines: list[str] = []
    korean_lines: list[str] = []
    seen_korean = False

    for line in lines:
        if re.search(r"[가-힣]", line):
            seen_korean = True
            korean_lines.append(line)
        elif seen_korean:
            korean_lines.append(line)
        else:
            english_lines.append(line)

    english = " ".join(english_lines).strip() or lines[0]
    korean = " ".join(korean_lines).strip()
    return english, korean


def find_cloze_target(term: str, sentence: str) -> tuple[str, int, int] | None:
    if not term or not sentence:
        return None

    exact_pattern = re.escape(term).replace(r"\ ", r"\s+")
    exact = re.search(exact_pattern, sentence, flags=re.IGNORECASE)
    if exact:
        return exact.group(0), exact.start(), exact.end()

    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", term)
    tokens = sorted(set(tokens), key=len, reverse=True)
    for token in tokens:
        match = re.search(rf"\b{re.escape(token)}\b", sentence, flags=re.IGNORECASE)
        if match:
            return match.group(0), match.start(), match.end()

    return None


def make_cloze(term: str, sentence: str) -> tuple[str, str]:
    target = find_cloze_target(term, sentence)
    if not target:
        return sentence, term

    answer, start, end = target
    return f"{sentence[:start]}____{sentence[end:]}", answer


def split_lines(value) -> list[str]:
    return [clean(line) for line in str(value or "").splitlines() if clean(line)]


def pair_related_words(words_value, meanings_value) -> str:
    related_words = split_lines(words_value)
    related_meanings = split_lines(meanings_value)
    if not related_words:
        return ""

    if len(related_words) == 1 and len(related_meanings) > 1:
        return f"연관: {related_words[0]}: {' / '.join(related_meanings)}"

    pairs: list[str] = []
    for index, related_word in enumerate(related_words):
        related_meaning = related_meanings[index] if index < len(related_meanings) else ""
        pairs.append(f"{related_word}: {related_meaning}" if related_meaning else related_word)
    if len(related_meanings) > len(related_words):
        pairs.append(" / ".join(related_meanings[len(related_words) :]))
    return "연관: " + "; ".join(pairs)


def build_expression(related_words, related_meanings, point) -> str:
    parts = [part for part in [pair_related_words(related_words, related_meanings), clean(point)] if part]
    return " | ".join(parts)


def extract_point_meaning(word: str, point) -> str:
    if not word or point is None:
        return ""

    for line in split_lines(point):
        match = re.match(rf"(?i)^{re.escape(word)}\s*:\s*(.+)$", line)
        if not match:
            continue

        meaning = match.group(1).strip()
        next_term = re.search(r"\s+[A-Za-z][A-Za-z\s\-\(\)]{0,35}\s*:", meaning)
        if next_term:
            meaning = meaning[: next_term.start()].strip()
        meaning = re.sub(r"\s+:\s*$", "", meaning).strip(" ,;/")
        if re.search(r"[가-힣]", meaning):
            return meaning

    return ""


def build_frequent_words(
    meaning_lookup: dict[str, str],
    pronunciation_lookup: dict[str, str],
    meaning_overrides: dict[str, str],
    example_overrides: dict[str, dict[str, str]],
) -> list[dict]:
    if not FREQUENT_WORKBOOK_PATH.exists():
        return []

    workbook = load_workbook(FREQUENT_WORKBOOK_PATH, read_only=True, data_only=True)
    sheet = workbook[FREQUENT_SHEET]
    rows: list[dict] = []
    current_day = ""

    for row in sheet.iter_rows(min_row=2, values_only=True):
        day_marker = clean(row[0] if len(row) > 0 else None)
        if re.fullmatch(r"DAY\d+", day_marker, flags=re.IGNORECASE):
            current_day = day_marker.upper()

        word = clean(row[2] if len(row) > 2 else None)
        if not word:
            continue

        rank = len(rows) + 1
        word_id = f"F{rank:04d}"
        override = get_example_override(example_overrides, word_id, word)
        word = override.get("word", word)

        meaning = clean(row[3] if len(row) > 3 else None)
        meaning_source = "file" if meaning else ""
        if not meaning:
            meaning = meaning_lookup.get(normalize_key(word), "")
            meaning_source = "existing" if meaning else ""
        if not meaning:
            meaning = extract_point_meaning(word, row[7] if len(row) > 7 else None)
            meaning_source = "point" if meaning else ""
        if meaning_overrides.get(normalize_key(word)):
            meaning = meaning_overrides[normalize_key(word)]
            meaning_source = "override"

        example_en, example_ko = split_example(row[4] if len(row) > 4 else None)
        example_en = override.get("exampleEn", example_en)
        example_ko = override.get("exampleKo", example_ko)
        cloze, cloze_answer = make_cloze(word, example_en)

        rows.append(
            {
                "id": word_id,
                "source": "frequent",
                "sourceLabel": "빈출",
                "rank": rank,
                "chunk": 0,
                "word": word,
                "meaning": meaning,
                "pronunciation": pronunciation_lookup.get(normalize_key(word), ""),
                "group": current_day,
                "exampleEn": example_en,
                "exampleKo": example_ko,
                "clozeExample": cloze,
                "clozeAnswer": cloze_answer,
                "expression": build_expression(
                    row[5] if len(row) > 5 else None,
                    row[6] if len(row) > 6 else None,
                    row[7] if len(row) > 7 else None,
                ),
                "duplicateFileCount": 0,
                "appearanceCount": 1,
                "originalNo": row[1] if len(row) > 1 else "",
                "meaningSource": meaning_source,
            }
        )

    return rows


def assign_routine_chunks(words: list[dict]) -> None:
    chunk_size = max(1, math.ceil(len(words) / ROUTINE_CHUNK_COUNT))
    for index, word in enumerate(words):
        chunk = (index // chunk_size) + 1
        word["chunk"] = min(ROUTINE_CHUNK_COUNT, chunk)


def build_words() -> list[dict]:
    workbook = load_workbook(WORKBOOK_PATH, read_only=True, data_only=True)
    words: list[dict] = []
    meaning_lookup: dict[str, str] = {}
    pronunciation_lookup = load_pronunciations()
    meaning_overrides = load_meaning_overrides()
    example_overrides = load_example_overrides()

    vocab_sheet = workbook[VOCAB_SHEET]
    for row in vocab_sheet.iter_rows(min_row=2, values_only=True):
        rank = row[0]
        word = clean(row[2])
        if not rank or not word:
            continue

        word_id = f"V{int(rank):04d}"
        override = get_example_override(example_overrides, word_id, word)
        word = override.get("word", word)
        example_en, example_ko = split_example(row[4])
        example_en = override.get("exampleEn", example_en)
        example_ko = override.get("exampleKo", example_ko)
        cloze, cloze_answer = make_cloze(word, example_en)
        words.append(
            {
                "id": word_id,
                "source": "vocab",
                "sourceLabel": "어휘",
                "rank": int(rank),
                "chunk": 0,
                "word": word,
                "meaning": meaning_overrides.get(normalize_key(word), clean(row[3])),
                "pronunciation": pronunciation_lookup.get(normalize_key(word), ""),
                "group": clean(row[1]),
                "exampleEn": example_en,
                "exampleKo": example_ko,
                "clozeExample": cloze,
                "clozeAnswer": cloze_answer,
                "expression": "",
                "duplicateFileCount": row[5] or 0,
                "appearanceCount": row[6] or 0,
            }
        )
        meaning_lookup.setdefault(normalize_key(word), clean(row[3]))

    reading_sheet = workbook[READING_SHEET]
    for row in reading_sheet.iter_rows(min_row=2, values_only=True):
        rank = row[1]
        word = clean(row[2])
        if not rank or not word:
            continue

        word_id = f"R{int(rank):04d}"
        override = get_example_override(example_overrides, word_id, word)
        word = override.get("word", word)
        example_en, example_ko = split_example(row[4])
        example_en = override.get("exampleEn", example_en)
        example_ko = override.get("exampleKo", example_ko)
        cloze, cloze_answer = make_cloze(word, example_en)

        words.append(
            {
                "id": word_id,
                "source": "reading",
                "sourceLabel": "독해",
                "rank": int(rank),
                "chunk": 0,
                "word": word,
                "meaning": meaning_overrides.get(normalize_key(word), clean(row[3])),
                "pronunciation": pronunciation_lookup.get(normalize_key(word), ""),
                "group": "",
                "exampleEn": example_en,
                "exampleKo": example_ko,
                "clozeExample": cloze,
                "clozeAnswer": cloze_answer,
                "expression": clean(row[5]),
                "duplicateFileCount": 0,
                "appearanceCount": row[6] or 0,
            }
        )
        meaning_lookup.setdefault(normalize_key(word), clean(row[3]))

    words.extend(
        build_frequent_words(
            meaning_lookup,
            pronunciation_lookup,
            meaning_overrides,
            example_overrides,
        )
    )
    assign_routine_chunks(words)
    return words


def main() -> None:
    words = build_words()
    chunk_counts = {
        str(chunk): sum(1 for word in words if word["chunk"] == chunk)
        for chunk in range(1, ROUTINE_CHUNK_COUNT + 1)
    }
    meta = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceFile": "src/TEPS_VOCA.xlsx + src/TEPS_VOCA(O).xlsx",
        "sourceFiles": ["src/TEPS_VOCA.xlsx", "src/TEPS_VOCA(O).xlsx"],
        "total": len(words),
        "counts": {
            "vocab": sum(1 for word in words if word["source"] == "vocab"),
            "reading": sum(1 for word in words if word["source"] == "reading"),
            "frequent": sum(1 for word in words if word["source"] == "frequent"),
        },
        "chunkCounts": chunk_counts,
        "chunkRule": {
            "routine": "split all sources evenly across a 7-day cycle",
        },
    }

    js = (
        "// Generated from src/TEPS_VOCA.xlsx and src/TEPS_VOCA(O).xlsx by src/generate_words_data.py\n"
        f"window.TEPS_META = {json.dumps(meta, ensure_ascii=False, indent=2)};\n"
        f"window.TEPS_WORDS = {json.dumps(words, ensure_ascii=False, indent=2)};\n"
    )
    OUTPUT_PATH.write_text(js, encoding="utf-8")
    print(f"Wrote {len(words)} words to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
