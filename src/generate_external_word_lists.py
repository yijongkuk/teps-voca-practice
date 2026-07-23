from __future__ import annotations

import argparse
import json
import re
import tempfile
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = ROOT / "external_word_lists.json"

OXFORD_URL = (
    "https://www.oxfordlearnersdictionaries.com/external/pdf/wordlists/"
    "oxford-3000-5000/American_Oxford_5000.pdf"
)
AWL_URL = "https://www.eapfoundation.com/vocab/academic/awllists/"

POS_PATTERN = re.compile(
    r"\b(?:(?:modal|auxiliary) v|adj|adv|n|v|prep|conj|det|exclam|pron)\.|\bnumber\b"
)
LEVEL_PATTERN = re.compile(r"\b(?:B1|B2|C1)\b")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def normalize_oxford_headword(value: str) -> str:
    word = re.sub(r"\s*\([^)]*\)", "", clean(value))
    word = re.sub(r"(?<=[A-Za-z])\s*\d+$", "", word)
    return clean(word)


def fold_pdf_lines(lines: list[str]) -> list[str]:
    folded: list[str] = []
    index = 0
    while index < len(lines):
        line = clean(lines[index])
        next_line = clean(lines[index + 1]) if index + 1 < len(lines) else ""
        next_pos = POS_PATTERN.search(next_line)

        # A few entries are split across PDF text lines (for example,
        # "sacred" + "adj. C1" and "recount" + "1 v. C1").
        if (
            line
            and not POS_PATTERN.search(line)
            and next_pos
            and not re.search(r"[A-Za-z]", next_line[: next_pos.start()])
        ):
            folded.append(f"{line} {next_line}")
            index += 2
            continue

        # "scratch ... B2" is extracted as "scratch ... B" + "2".
        if re.search(r"\bB$", line) and next_line == "2":
            folded.append(f"{line}2")
            index += 2
            continue

        folded.append(line)
        index += 1
    return folded


def parse_oxford_pdf(path: Path) -> tuple[list[dict], int]:
    merged: OrderedDict[str, dict] = OrderedDict()
    source_entry_count = 0
    for page in PdfReader(path).pages:
        page_lines = fold_pdf_lines((page.extract_text() or "").splitlines())
        for line in page_lines:
            first_pos = POS_PATTERN.search(line)
            if not first_pos:
                continue

            levels = LEVEL_PATTERN.findall(line[first_pos.start() :])
            if not levels:
                continue

            word = normalize_oxford_headword(line[: first_pos.start()])
            if not word or not re.search(r"[A-Za-z]", word):
                continue

            source_entry_count += 1
            key = word.casefold()
            entry = merged.setdefault(
                key,
                {
                    "word": word,
                    "levels": [],
                    "partsOfSpeech": [],
                },
            )
            for level in levels:
                if level not in entry["levels"]:
                    entry["levels"].append(level)
            for part_of_speech in POS_PATTERN.findall(line[first_pos.start() :]):
                normalized_pos = part_of_speech.removesuffix(".")
                if normalized_pos not in entry["partsOfSpeech"]:
                    entry["partsOfSpeech"].append(normalized_pos)

    return list(merged.values()), source_entry_count


def parse_awl_html(path: Path) -> list[dict]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()

    for row in soup.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 3:
            continue
        headword_node = cells[0].find("b")
        sublist_text = clean(cells[1].get_text(" ", strip=True))
        if not headword_node or not re.fullmatch(r"(?:10|[1-9])", sublist_text):
            continue

        word = clean(headword_node.get_text(" ", strip=True))
        key = word.casefold()
        if not word or key in seen:
            continue
        seen.add(key)

        related_text = clean(cells[2].get_text(" ", strip=True))
        related_forms = [
            form
            for form in (clean(part) for part in related_text.split(","))
            if form and form.casefold() != key
        ]
        entries.append(
            {
                "word": word,
                "sublist": int(sublist_text),
                "relatedForms": related_forms,
            }
        )

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build normalized Oxford 5000 and AWL word-list data."
    )
    parser.add_argument("--oxford-pdf", type=Path)
    parser.add_argument("--awl-html", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="teps-word-lists-") as temp_dir:
        temp_root = Path(temp_dir)
        oxford_path = args.oxford_pdf or temp_root / "American_Oxford_5000.pdf"
        awl_path = args.awl_html or temp_root / "awl.html"
        if not args.oxford_pdf:
            download(OXFORD_URL, oxford_path)
        if not args.awl_html:
            download(AWL_URL, awl_path)

        oxford_entries, oxford_source_entry_count = parse_oxford_pdf(oxford_path)
        awl_entries = parse_awl_html(awl_path)

    if oxford_source_entry_count != 2000:
        raise ValueError(
            "Expected 2,000 Oxford source entries, extracted "
            f"{oxford_source_entry_count:,}."
        )
    if len(oxford_entries) != 1997:
        raise ValueError(
            f"Expected 1,997 unique Oxford headwords, extracted {len(oxford_entries):,}."
        )
    if len(awl_entries) != 570:
        raise ValueError(f"Expected 570 AWL headwords, extracted {len(awl_entries):,}.")

    payload = {
        "_meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "oxford": {
                "label": "Oxford 5000",
                "description": "Oxford 3000에 추가되는 B2-C1 2,000개 단어",
                "source": OXFORD_URL,
                "count": len(oxford_entries),
                "sourceEntryCount": oxford_source_entry_count,
            },
            "awl": {
                "label": "AWL 570",
                "description": "Academic Word List 570개 표제어",
                "source": AWL_URL,
                "count": len(awl_entries),
            },
        },
        "oxford5000": oxford_entries,
        "awl": awl_entries,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(oxford_entries):,} unique Oxford headwords "
        f"from {oxford_source_entry_count:,} source entries to {args.output}"
    )
    print(f"Wrote {len(awl_entries):,} AWL entries to {args.output}")


if __name__ == "__main__":
    main()
