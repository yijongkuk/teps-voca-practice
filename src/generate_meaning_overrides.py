from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import generate_words_data


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = ROOT / "meaning_overrides.json"
DEFAULT_CACHE_PATH = ROOT / "naver_meaning_cache.json"
DEFAULT_TRANSLATE_CACHE_PATH = ROOT / "translate_meaning_cache.json"

SEARCH_URL = "https://en.dict.naver.com/api3/enko/search?m=pc&range=all&query={query}"
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t&dj=1&q={query}"
PAPAGO_TRANSLATE_URL = "https://dict.naver.com/api3/enko/papago/translate?query={query}"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://en.dict.naver.com/",
}

NOISE_PATTERNS = [
    r"\(=.*?\)",
    r"\(↔.*?\)",
    r"\(→.*?\)",
    r"\[[^\]]*?\]",
]

MANUAL_MEANING_OVERRIDES = {
    "accreted": "축적된, 누적된",
    "calorie-dense": "칼로리가 높은, 열량이 높은",
    "configurated": "구성된, 설정된",
    "overhead compartment": "머리 위 짐칸, 기내 선반",
    "practice": "연습, 실천, 관행",
    "prevent a from -ing": "A가 ~하는 것을 막다, A가 ~하는 것을 방지하다",
    "publicity stunt": "홍보용 술책, 관심 끌기용 행동",
    "squeezed": "압착된, 짜낸, 꽉 끼인",
    "superstitions": "미신, 미신적 믿음",
    "tang": "톡 쏘는 맛, 톡 쏘는 냄새",
}


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(text)


def clean_meaning(value: str) -> str:
    text = strip_html(value)
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;/·")
    return text


def clean_translation(value: str) -> str:
    text = clean_meaning(value)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;/·")
    return text


def valid_translation(value: str) -> bool:
    if not value:
        return False
    if not re.search(r"[가-힣]", value):
        return False
    if re.search(r"https?://|오류|문제가 발생", value, flags=re.IGNORECASE):
        return False
    if len(value) > 32:
        return False
    return True


def split_meaning(value: str) -> list[str]:
    text = clean_meaning(value)
    if not text:
        return []

    text = re.sub(r"^\([^)]*$", "", text).strip()
    parts = re.split(r"[,;/]| 또는 | 혹은 ", text)
    results: list[str] = []
    for part in parts:
        item = part.strip(" ()[]·")
        item = re.sub(r"^\d+\.\s*", "", item)
        item = re.sub(r"^[~-]\s*", "", item)
        item = re.sub(r"^[^)]{1,24}\)\s*", "", item)
        item = re.sub(r"\s*\([^)]*$", "", item)
        item = item.strip(" ()[]·")
        if not item or re.search(r"[A-Za-z]{3,}", item):
            continue
        if re.search(r"^(과거분사|과거형|현재분사|복수형|비교급|최상급)$", item):
            continue
        if len(item) > 20:
            continue
        if re.search(r"사전$|코일|요크|문서국|발호", item):
            continue
        results.append(item)
    return results


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_search(term: str) -> dict:
    url = SEARCH_URL.format(query=urllib.parse.quote(term))
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def fetch_url(url_template: str, term: str) -> dict:
    url = url_template.format(query=urllib.parse.quote(term))
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def get_search_data(term: str, cache: dict[str, dict], delay: float) -> dict | None:
    key = generate_words_data.normalize_key(term)
    if key in cache:
        return cache[key]

    try:
        data = fetch_search(term)
    except Exception as exc:
        cache[key] = {"_error": str(exc)}
        return None

    cache[key] = data
    if delay > 0:
        time.sleep(delay)
    return data


def get_translate_data(
    provider: str,
    url_template: str,
    term: str,
    cache: dict[str, dict],
    delay: float,
) -> dict | None:
    key = f"{provider}:{generate_words_data.normalize_key(term)}"
    if key in cache:
        return cache[key]

    try:
        data = fetch_url(url_template, term)
    except Exception as exc:
        cache[key] = {"_error": str(exc)}
        return None

    cache[key] = data
    if delay > 0:
        time.sleep(delay)
    return data


def iter_search_items(data: dict) -> list[dict]:
    result_map = data.get("searchResultMap", {}).get("searchResultListMap", {})
    word_result = result_map.get("WORD", {})
    return word_result.get("items", []) or []


