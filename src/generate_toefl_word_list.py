"""Build a normalized word list from the scanned Hackers TOEFL Vocabulary book.

The PDF is a scan with an OCR text layer, so the raw text is noisy. The parser
leans on the layout instead of the characters: headwords are the only large bold
run in the left column, pronunciations are the only Times run next to them, and
the Korean translation block is the trailing run of garbled rows at the bottom of
every page. Damaged headwords and synonyms are repaired against a lexicon built
from the book's own index pages plus every example sentence in the book.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parent
DEFAULT_PDF_PATH = ROOT / "03 TOEFLVOCA.pdf"
DEFAULT_OUTPUT_PATH = ROOT / "toefl_word_list.json"

DAY_COUNT = 60
# Every three days occupy a fixed 20-page block: 3 x 6 entry pages + a 2-page
# review test. Day 60 ends on page 397 and the book index starts on page 399.
PAGES_PER_DAY = 6
BLOCK_PAGES = 20
CONTENT_PAGE_COUNT = DAY_COUNT // 3 * BLOCK_PAGES
INDEX_FIRST_PAGE = 399

POS_WORDS = {"adj", "adv", "n", "v", "prep", "conj", "pron", "phr"}
POS_LABELS = {
    "adj": "adj.",
    "adv": "adv.",
    "n": "n.",
    "v": "v.",
    "prep": "prep.",
    "conj": "conj.",
    "pron": "pron.",
    "phr": "phr.",
}

ENGLISH_TOKEN = re.compile(r"^[(\"'\[]?[A-Za-z][A-Za-z'\-]*[.,;:!?)\"'\]]*$")
NUMBER_TOKEN = re.compile(r"^[\d.,%$]+$")
SENSE_INDEX = re.compile(r"^(\d)\.$")
LETTERS_ONLY = re.compile(r"[^a-z]")

# Words the book uses inside example sentences and synonym lists that the index
# pages do not carry on their own.
EXTRA_LEXICON = {
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "from",
    "as", "is", "are", "was", "were", "be", "been", "being", "and", "or", "but",
    "not", "no", "it", "its", "he", "she", "his", "her", "they", "them", "their",
    "this", "that", "these", "those", "there", "here", "who", "whom", "which",
    "what", "when", "where", "why", "how", "than", "then", "into", "onto",
    "over", "under", "about", "after", "before", "between", "through", "during",
    "such", "some", "any", "all", "both", "each", "more", "most", "many", "much",
    "have", "has", "had", "do", "does", "did", "can", "could", "will", "would",
    "shall", "should", "may", "might", "must", "one", "two", "three", "first",
    "second", "third", "up", "down", "out", "off", "so", "if", "because", "while",
    "you", "your", "we", "our", "us", "i", "me", "my", "him", "himself",
    "herself", "itself", "themselves", "other", "others", "another", "same",
    "own", "very", "too", "also", "only", "just", "even", "still", "yet",
}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_key(value: str) -> str:
    return clean(value).lower()


def letters(value: str) -> str:
    return LETTERS_ONLY.sub("", value.lower())


def norm_pos(text: str) -> str:
    stripped = re.sub(r"[^A-Za-z]", "", text).lower()
    return stripped if stripped in POS_WORDS else ""


def median(values, fallback=None):
    return statistics.median(values) if values else fallback


def day_page_range(day: int) -> range:
    block, offset = divmod(day - 1, 3)
    start = block * BLOCK_PAGES + offset * PAGES_PER_DAY
    return range(start, start + PAGES_PER_DAY)


def is_english_token(text: str) -> bool:
    return bool(ENGLISH_TOKEN.match(text) or NUMBER_TOKEN.match(text))


def garbage_ratio(row: list[dict]) -> float:
    if not row:
        return 0.0
    bad = sum(1 for w in row if not is_english_token(w["text"]))
    return bad / len(row)


def read_rows(page, tolerance: float = 4.5) -> list[list[dict]]:
    words = sorted(
        page.extract_words(extra_attrs=["fontname", "size"]),
        key=lambda w: (w["top"], w["x0"]),
    )
    rows: list[list[dict]] = []
    for word in words:
        if rows and abs(rows[-1][-1]["top"] - word["top"]) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def is_headword_token(word: dict) -> bool:
    """Headwords are the only oversized run in the left column.

    The scan's OCR assigns fonts inconsistently, so size plus "at least two
    letters" separates headwords from entry numbers (one or two glyphs),
    pronunciations (~8pt Times) and antonyms (~9pt).
    """
    large = word["size"] >= 10.0 or ("Bold" in word["fontname"] and word["size"] >= 9.5)
    return large and bool(re.search(r"[A-Za-z]{2}", word["text"]))


def split_page(page_index: int, rows: list[list[dict]], height: float) -> dict | None:
    """Split one entry page into its body rows and its Korean translation block."""
    def_left = median(
        [
            w["x0"]
            for row in rows
            for w in row
            if 150 <= w["x0"] <= 260 and norm_pos(w["text"])
        ]
    )
    if def_left is None:
        return None

    keep = [row for row in rows if 0.10 * height < row[0]["top"] < height - 58]

    head_column = def_left - 62
    korean_lo, korean_hi = def_left - 56, def_left - 30
    gloss_start = len(keep)
    for index in range(len(keep) - 1, -1, -1):
        row = keep[index]
        x0 = row[0]["x0"]
        placed = x0 < head_column or korean_lo <= x0 <= korean_hi
        if row[0]["top"] < 0.55 * height or not placed or garbage_ratio(row) < 0.3:
            break
        gloss_start = index

    body, gloss = keep[:gloss_start], keep[gloss_start:]

    # The daily quiz closes the entry list on the last page of a day.
    for index, row in enumerate(body):
        if any(
            "Bold" in w["fontname"]
            and w["size"] > 20
            and re.fullmatch(r"[OQ]ui[zx]", w["text"])
            for w in row
        ):
            body = body[:index]
            break

    head_candidates = [
        [w for w in row if w["x0"] < def_left - 25 and is_headword_token(w)]
        for row in body
    ]
    head_left = median(
        [row[0]["x0"] for row in head_candidates if row],
        def_left - 99,
    )
    return {
        "page": page_index,
        "defLeft": def_left,
        "headLeft": head_left,
        "body": body,
        "gloss": gloss,
    }


def split_row(row: list[dict], part: dict) -> dict:
    def_left, head_left = part["defLeft"], part["headLeft"]
    left = [w for w in row if w["x0"] < def_left - 25]
    right = [w for w in row if w["x0"] >= def_left - 25]
    bold = [w for w in left if is_headword_token(w) and w["x0"] >= head_left - 6]
    pronunciation = [
        w
        for w in left
        if w not in bold and "Times" in w["fontname"] and w["x0"] >= head_left - 4
    ]
    antonyms = [
        w
        for w in left
        if w not in bold
        and w not in pronunciation
        and w["x0"] >= head_left - 4
        and 7.8 <= w["size"] < 10.0
        and re.fullmatch(r"[A-Za-z][A-Za-z'\-]{2,}", w["text"])
    ]
    return {
        "right": right,
        "bold": bold,
        "pronunciation": pronunciation,
        "antonyms": antonyms,
    }


def gloss_terms(part: dict) -> list[str]:
    limit = part["defLeft"] - 62
    terms = []
    for row in part["gloss"]:
        tokens = [
            w["text"]
            for w in row
            if w["x0"] < limit and re.search(r"[A-Za-z]", w["text"])
        ]
        if tokens:
            terms.append(clean(" ".join(tokens)).strip(" .,;:"))
    return [term for term in terms if term]


def parse_day(pages: dict[int, dict], day: int) -> tuple[list[str], list[dict]]:
    parts = [pages[index] for index in day_page_range(day) if pages.get(index)]

    heads: list[str] = []
    for part in parts:
        for term in gloss_terms(part):
            if not heads or heads[-1].lower() != term.lower():
                heads.append(term)

    entries: list[dict] = []
    current: dict | None = None
    for part in parts:
        for index, row in enumerate(part["body"]):
            cells = split_row(row, part)
            follower = (
                split_row(part["body"][index + 1], part)
                if index + 1 < len(part["body"])
                else None
            )
            right = cells["right"]
            pos = norm_pos(right[0]["text"]) if right else ""
            if pos:
                sense_index = next(
                    (
                        int(match.group(1))
                        for word in right[1:3]
                        for match in [SENSE_INDEX.match(word["text"])]
                        if match
                    ),
                    None,
                )
                starts = bool(cells["bold"]) or bool(
                    cells["pronunciation"] or (follower and follower["pronunciation"])
                )
                if not starts and current and current["senses"] and sense_index in (None, 1):
                    starts = True
                if starts or current is None:
                    current = {
                        "page": part["page"],
                        "bold": clean(" ".join(w["text"] for w in cells["bold"])),
                        "senses": [],
                        "antonyms": [],
                    }
                    entries.append(current)
                current["senses"].append(
                    {
                        "pos": pos,
                        "index": sense_index,
                        "synonyms": [
                            {"x0": w["x0"], "x1": w["x1"], "text": w["text"]}
                            for w in right[1:]
                        ],
                        "example": [],
                    }
                )
            elif current and current["senses"] and right:
                current["senses"][-1]["example"].extend(w["text"] for w in right)
            if current and cells["antonyms"]:
                current["antonyms"].append(
                    " ".join(w["text"] for w in cells["antonyms"])
                )
    return heads, entries


def parse_index_lexicon(pages_text: list[str]) -> set[str]:
    """Collect the vocabulary the book itself indexes on its final pages."""
    words: set[str] = set()
    for text in pages_text:
        for line in text.splitlines():
            for token in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", line):
                words.add(token.lower())
    return words


def build_lexicon(index_words: set[str], entries: list[dict], cmudict: Path | None) -> set[str]:
    lexicon = set(EXTRA_LEXICON) | index_words
    if cmudict and cmudict.exists():
        for line in cmudict.read_text(encoding="utf-8", errors="ignore").splitlines():
            token = re.sub(r"\(\d+\)$", "", line.split(" ", 1)[0]).lower()
            if re.fullmatch(r"[a-z][a-z'\-]*", token):
                lexicon.add(token)
    for entry in entries:
        for sense in entry["senses"]:
            for token in sense["example"]:
                stripped = token.strip(".,;:!?()\"'").lower()
                if re.fullmatch(r"[a-z][a-z'\-]{2,}", stripped):
                    lexicon.add(stripped)
    return lexicon


def inflection_forms(word: str) -> list[str]:
    forms = [word]
    for suffix, replacement in (
        ("ies", "y"),
        ("ied", "y"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)] + replacement
            forms.append(base)
            if suffix in ("ing", "ed"):
                forms.append(base + "e")
    return forms


def repair_term(raw: str, lexicon: set[str], hints: list[str]) -> tuple[str, str]:
    """Return (repaired term, status) for one OCR-damaged term."""
    term = clean(raw)
    term = re.sub(r"[*]+", "", term)
    term = re.sub(r"^[^A-Za-z]+", "", term)
    term = re.sub(r"[^A-Za-z)\]]+$", "", term)
    term = clean(term)
    if not term:
        return "", "empty"

    tokens = term.split(" ")
    if all(token.lower().strip("().,'-") in lexicon for token in tokens if token):
        return term.lower(), "clean"

    # "su rdinate" and "re roduce" lose characters mid-word: try the collapsed
    # spelling and then the closest word the surrounding text actually uses.
    collapsed = letters(term)
    if collapsed in lexicon:
        return collapsed, "collapsed"

    candidates = {letters(hint): hint.lower() for hint in hints if letters(hint)}
    for hint in list(candidates):
        for form in inflection_forms(hint):
            if form in lexicon:
                candidates.setdefault(form, form)

    best, best_score = "", 0.0
    for candidate_key, candidate in candidates.items():
        score = difflib.SequenceMatcher(None, collapsed, candidate_key).ratio()
        if collapsed and candidate_key.startswith(collapsed[:2]):
            score += 0.05
        if score > best_score:
            best, best_score = candidate, score
    if best and best_score >= 0.7:
        return best, "repaired"

    matches = difflib.get_close_matches(collapsed, lexicon, n=1, cutoff=0.82)
    if matches:
        return matches[0], "repaired"
    return term.lower(), "unresolved"


def resolve_headword(
    bold: str,
    gloss: str,
    lexicon: set[str],
    hints: list[str],
    pool: set[str],
) -> tuple[str, str]:
    """Pick the headword the page, the translation block and the example agree on."""
    candidates: list[tuple[str, str]] = []
    if clean(bold):
        candidates.append(repair_term(bold, lexicon, hints))
        candidates.append(repair_term(letters(bold), lexicon, hints))
    if clean(gloss):
        word, status = repair_term(gloss, lexicon, hints)
        candidates.append((word, "fromGloss" if status in ("clean", "collapsed") else status))
    candidates = [(word, status) for word, status in candidates if word]
    if not candidates:
        return "", "empty"

    def rank(item: tuple[str, str]) -> tuple:
        word, status = item
        order = ["clean", "collapsed", "fromGloss", "repaired", "unresolved"]
        return (
            appears_in_example(word, pool),
            all(part in lexicon for part in word.split(" ")),
            -order.index(status) if status in order else -9,
        )

    best = max(candidates, key=rank)
    if not appears_in_example(best[0], pool):
        # Neither the page nor the translation block survived OCR: fall back to
        # the closest content word the example sentence itself uses.
        target = letters(bold or gloss)
        scored = [
            (difflib.SequenceMatcher(None, target, item).ratio(), item)
            for item in pool
            if len(item) >= 4 and item in lexicon and item not in EXTRA_LEXICON
        ]
        if scored:
            score, candidate = max(scored)
            if score >= 0.6:
                return candidate, "repaired"
    return best


def align_gloss(entry_words: list[str], heads: list[str]) -> list[str]:
    """Line the per-page translation headwords up with the parsed entries.

    Both lists are in reading order but the translation block sometimes drops or
    merges a line, so a plain zip would drift. A small Needleman-Wunsch pass over
    the two sequences keeps the surviving pairs anchored.
    """
    rows, columns = len(entry_words), len(heads)
    gap = -0.35
    score = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        score[i][0] = score[i - 1][0] + gap
    for j in range(1, columns + 1):
        score[0][j] = score[0][j - 1] + gap
    for i in range(1, rows + 1):
        left = letters(entry_words[i - 1])
        for j in range(1, columns + 1):
            right = letters(heads[j - 1])
            similarity = (
                difflib.SequenceMatcher(None, left, right).ratio() if left and right else 0.3
            )
            score[i][j] = max(
                score[i - 1][j - 1] + similarity - 0.45,
                score[i - 1][j] + gap,
                score[i][j - 1] + gap,
            )

    matched: list[str] = [""] * rows
    i, j = rows, columns
    while i > 0 and j > 0:
        left, right = letters(entry_words[i - 1]), letters(heads[j - 1])
        similarity = (
            difflib.SequenceMatcher(None, left, right).ratio() if left and right else 0.3
        )
        if abs(score[i][j] - (score[i - 1][j - 1] + similarity - 0.45)) < 1e-9:
            matched[i - 1] = heads[j - 1]
            i, j = i - 1, j - 1
        elif abs(score[i][j] - (score[i - 1][j] + gap)) < 1e-9:
            i -= 1
        else:
            j -= 1
    return matched


DIGIT_LOOKALIKES = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "6": "b"})


def resolve_word(candidate: str, lexicon: set[str]) -> str:
    if candidate in lexicon:
        return candidate
    relettered = candidate.translate(DIGIT_LOOKALIKES)
    if relettered in lexicon:
        return relettered
    matches = difflib.get_close_matches(relettered, lexicon, n=1, cutoff=0.8)
    return matches[0] if matches else ""


def split_synonym_chunks(tokens: list[dict]) -> list[str]:
    """Group synonym tokens into entries.

    Commas separate most synonyms, but the book also prints one or two extra
    synonyms in a lighter style further to the right, separated only by a wide
    gap. Splitting on that gap keeps them from gluing onto the previous item.
    """
    chunks: list[list[str]] = []
    previous_x1: float | None = None
    for token in tokens:
        text = token["text"]
        if SENSE_INDEX.match(text):
            continue
        if not chunks or (previous_x1 is not None and token["x0"] - previous_x1 > 8):
            chunks.append([])
        chunks[-1].append(text)
        previous_x1 = token["x1"]
        if text.endswith((",", ";", ":")):
            chunks.append([])
            previous_x1 = None
    return [" ".join(chunk) for chunk in chunks if chunk]


def clean_terms(chunks: list[str], lexicon: set[str]) -> list[str]:
    output: list[str] = []
    for chunk in chunks:
        for piece in re.split(r"[,;:]", chunk):
            candidate = clean(re.sub(r"[^A-Za-z0-9'\- ]+", " ", piece)).lower()
            if len(candidate) < 3:
                continue
            parts = [part for part in candidate.split(" ") if len(part) > 1 or part == "a"]
            resolved = [resolve_word(part, lexicon) for part in parts]
            if not resolved or not all(resolved):
                continue
            term = " ".join(resolved)
            if term not in output:
                output.append(term)
    return output


def letters_split(value: str) -> list[str]:
    return [part for part in re.split(r"[^a-z]+", value.lower()) if part]


def example_pool(example_words: list[str]) -> set[str]:
    pool: set[str] = set()
    for token in example_words:
        lowered = token.lower().strip(".,;:!?()\"'")
        if not lowered:
            continue
        pool.add(lowered)
        pool.update(inflection_forms(lowered))
        pool.update(letters_split(lowered))
    return pool


def appears_in_example(word: str, pool: set[str]) -> bool:
    """The book always demonstrates a headword in its own example sentence."""
    parts = [part for part in letters_split(word) if part not in EXTRA_LEXICON]
    if not parts:
        parts = letters_split(word)
    if not parts:
        return False
    for part in parts:
        forms = set(inflection_forms(part)) | {part}
        if forms & pool:
            continue
        if len(part) >= 4 and any(item.startswith(part[:4]) for item in pool):
            continue
        if any(
            difflib.SequenceMatcher(None, part, item).ratio() >= 0.72 for item in pool
        ):
            continue
        return False
    return True


def clean_example(tokens: list[str], lexicon: set[str]) -> tuple[str, bool]:
    kept = [token for token in tokens if is_english_token(token)]
    dropped = len(tokens) - len(kept)
    # OCR noise that survives the token filter clusters at the ends of the line,
    # where the book prints the Korean gloss, so trim from both sides.
    def known(token: str) -> bool:
        stripped = token.strip(".,;:!?()\"'").lower()
        return bool(stripped) and (
            stripped in lexicon or NUMBER_TOKEN.match(stripped) is not None
        )

    while kept and not known(kept[-1]):
        kept.pop()
        dropped += 1
    while kept and not known(kept[0]):
        kept.pop(0)
        dropped += 1
    # A stray initial or unit-like word can survive after the sentence already
    # ended ("... information. Lb."), so drop short tails behind a full stop.
    while (
        len(kept) >= 2
        and len(kept[-1].strip(".,;:!?()\"'")) <= 3
        and kept[-2].endswith((".", "!", "?"))
    ):
        kept.pop()
        dropped += 1

    text = clean(" ".join(kept))
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    if text and not text.endswith((".", "!", "?", '"')):
        text = f"{text}."
    return text, dropped > 0


def build_entries(pdf_path: Path, cmudict: Path | None) -> tuple[list[dict], dict]:
    pages: dict[int, dict] = {}
    index_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            if page_index < CONTENT_PAGE_COUNT:
                if page_index % BLOCK_PAGES >= PAGES_PER_DAY * 3:
                    continue  # review-test pages
                part = split_page(page_index, read_rows(page), page.height)
                if part:
                    pages[page_index] = part
            elif page_index >= INDEX_FIRST_PAGE:
                index_text.append(page.extract_text() or "")

    raw_days = [(day, *parse_day(pages, day)) for day in range(1, DAY_COUNT + 1)]
    all_entries = [entry for _, _, entries in raw_days for entry in entries]
    lexicon = build_lexicon(parse_index_lexicon(index_text), all_entries, cmudict)

    stats = Counter()
    unresolved: list[dict] = []
    results: list[dict] = []
    for day, heads, entries in raw_days:
        aligned = align_gloss([entry["bold"] for entry in entries], heads)
        for number, entry in enumerate(entries, start=1):
            example_words = [
                token.strip(".,;:!?()\"'")
                for sense in entry["senses"]
                for token in sense["example"]
            ]
            hints = [word for word in example_words if len(word) >= 4]
            hints += [head for head in heads]
            pool = example_pool(example_words)
            word, status = resolve_headword(
                entry["bold"], aligned[number - 1], lexicon, hints, pool
            )
            if word and not appears_in_example(word, pool):
                stats["exampleMismatch"] += 1
            stats[status] += 1
            if not word or status == "unresolved":
                unresolved.append(
                    {"day": day, "no": number, "bold": entry["bold"], "guess": word}
                )
                if not word:
                    continue

            senses = []
            for sense in entry["senses"]:
                example, suspect = clean_example(sense["example"], lexicon)
                stats["exampleSuspect" if suspect else "exampleClean"] += 1
                senses.append(
                    {
                        "pos": POS_LABELS.get(sense["pos"], sense["pos"]),
                        "index": sense["index"],
                        "synonyms": clean_terms(
                            split_synonym_chunks(sense["synonyms"]), lexicon
                        ),
                        "exampleEn": example,
                    }
                )
            antonyms = clean_terms(entry["antonyms"], lexicon)
            results.append(
                {
                    "day": day,
                    "no": number,
                    "word": word,
                    "senses": senses,
                    "antonyms": [item for item in antonyms if item != word],
                }
            )

    meta = {
        "totalPages": total_pages,
        "headwordStatus": {
            key: stats[key]
            for key in ("clean", "collapsed", "fromGloss", "repaired", "unresolved", "empty")
        },
        "examples": {"clean": stats["exampleClean"], "suspect": stats["exampleSuspect"]},
        "headwordsMissingFromExample": stats["exampleMismatch"],
        "lexiconSize": len(lexicon),
        "unresolved": unresolved,
    }
    return results, meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a normalized word list from the Hackers TOEFL Vocabulary scan."
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--cmudict",
        type=Path,
        help="Optional CMUdict .dict file used to widen the spelling lexicon.",
    )
    args = parser.parse_args()

    entries, meta = build_entries(args.pdf, args.cmudict)
    duplicates = [
        word for word, count in Counter(entry["word"] for entry in entries).items() if count > 1
    ]
    payload = {
        "_meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": args.pdf.name,
            "label": "TOEFLVOCA",
            "description": "Hackers TOEFL Vocabulary 60일 구성을 4일씩 묶은 15일 단어장",
            "bookDays": DAY_COUNT,
            "count": len(entries),
            "duplicateHeadwords": sorted(duplicates),
            **meta,
        },
        "entries": entries,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(entries):,} entries to {args.output}")
    print(f"Headwords: {meta['headwordStatus']}")
    print(f"Examples: {meta['examples']}")
    print(f"Unresolved headwords: {len(meta['unresolved'])}")


if __name__ == "__main__":
    main()
