from __future__ import annotations

import argparse
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import generate_meaning_overrides
import generate_words_data
import requests


ROOT = Path(__file__).resolve().parent
LIST_PATH = ROOT / "external_word_lists.json"
TOEFL_LIST_PATH = ROOT / "toefl_word_list.json"
OUTPUT_PATH = ROOT / "external_word_details.json"
NAVER_CACHE_PATH = ROOT / "naver_meaning_cache.json"
_thread_state = threading.local()
MANUAL_DETAILS = {
    "error": {
        "meaning": "오류, 실수",
        "pronunciation": "ˈerər",
        "exampleEn": "The report contains several errors.",
        "exampleKo": "그 보고서에는 몇 가지 오류가 있다.",
        "detailSource": "manual",
    },
    "id": {
        "meaning": "신분증, 신원 확인",
        "pronunciation": "ˌaɪ ˈdiː",
        "exampleEn": "You need to show your ID at the entrance.",
        "exampleKo": "입구에서 신분증을 제시해야 한다.",
        "detailSource": "manual",
    },
}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_example(value: object) -> str:
    return clean(generate_meaning_overrides.strip_html(str(value or "")))


def extract_example(term: str, data: dict) -> tuple[str, str]:
    items = generate_meaning_overrides.selected_items(
        term, generate_meaning_overrides.iter_search_items(data)
    )
    fallback: tuple[str, str] = ("", "")
    for item in items:
        for collector in item.get("meansCollector", []) or []:
            for meaning in collector.get("means", []) or []:
                example_en = clean_example(meaning.get("exampleOri"))
                example_ko = clean_example(meaning.get("exampleTrans"))
                if not example_en:
                    continue
                if not fallback[0]:
                    fallback = (example_en, example_ko)
                if re.search(rf"\b{re.escape(term)}\w*\b", example_en, re.IGNORECASE):
                    return example_en, example_ko
    return fallback


def extract_pronunciation(term: str, data: dict) -> str:
    items = generate_meaning_overrides.selected_items(
        term, generate_meaning_overrides.iter_search_items(data)
    )
    for item in items:
        symbols = item.get("searchPhoneticSymbolList", []) or []
        preferred = sorted(
            symbols,
            key=lambda symbol: (
                "US" not in clean(symbol.get("symbolTypeCode"))
                and "미국" not in clean(symbol.get("symbolType")),
            ),
        )
        for symbol in preferred:
            value = clean_example(symbol.get("symbolValue"))
            if value:
                return value.replace("│", "ˈ")
    return ""


def detail_from_data(term: str, data: dict, detail_source: str) -> dict[str, str]:
    meanings = generate_meaning_overrides.collect_naver_meanings(
        term, data, limit=5
    )
    example_en, example_ko = extract_example(term, data)
    return {
        "meaning": ", ".join(meanings),
        "pronunciation": extract_pronunciation(term, data),
        "exampleEn": example_en,
        "exampleKo": example_ko,
        "detailSource": detail_source,
    }


def session() -> requests.Session:
    value = getattr(_thread_state, "session", None)
    if value is None:
        value = requests.Session()
        value.headers.update(generate_meaning_overrides.REQUEST_HEADERS)
        _thread_state.session = value
    return value


def fetch_json(url_template: str, term: str, timeout: int = 12) -> dict:
    url = url_template.format(query=urllib.parse.quote(term))
    response = session().get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def detail_from_dictionary(term: str) -> dict[str, str]:
    last_error = ""
    for attempt in range(2):
        try:
            data = fetch_json(generate_meaning_overrides.SEARCH_URL, term)
            detail = detail_from_data(term, data, "dictionary")
            if not detail["meaning"]:
                translation = fetch_json(
                    generate_meaning_overrides.GOOGLE_TRANSLATE_URL, term, timeout=8
                )
                candidates = generate_meaning_overrides.collect_google_translation(
                    translation
                )
                detail["meaning"] = candidates[0] if candidates else ""
            return detail
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.3 * (attempt + 1))

    try:
        translation = fetch_json(
            generate_meaning_overrides.GOOGLE_TRANSLATE_URL, term, timeout=8
        )
        candidates = generate_meaning_overrides.collect_google_translation(
            translation
        )
        if candidates:
            return {
                "meaning": candidates[0],
                "pronunciation": "",
                "exampleEn": "",
                "exampleKo": "",
                "detailSource": "translation-fallback",
                "warning": last_error,
            }
    except Exception as exc:
        if last_error:
            last_error = f"{last_error}; fallback: {exc}"
        else:
            last_error = str(exc)
    return {"error": last_error, "detailSource": "dictionary"}


