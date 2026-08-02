"""Build a normalized word list from the scanned Hackers Super Vocabulary book.

Like the TOEFL scan this PDF only carries a noisy OCR text layer, so the parser
reads the page layout instead of the characters. Every entry is laid out the
same way: an oversized headword and a bracketed pronunciation in the narrow left
column, then an English definition, a Korean gloss behind an "I" separator, an
example sentence, and one or more relationship rows ("ANT curt : wordy") that
are the point of this book. Damaged spellings are repaired against a lexicon
built from the book's own index pages and from its example sentences.
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
DEFAULT_PDF_PATH = ROOT / "02 SUPERVOCA.pdf"
DEFAULT_OUTPUT_PATH = ROOT / "super_word_list.json"

DAY_COUNT = 30
# The book runs 30 days and offers a 15-day condensed plan of its own, so two
# book days make one study chunk.
BOOK_DAYS_PER_CHUNK = 2
INDEX_FIRST_PAGE = 465

POS_TOKENS = {"n", "v", "adj", "adv", "prep", "conj", "pron"}
ENGLISH_TOKEN = re.compile(r"^[(\"'\[]?[A-Za-z][A-Za-z'\-]*[.,;:!?)\"'\]]*$")
NUMBER_TOKEN = re.compile(r"^[\d.,%$]+$")
LETTERS_ONLY = re.compile(r"[^a-z]")

# The 13 relationship patterns the book teaches. Two of them are printed with
# Korean labels that the scan renders as noise, so they fall back to a generic
# label rather than being guessed at.
RELATION_LABELS = {
    "SYN": "동의어",
    "POS": "긍정",
    "ANT": "반의어",
    "WO": "무·부재",
    "CN": "불가·부정",
    "DE": "정도",
    "KIN": "종류",
    "PAR": "부분",
    "CH": "성격",
    "PUR": "목적·용도",
    "FUN": "기능",
}
RELATION_ALIASES = {"SVN": "SYN", "SYM": "SYN", "ANI": "ANT", "AN": "ANT", "FN": "FUN"}
GENERIC_RELATION = "관계"

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


def letters(value: str) -> str:
    return LETTERS_ONLY.sub("", value.lower())


def letters_split(value: str) -> list[str]:
    return [part for part in re.split(r"[^a-z]+", value.lower()) if part]


def median(values, fallback=None):
    return statistics.median(values) if values else fallback


def is_english_token(text: str) -> bool:
    return bool(ENGLISH_TOKEN.match(text) or NUMBER_TOKEN.match(text))


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


def column_split(rows: list[list[dict]]) -> float:
    """Find the gutter between the headword column and the entry body."""
    xs = sorted({round(w["x0"], 1) for row in rows for w in row if 40 <= w["x0"] <= 180})
    best, widest = 100.0, 0.0
    for left, right in zip(xs, xs[1:]):
        middle = (left + right) / 2
        if right - left > widest and 60 <= middle <= 145:
            best, widest = middle, right - left
    return best


def is_day_title(rows: list[list[dict]]) -> bool:
    return any(
        w["size"] >= 20 and re.fullmatch(r"DAY[.·]?", w["text"])
        for row in rows
        for w in row
    )


def split_page(page_index: int, rows: list[list[dict]], height: float) -> dict:
    split = column_split(rows)
    body = [row for row in rows if row[0]["top"] < height - 40]

    translation_start = len(body)
    for index, row in enumerate(body):
        if row[0]["top"] < 0.6 * height:
            continue
        if any(w["text"].upper().startswith("TRANSLATION") for w in row):
            translation_start = index
            break

    entries_rows, translation_rows = body[:translation_start], body[translation_start:]
    example_left = median(
        [
            min(
                w["x0"]
                for w in row
                if w["x0"] >= split and "Times" in w["fontname"] and w["size"] >= 9.5
            )
            for row in entries_rows
            if any(
                w["x0"] >= split and "Times" in w["fontname"] and w["size"] >= 9.5
                for w in row
            )
        ],
        split,
    )
    head_size = max(
        (w["size"] for row in entries_rows for w in row if w["x0"] < split),
        default=0.0,
    )
    return {
        "page": page_index,
        "split": split,
        "exampleLeft": example_left,
        "headSize": head_size,
        "body": entries_rows,
        "translation": translation_rows,
    }


def is_headword_token(word: dict, part: dict) -> bool:
    return (
        word["x0"] < part["split"]
        and word["size"] >= max(11.0, part["headSize"] - 1.6)
        and not word["text"].startswith("[")
        and bool(re.match(r"^[A-Za-z][A-Za-z'\- ]*$", word["text"]))
    )


def translation_headwords(part: dict) -> list[str]:
    terms = []
    for row in part["translation"]:
        tokens = [w["text"] for w in row if w["x0"] < part["split"]]
        term = clean(" ".join(tokens))
        if term and not term.upper().startswith("TRANSLATION"):
            terms.append(term)
    return terms


def dominant_family(tokens: list[dict]) -> str:
    families = Counter(
        "times" if "Times" in w["fontname"] else "helvetica" for w in tokens
    )
    return families.most_common(1)[0][0] if families else "helvetica"


def example_tokens(right: list[dict], example_left: float) -> list[dict]:
    """Read one example line, marking the gaps the scan left behind.

    The book italicises the headword inside every example and the scan often
    drops those glyphs entirely, leaving a wide blank ("The ___ of the handgun
    law shocked the public"). A gap much wider than a word space is that missing
    headword, so record a placeholder for it instead of silently closing up.
    """
    tokens: list[dict] = []
    if right[0]["x0"] > example_left + 26:
        tokens.append({"text": None, "italic": True})
    previous_x1 = None
    for word in right:
        if word["size"] < 8:
            continue  # specks the scan left between words
        if previous_x1 is not None and word["x0"] - previous_x1 > 22:
            tokens.append({"text": None, "italic": True})
        italic = "Italic" in word["fontname"] or "Oblique" in word["fontname"]
        tokens.append({"text": word["text"], "italic": italic})
        previous_x1 = word["x1"]
    return tokens


def parse_relation(right: list[dict], split: float) -> dict | None:
    colon = next((i for i, w in enumerate(right) if w["text"] == ":"), None)
    if colon is None or colon == 0 or len(right) > 9:
        return None
    pair_start = right[colon]["x0"]
    code_tokens = [w for w in right[:colon] if w["x1"] < pair_start - 18]
    after = [
        w["text"]
        for w in right[colon + 1 :]
        if not w["text"].startswith(("[", "(")) and w["size"] >= 8
    ]
    while len(after) > 1 and len(after[-1].strip(".,;:")) <= 1:
        after.pop()
    related = clean(" ".join(after))
    if not related:
        return None
    return {"code": clean(" ".join(w["text"] for w in code_tokens)), "related": related}


def normalize_relation(code: str) -> tuple[str, str]:
    key = re.sub(r"[^A-Za-z]", "", code).upper()
    key = RELATION_ALIASES.get(key, key)
    if key in RELATION_LABELS:
        return key, RELATION_LABELS[key]
    matches = difflib.get_close_matches(key, RELATION_LABELS, n=1, cutoff=0.8)
    if matches:
        return matches[0], RELATION_LABELS[matches[0]]
    return "", GENERIC_RELATION


def parse_day(parts: list[dict]) -> tuple[list[str], list[dict]]:
    heads: list[str] = []
    for part in parts:
        for term in translation_headwords(part):
            if not heads or heads[-1].lower() != term.lower():
                heads.append(term)

    entries: list[dict] = []
    current: dict | None = None
    for part in parts:
        split = part["split"]
        current = None  # entries never run across a page break in this book
        for row in part["body"]:
            left = [w for w in row if w["x0"] < split]
            right = [w for w in row if w["x0"] >= split]
            heads_here = [w for w in left if is_headword_token(w, part)]
            if heads_here:
                current = {
                    "page": part["page"],
                    "head": clean(" ".join(w["text"] for w in heads_here)),
                    "definition": [],
                    "example": [],
                    "relations": [],
                    "separated": False,
                    "sawExample": False,
                }
                entries.append(current)
            if not current or not right:
                continue

            relation = parse_relation(right, split)
            if relation:
                current["relations"].append(relation)
                current["sawExample"] = True
                continue

            if dominant_family(right) == "times" and max(w["size"] for w in right) >= 9.5:
                current["example"].extend(example_tokens(right, part["exampleLeft"]))
                current["sawExample"] = True
                continue

            if current["sawExample"] or current["separated"]:
                continue
            # The Korean gloss sits behind a lone "I" on the definition line.
            for word in right:
                if word["text"] in ("I", "|", "l") and current["definition"]:
                    current["separated"] = True
                    break
                current["definition"].append(word["text"])
    return heads, entries


def build_lexicon(index_text: list[str], entries: list[dict], cmudict: Path | None) -> set[str]:
    lexicon = set(EXTRA_LEXICON)
    for text in index_text:
        for token in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
            lexicon.add(token.lower())
    if cmudict and cmudict.exists():
        for line in cmudict.read_text(encoding="utf-8", errors="ignore").splitlines():
            token = re.sub(r"\(\d+\)$", "", line.split(" ", 1)[0]).lower()
            if re.fullmatch(r"[a-z][a-z'\-]*", token):
                lexicon.add(token)
    for entry in entries:
        tokens = [
            *entry["definition"],
            *(t["text"] for t in entry["example"] if t["text"] and not t["italic"]),
        ]
        for token in tokens:
            stripped = token.strip(".,;:!?()\"'").lower()
            if re.fullmatch(r"[a-z][a-z'\-]{2,}", stripped):
                lexicon.add(stripped)
    return lexicon


def inflection_forms(word: str) -> list[str]:
    forms = [word]
    for suffix, replacement in (
        ("ies", "y"), ("ied", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)] + replacement
            forms.append(base)
            if suffix in ("ing", "ed"):
                forms.append(base + "e")
    return forms


def example_pool(tokens: list[str]) -> set[str]:
    pool: set[str] = set()
    for token in tokens:
        lowered = token.lower().strip(".,;:!?()\"'")
        if not lowered:
            continue
        pool.add(lowered)
        pool.update(inflection_forms(lowered))
        pool.update(letters_split(lowered))
    return pool


def appears_in(word: str, pool: set[str]) -> bool:
    parts = [part for part in letters_split(word) if part not in EXTRA_LEXICON]
    if not parts:
        parts = letters_split(word)
    if not parts:
        return False
    for part in parts:
        if (set(inflection_forms(part)) | {part}) & pool:
            continue
        if len(part) >= 4 and any(item.startswith(part[:4]) for item in pool):
            continue
        if any(difflib.SequenceMatcher(None, part, item).ratio() >= 0.72 for item in pool):
            continue
        return False
    return True


def repair_term(raw: str, lexicon: set[str], hints: list[str]) -> tuple[str, str]:
    term = clean(re.sub(r"[^A-Za-z'\- ]+", "", clean(raw)))
    if not term:
        return "", "empty"
    tokens = [token for token in term.split(" ") if token]
    if all(token.lower().strip("'-") in lexicon for token in tokens):
        return term.lower(), "clean"

    collapsed = letters(term)
    if collapsed in lexicon:
        return collapsed, "collapsed"

    candidates = {letters(hint): hint.lower() for hint in hints if letters(hint)}
    best, best_score = "", 0.0
    for key, candidate in candidates.items():
        score = difflib.SequenceMatcher(None, collapsed, key).ratio()
        if collapsed and key.startswith(collapsed[:2]):
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
    head: str, gloss: str, lexicon: set[str], hints: list[str], pool: set[str]
) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    if clean(head):
        candidates.append(repair_term(head, lexicon, hints))
        candidates.append(repair_term(letters(head), lexicon, hints))
    if clean(gloss):
        word, status = repair_term(gloss, lexicon, hints)
        candidates.append((word, "fromTranslation" if status in ("clean", "collapsed") else status))
    candidates = [(word, status) for word, status in candidates if word]
    if not candidates:
        return "", "empty"

    order = ["clean", "collapsed", "fromTranslation", "repaired", "unresolved"]

    def rank(item: tuple[str, str]) -> tuple:
        word, status = item
        return (
            appears_in(word, pool),
            all(part in lexicon for part in word.split(" ")),
            -order.index(status) if status in order else -9,
        )

    return max(candidates, key=rank)


def align_translation(entry_words: list[str], heads: list[str]) -> list[str]:
    rows, columns = len(entry_words), len(heads)
    gap = -0.35
    score = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        score[i][0] = score[i - 1][0] + gap
    for j in range(1, columns + 1):
        score[0][j] = score[0][j - 1] + gap
    similarity_cache: dict[tuple[int, int], float] = {}

    def similarity(i: int, j: int) -> float:
        if (i, j) not in similarity_cache:
            left, right = letters(entry_words[i]), letters(heads[j])
            similarity_cache[(i, j)] = (
                difflib.SequenceMatcher(None, left, right).ratio() if left and right else 0.3
            )
        return similarity_cache[(i, j)]

    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            score[i][j] = max(
                score[i - 1][j - 1] + similarity(i - 1, j - 1) - 0.45,
                score[i - 1][j] + gap,
                score[i][j - 1] + gap,
            )

    matched = [""] * rows
    i, j = rows, columns
    while i > 0 and j > 0:
        if abs(score[i][j] - (score[i - 1][j - 1] + similarity(i - 1, j - 1) - 0.45)) < 1e-9:
            matched[i - 1] = heads[j - 1]
            i, j = i - 1, j - 1
        elif abs(score[i][j] - (score[i - 1][j] + gap)) < 1e-9:
            i -= 1
        else:
            j -= 1
    return matched


def clean_sentence(
    tokens: list[dict], lexicon: set[str], headword: str
) -> tuple[str, bool]:
    # The book italicises the headword inside every example, and the scan garbles
    # those glyphs more often than the surrounding roman text ("al:Jsconaecl").
    # Restore the headword rather than dropping the word the sentence is about.
    restored: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token["italic"] and token["text"] is not None:
            restored.append(token["text"])
            index += 1
            continue
        # One italic run is one headword. The scan breaks it into fragments
        # ("s urat a" for "saturated") or loses it entirely, so rebuild the run
        # unless it still reads as the headword.
        run = []
        while index < len(tokens) and (tokens[index]["italic"] or tokens[index]["text"] is None):
            run.append(tokens[index]["text"] or "")
            index += 1
        joined = letters("".join(run))
        readable = (
            joined in lexicon
            and (
                joined.startswith(letters(headword)[:4])
                or difflib.SequenceMatcher(None, joined, letters(headword)).ratio() >= 0.75
            )
        )
        restored.append(" ".join(part for part in run if part) if readable else headword)

    kept = [token for token in restored if is_english_token(token)]
    dropped = len(restored) - len(kept)

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


def clean_definition(tokens: list[str], lexicon: set[str]) -> tuple[str, str]:
    parts_of_speech: list[str] = []
    body = list(tokens)
    while body:
        candidate = re.sub(r"[^A-Za-z]", "", body[0]).lower()
        if candidate in POS_TOKENS and len(body) > 1:
            parts_of_speech.append(f"{candidate}.")
            body.pop(0)
            continue
        break

    kept = [token for token in body if is_english_token(token)]
    while kept and kept[-1].strip(".,;:").lower() not in lexicon:
        kept.pop()
    text = clean(" ".join(kept))
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text, ", ".join(parts_of_speech)


def build_entries(pdf_path: Path, cmudict: Path | None):
    parts_by_page: dict[int, dict] = {}
    day_starts: list[int] = []
    index_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for page_index, page in enumerate(pdf.pages):
            if page_index >= INDEX_FIRST_PAGE:
                index_text.append(page.extract_text() or "")
                continue
            rows = read_rows(page)
            if is_day_title(rows):
                day_starts.append(page_index)
            parts_by_page[page_index] = split_page(page_index, rows, page.height)

    if len(day_starts) != DAY_COUNT:
        raise ValueError(f"Expected {DAY_COUNT} day title pages, found {len(day_starts)}.")

    raw_days = []
    for day, start in enumerate(day_starts, start=1):
        end = day_starts[day] if day < DAY_COUNT else INDEX_FIRST_PAGE
        parts = [parts_by_page[index] for index in range(start, end) if index in parts_by_page]
        raw_days.append((day, *parse_day(parts)))

    all_entries = [entry for _, _, entries in raw_days for entry in entries]
    lexicon = build_lexicon(index_text, all_entries, cmudict)

    stats = Counter()
    unresolved: list[dict] = []
    results: list[dict] = []
    for day, heads, entries in raw_days:
        aligned = align_translation([entry["head"] for entry in entries], heads)
        number = 0
        for index, entry in enumerate(entries):
            words_in_example = [
                token["text"] for token in entry["example"] if token["text"]
            ]
            pool = example_pool(words_in_example + entry["definition"])
            hints = [token for token in words_in_example if len(token) >= 4]
            hints.append(aligned[index])
            word, status = resolve_headword(
                entry["head"], aligned[index], lexicon, hints, pool
            )
            stats[status] += 1
            if not word or status == "unresolved":
                unresolved.append({"day": day, "head": entry["head"], "guess": word})
                if not word:
                    continue

            definition, parts_of_speech = clean_definition(entry["definition"], lexicon)
            example, suspect = clean_sentence(entry["example"], lexicon, word)
            stats["exampleSuspect" if suspect else "exampleClean"] += 1
            if len(letters(word)) < 3 or not (definition or example):
                stats["emptyBody"] += 1
                continue

            relations = []
            for relation in entry["relations"]:
                code, label = normalize_relation(relation["code"])
                related, related_status = repair_term(relation["related"], lexicon, [])
                if not related or related_status == "unresolved":
                    stats["relationDropped"] += 1
                    continue
                relations.append({"code": code, "label": label, "word": related})
                stats["relationKept"] += 1

            number += 1
            results.append(
                {
                    "day": day,
                    "no": number,
                    "word": word,
                    "pos": parts_of_speech,
                    "definitionEn": definition,
                    "exampleEn": example,
                    "relations": relations,
                }
            )

    meta = {
        "totalPages": total_pages,
        "dayStartPages": day_starts,
        "headwordStatus": {
            key: stats[key]
            for key in ("clean", "collapsed", "fromTranslation", "repaired", "unresolved", "empty")
        },
        "examples": {"clean": stats["exampleClean"], "suspect": stats["exampleSuspect"]},
        "relations": {"kept": stats["relationKept"], "dropped": stats["relationDropped"]},
        "droppedEmptyBody": stats["emptyBody"],
        "lexiconSize": len(lexicon),
        "unresolved": unresolved,
    }
    return results, meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a normalized word list from the Hackers Super Vocabulary scan."
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--cmudict", type=Path)
    args = parser.parse_args()

    entries, meta = build_entries(args.pdf, args.cmudict)
    duplicates = [
        word for word, count in Counter(entry["word"] for entry in entries).items() if count > 1
    ]
    payload = {
        "_meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": args.pdf.name,
            "label": "SUPERVOCA",
            "description": "Hackers Super Vocabulary 30일 구성을 2일씩 묶은 15일 단어장",
            "bookDays": DAY_COUNT,
            "bookDaysPerChunk": BOOK_DAYS_PER_CHUNK,
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
    print(f"Examples: {meta['examples']}; relations: {meta['relations']}")
    print(f"Unresolved: {len(meta['unresolved'])}; dropped empty: {meta['droppedEmptyBody']}")


if __name__ == "__main__":
    main()