def item_entry_name(item: dict) -> str:
    return item_entry_label(item).lower()


def item_entry_label(item: dict) -> str:
    raw = item.get("entryName") or item.get("expEntry") or item.get("expAliasEntrySearch") or ""
    return clean_meaning(raw)


def is_capitalized_proper_match(term: str, item: dict) -> bool:
    label = item_entry_label(item)
    return bool(term and term[0].islower() and label[:1].isupper() and label.lower() == term.lower())


def exactness_score(term: str, item: dict) -> int:
    key = generate_words_data.normalize_key(term)
    name = generate_words_data.normalize_key(item_entry_name(item))
    match_type = str(item.get("matchType", ""))
    if name == key:
        return 0
    if "exact" in match_type:
        return 1
    if key in name or name in key:
        return 2
    return 5


def selected_items(term: str, items: list[dict]) -> list[dict]:
    key = generate_words_data.normalize_key(term)
    lexical_items = [item for item in items if not is_capitalized_proper_match(term, item)]
    exact = [item for item in lexical_items if exactness_score(term, item) == 0]
    if exact:
        word_items = [item for item in exact if item.get("expDictTypeForm") == "단어"]
        if word_items:
            return sorted(word_items, key=lambda item: int(item.get("rank") or 999))[:2]
        return sorted(exact, key=lambda item: int(item.get("rank") or 999))[:3]

    # Inflected forms often return the base entry first. Use only the best lexical item,
    # not nearby phrase/example entries.
    close = [item for item in lexical_items if exactness_score(term, item) <= 2 and item.get("expDictTypeForm") == "단어"]
    if close:
        return sorted(close, key=lambda item: (exactness_score(term, item), int(item.get("rank") or 999)))[:1]

    if len(key.split()) > 1:
        phrase_items = [item for item in lexical_items if exactness_score(term, item) <= 2]
        return sorted(phrase_items, key=lambda item: (exactness_score(term, item), int(item.get("rank") or 999)))[:3]

    return sorted(lexical_items or items, key=lambda item: (exactness_score(term, item), int(item.get("rank") or 999)))[:1]


def has_direct_entry(term: str, data: dict | None) -> bool:
    if not data or data.get("_error"):
        return False
    key = generate_words_data.normalize_key(term)
    for item in iter_search_items(data):
        if is_capitalized_proper_match(term, item):
            continue
        if item.get("expDictTypeForm") != "단어":
            continue
        if generate_words_data.normalize_key(item_entry_label(item)) != key:
            continue
        match_type = str(item.get("matchType", ""))
        if "exact:entry" in match_type:
            return True
    return False


def collect_naver_meanings(term: str, data: dict, limit: int = 3) -> list[str]:
    items = iter_search_items(data)
    items = selected_items(term, items)

    meanings: list[str] = []
    seen: set[str] = set()
    for item in items:
        for collector in item.get("meansCollector", []) or []:
            for meaning in collector.get("means", []) or []:
                for part in split_meaning(meaning.get("value", "")):
                    normalized = re.sub(r"\s+", "", part)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    meanings.append(part)
                    if len(meanings) >= limit:
                        return meanings
    return meanings


def collect_google_translation(data: dict) -> list[str]:
    meanings: list[str] = []
    for sentence in data.get("sentences", []) or []:
        translated = clean_translation(sentence.get("trans", ""))
        if valid_translation(translated):
            meanings.append(translated)
    return meanings[:1]


def collect_papago_translation(data: dict) -> list[str]:
    translated = clean_translation(data.get("translateResult", {}).get("translatedText", ""))
    return [translated] if valid_translation(translated) else []


def add_candidates(results: list[str], seen: set[str], candidates: list[str], limit: int) -> None:
    for candidate in candidates:
        value = clean_translation(candidate)
        if not valid_translation(value):
            continue
        normalized = re.sub(r"[\s,./;·]+", "", value)
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(value)
        if len(results) >= limit:
            return