def detail_from_translation(term: str) -> dict[str, str]:
    try:
        translation = fetch_json(
            generate_meaning_overrides.GOOGLE_TRANSLATE_URL, term, timeout=8
        )
        candidates = generate_meaning_overrides.collect_google_translation(translation)
        if candidates:
            return {
                "meaning": candidates[0],
                "pronunciation": "",
                "exampleEn": "",
                "exampleKo": "",
                "detailSource": "translation-fallback",
            }
        return {
            "error": "No usable translation returned",
            "detailSource": "translation-fallback",
        }
    except Exception as exc:
        return {"error": str(exc), "detailSource": "translation-fallback"}


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save_payload(path: Path, entries: dict[str, dict], total_terms: int) -> None:
    covered_meaning = sum(bool(entry.get("meaning")) for entry in entries.values())
    covered_example = sum(bool(entry.get("exampleEn")) for entry in entries.values())
    covered_pronunciation = sum(
        bool(entry.get("pronunciation")) for entry in entries.values()
    )
    errors = sorted(
        key for key, entry in entries.items() if entry.get("error")
    )
    payload = {
        "_meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "totalTerms": total_terms,
            "coverage": {
                "meaning": covered_meaning,
                "example": covered_example,
                "pronunciation": covered_pronunciation,
            },
            "errors": errors,
            "note": (
                "Compact study-card details generated from the project's existing "
                "English-Korean dictionary pipeline; existing TEPS cards are reused "
                "for overlapping headwords."
            ),
        },
        "entries": dict(sorted(entries.items())),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate meanings, examples, and pronunciations for external lists."
    )
    parser.add_argument("--lists", type=Path, default=LIST_PATH)
    parser.add_argument("--toefl-list", type=Path, default=TOEFL_LIST_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--cache", type=Path, default=NAVER_CACHE_PATH)
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--translation-only",
        action="store_true",
        help="Fill remaining meanings quickly without dictionary examples.",
    )
    args = parser.parse_args()

    list_payload = load_json(args.lists, {})
    toefl_payload = load_json(args.toefl_list, {})
    source_entries = [
        *list_payload.get("oxford5000", []),
        *list_payload.get("awl", []),
        *toefl_payload.get("entries", []),
    ]
    terms: dict[str, str] = {}
    for entry in source_entries:
        word = clean(entry.get("word"))
        if word:
            terms.setdefault(generate_words_data.normalize_key(word), word)
    if args.limit is not None:
        terms = dict(list(terms.items())[: args.limit])

    existing_payload = load_json(args.output, {})
    existing_entries = existing_payload.get("entries", {})
    details: dict[str, dict] = {
        key: value
        for key, value in existing_entries.items()
        if key in terms
        and isinstance(value, dict)
        and not value.get("error")
    }

    def needs_dictionary_detail(key: str) -> bool:
        detail = details.get(key, {})
        return (
            not detail
            or detail.get("error")
            or detail.get("detailSource") == "translation-fallback"
        )

    frequent_builder = getattr(
        generate_words_data, "build_frequent_words", generate_words_data.build_words
    )
    frequent_words = frequent_builder()
    frequent_by_key = {
        generate_words_data.normalize_key(word["word"]): word for word in frequent_words
    }
    for key in terms:
        if not needs_dictionary_detail(key) or key not in frequent_by_key:
            continue
        source = frequent_by_key[key]
        details[key] = {
            "meaning": clean(source.get("meaning")),
            "pronunciation": clean(source.get("pronunciation")),
            "exampleEn": clean(source.get("exampleEn")),
            "exampleKo": clean(source.get("exampleKo")),
            "detailSource": "existing-teps-card",
        }

    for key, detail in MANUAL_DETAILS.items():
        if key in terms:
            details[key] = detail

    if not args.translation_only and not args.skip_cache and args.cache.exists():
        print(f"Loading existing dictionary cache: {args.cache}")
        cached_responses = load_json(args.cache, {})
        reused_from_cache = 0
        for key, term in terms.items():
            if not needs_dictionary_detail(key):
                continue
            data = cached_responses.get(key)
            if not isinstance(data, dict) or data.get("_error"):
                continue
            detail = detail_from_data(term, data, "dictionary-cache")
            if not detail.get("meaning"):
                continue
            details[key] = detail
            reused_from_cache += 1
        del cached_responses
        print(f"Reused {reused_from_cache:,} entries from the dictionary cache")

    pending = [
        (key, term)
        for key, term in terms.items()
        if key not in details
        or (not args.translation_only and needs_dictionary_detail(key))
    ]
    print(
        f"External terms: {len(terms):,}; reused/resumed: {len(details):,}; "
        f"dictionary lookups: {len(pending):,}"
    )
    save_payload(args.output, details, len(terms))

    worker = detail_from_translation if args.translation_only else detail_from_dictionary
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(worker, term): (key, term)
            for key, term in pending
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            key, term = futures[future]
            try:
                details[key] = future.result()
            except Exception as exc:
                details[key] = {
                    "error": str(exc),
                    "detailSource": "dictionary",
                }
            if completed % 25 == 0 or completed == len(pending):
                save_payload(args.output, details, len(terms))
                print(
                    f"Processed {completed:,}/{len(pending):,} lookups "
                    f"({len(details):,}/{len(terms):,} total)"
                )

    save_payload(args.output, details, len(terms))
    print(f"Wrote {len(details):,} compact details to {args.output}")


if __name__ == "__main__":
    main()
