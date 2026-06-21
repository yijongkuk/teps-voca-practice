from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parent
WORKBOOK_PATH = ROOT / "TEPS_VOCA.xlsx"
OUTPUT_PATH = ROOT / "words-data.js"

VOCAB_SHEET = "어휘단어장(통합)"
READING_SHEET = "독해단어장(통합)"
VOCAB_CHUNK_SIZE = 307
READING_CHUNK_LIMITS = [195, 390, 586, 781, 976]


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


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


def reading_chunk(rank: int) -> int:
    for index, limit in enumerate(READING_CHUNK_LIMITS, start=1):
        if rank <= limit:
            return index
    return 5


def build_words() -> list[dict]:
    workbook = load_workbook(WORKBOOK_PATH, read_only=True, data_only=True)
    words: list[dict] = []

    vocab_sheet = workbook[VOCAB_SHEET]
    for row in vocab_sheet.iter_rows(min_row=2, values_only=True):
        rank = row[0]
        word = clean(row[2])
        if not rank or not word:
            continue

        example_en, example_ko = split_example(row[4])
        cloze, cloze_answer = make_cloze(word, example_en)
        chunk = ((int(rank) - 1) // VOCAB_CHUNK_SIZE) + 1

        words.append(
            {
                "id": f"V{int(rank):04d}",
                "source": "vocab",
                "sourceLabel": "어휘",
                "rank": int(rank),
                "chunk": chunk,
                "word": word,
                "meaning": clean(row[3]),
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

    reading_sheet = workbook[READING_SHEET]
    for row in reading_sheet.iter_rows(min_row=2, values_only=True):
        rank = row[1]
        word = clean(row[2])
        if not rank or not word:
            continue

        example_en, example_ko = split_example(row[4])
        cloze, cloze_answer = make_cloze(word, example_en)

        words.append(
            {
                "id": f"R{int(rank):04d}",
                "source": "reading",
                "sourceLabel": "독해",
                "rank": int(rank),
                "chunk": reading_chunk(int(rank)),
                "word": word,
                "meaning": clean(row[3]),
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

    return words


def main() -> None:
    words = build_words()
    chunk_counts = {
        str(chunk): sum(1 for word in words if word["chunk"] == chunk)
        for chunk in range(1, 6)
    }
    meta = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceFile": "src/TEPS_VOCA.xlsx",
        "total": len(words),
        "counts": {
            "vocab": sum(1 for word in words if word["source"] == "vocab"),
            "reading": sum(1 for word in words if word["source"] == "reading"),
        },
        "chunkCounts": chunk_counts,
        "chunkRule": {
            "vocab": "307 words per chunk",
            "reading": "195, 195, 196, 195, 195 words",
        },
    }

    js = (
        "// Generated from src/TEPS_VOCA.xlsx by src/generate_words_data.py\n"
        f"window.TEPS_META = {json.dumps(meta, ensure_ascii=False, indent=2)};\n"
        f"window.TEPS_WORDS = {json.dumps(words, ensure_ascii=False, indent=2)};\n"
    )
    OUTPUT_PATH.write_text(js, encoding="utf-8")
    print(f"Wrote {len(words)} words to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