def collect_meanings(
    term: str,
    search_data: dict | None,
    google_data: dict | None,
    papago_data: dict | None,
    limit: int = 3,
) -> list[str]:
    meanings: list[str] = []
    seen: set[str] = set()

    translation_first = search_data is not None and not has_direct_entry(term, search_data)
    if translation_first:
        if google_data and not google_data.get("_error"):
            add_candidates(meanings, seen, collect_google_translation(google_data), limit)
        if papago_data and not papago_data.get("_error"):
            add_candidates(meanings, seen, collect_papago_translation(papago_data), limit)
        if search_data and not search_data.get("_error"):
            add_candidates(meanings, seen, collect_naver_meanings(term, search_data, limit), limit)
    else:
        if search_data and not search_data.get("_error"):
            add_candidates(meanings, seen, collect_naver_meanings(term, search_data, limit), limit)
        if google_data and not google_data.get("_error"):
            add_candidates(meanings, seen, collect_google_translation(google_data), limit)
        if papago_data and not papago_data.get("_error"):
            add_candidates(meanings, seen, collect_papago_translation(papago_data), limit)

    return meanings[:limit]


def build_overrides(
    limit: int | None,
    cache_path: Path,
    translation_cache_path: Path,
    delay: float,
    use_google: bool,
    use_papago: bool,
    use_naver: bool,
) -> dict:
    cache = load_json(cache_path, {})
    translation_cache = load_json(translation_cache_path, {})
    words = generate_words_data.build_words()
    entries: dict[str, str] = {}
    missing: list[str] = []

    unique_terms: list[str] = []
    seen_terms: set[str] = set()
    for word in words:
        key = generate_words_data.normalize_key(word["word"])
        if key in seen_terms:
            continue
        seen_terms.add(key)
        unique_terms.append(word["word"])

    if limit is not None:
        unique_terms = unique_terms[:limit]

    for index, term in enumerate(unique_terms, start=1):
        search_data = get_search_data(term, cache, delay) if use_naver else None
        naver_meanings = (
            collect_naver_meanings(term, search_data)
            if search_data and not search_data.get("_error")
            else []
        )
        direct_entry = has_direct_entry(term, search_data)
        needs_translation = not direct_entry or not naver_meanings
        google_data = (
            get_translate_data("google", GOOGLE_TRANSLATE_URL, term, translation_cache, delay)
            if use_google and needs_translation
            else None
        )
        papago_data = (
            get_translate_data("papago", PAPAGO_TRANSLATE_URL, term, translation_cache, delay)
            if use_papago and needs_translation
            else None
        )
        meanings = collect_meanings(term, search_data, google_data, papago_data)
        if meanings:
            entries[generate_words_data.normalize_key(term)] = ", ".join(meanings[:3])
        else:
            missing.append(term)

        if index % 50 == 0:
            save_json(cache_path, cache)
            save_json(translation_cache_path, translation_cache)
            print(f"Processed {index}/{len(unique_terms)}")

    save_json(cache_path, cache)
    save_json(translation_cache_path, translation_cache)
    for term, meaning in MANUAL_MEANING_OVERRIDES.items():
        entries[generate_words_data.normalize_key(term)] = meaning
        if term in missing:
            missing.remove(term)
    return {
        "_meta": {
            "source": "Cool Tooltip Dictionary 14 style: Google Translate + Papago + Naver English-Korean dictionary",
            "totalTerms": len(unique_terms),
            "coverage": len(entries),
            "missing": len(missing),
            "providers": {
                "google": use_google,
                "papago": use_papago,
                "naver": use_naver,
            },
            "note": "Generated for local study data; cached to reduce repeated requests.",
        },
        "entries": entries,
        "missing": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate concise Korean meaning overrides from Naver dictionary data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--translation-cache", type=Path, default=DEFAULT_TRANSLATE_CACHE_PATH)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N unique terms.")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between uncached network requests.")
    parser.add_argument("--no-google", action="store_true", help="Do not use Google Translate.")
    parser.add_argument("--no-papago", action="store_true", help="Do not use Papago Translate.")
    parser.add_argument("--no-naver", action="store_true", help="Do not use Naver dictionary search.")
    args = parser.parse_args()

    payload = build_overrides(
        args.limit,
        args.cache,
        args.translation_cache,
        args.delay,
        not args.no_google,
        not args.no_papago,
        not args.no_naver,
    )
    save_json(args.output, payload)
    print(
        f"Wrote {len(payload['entries'])} meaning overrides to {args.output} "
        f"({payload['_meta']['missing']} missing)"
    )


if __name__ == "__main__":
    main()
