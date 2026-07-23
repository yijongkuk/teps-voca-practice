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
    "acquitted": "무죄를 선고받은",
    "adhere": "고수하다, 준수하다, 들러붙다",
    "adjourned": "연기된, 휴회한",
    "advised": "조언한, 권고한",
    "affirmed": "확인한, 단언한, 인정한",
    "braced": "대비한, 버틴, 지탱한",
    "broached": "화제를 꺼낸, 문제를 제기한",
    "calorie-dense": "칼로리가 높은, 열량이 높은",
    "calibrating": "보정하는, 조정하는",
    "captured": "포착된, 붙잡힌, 촬영된",
    "clogged": "막힌, 막아 버린",
    "composed": "구성된, 작곡한, 침착한",
    "configurated": "구성된, 설정된",
    "converting": "전환하는, 변환하는",
    "corroborate": "입증하다, 뒷받침하다",
    "crooned": "감미롭게 노래한, 낮은 목소리로 노래한",
    "delineated": "윤곽을 그린, 명확히 기술한",
    "deluged": "물에 잠긴, 쇄도에 시달린",
    "digesting": "소화하는, 이해하는",
    "discharged": "퇴원한, 해고된, 석방된, 방출된",
    "dismissed": "해고된, 해임된, 묵살된, 기각된",
    "dissipated": "흩어진, 소멸한, 낭비한",
    "elaborating": "자세히 설명하는, 정교하게 만드는",
    "embarking": "착수하는, 승선하는",
    "eradicated": "근절된, 완전히 없어진",
    "evacuated": "대피한, 대피시킨, 비운",
    "evaluated": "평가된, 평가한",
    "exasperated": "몹시 화가 난, 격분한",
    "extruded": "압출된, 밀려 나온",
    "granted": "승인된, 주어진, 인정된",
    "inspired": "영감을 받은, 영감을 준",
    "inaugurated": "취임한, 개시한",
    "included": "포함된",
    "lugged": "힘겹게 나른, 질질 끌고 간",
    "obstructed": "막힌, 방해받은",
    "overhead compartment": "머리 위 짐칸, 기내 선반",
    "practice": "연습, 실천, 관행",
    "prevent a from -ing": "A가 ~하는 것을 막다, A가 ~하는 것을 방지하다",
    "prevent": "막다, 방지하다",
    "professed": "공언한, 자칭하는",
    "publicity stunt": "홍보용 술책, 관심 끌기용 행동",
    "secluded": "외딴, 한적한",
    "squeezed": "압착된, 짜낸, 꽉 끼인",
    "superstitions": "미신, 미신적 믿음",
    "tactless": "요령 없는, 경솔한",
    "tang": "톡 쏘는 맛, 톡 쏘는 냄새",
    "tempting": "솔깃한, 유혹적인",
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


def collect_naver_meanings(
    term: str,
    data: dict,
    limit: int = 5,
    senses_per_pos: int = 2,
    per_sense: int = 1,
) -> list[str]:
    # Each POS group is a numbered list of dictionary senses ("means"), and each
    # sense's own value is often itself a comma list of near-synonyms (e.g. sense
    # 1 = "공급, 제공", sense 2 = "대비, 준비"). Capping on raw synonym count let a
    # single sense's synonym cluster eat the whole budget and crowd out a later,
    # genuinely different sense. Cap on distinct senses instead, taking only the
    # top synonym from each, so breadth of meaning wins over depth of synonymy.
    items = iter_search_items(data)
    items = selected_items(term, items)

    meanings: list[str] = []
    seen: set[str] = set()
    for item in items:
        for collector in item.get("meansCollector", []) or []:
            senses_used = 0
            for meaning in collector.get("means", []) or []:
                added_this_sense = 0
                for part in split_meaning(meaning.get("value", "")):
                    normalized = re.sub(r"\s+", "", part)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    meanings.append(part)
                    added_this_sense += 1
                    if added_this_sense >= per_sense or len(meanings) >= limit:
                        break
                senses_used += 1
                if senses_used >= senses_per_pos or len(meanings) >= limit:
                    break
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


def guess_singular(term: str) -> str | None:
    lower = term.lower()
    if len(lower) < 4 or not lower.endswith("s") or lower.endswith("ss"):
        return None
    if lower.endswith("ies"):
        return lower[:-3] + "y"
    if lower.endswith(("ches", "shes", "xes", "zes")):
        return lower[:-2]
    return lower[:-1]


def collect_meanings(
    term: str,
    naver_meanings: list[str],
    search_data: dict | None,
    google_data: dict | None,
    papago_data: dict | None,
    limit: int = 5,
) -> list[str]:
    meanings: list[str] = []
    seen: set[str] = set()

    translation_first = search_data is not None and not has_direct_entry(term, search_data)
    if translation_first:
        if google_data and not google_data.get("_error"):
            add_candidates(meanings, seen, collect_google_translation(google_data), limit)
        if papago_data and not papago_data.get("_error"):
            add_candidates(meanings, seen, collect_papago_translation(papago_data), limit)
        add_candidates(meanings, seen, naver_meanings, limit)
    else:
        add_candidates(meanings, seen, naver_meanings, limit)
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
    saved_cache_size = len(cache)
    saved_translation_cache_size = len(translation_cache)
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

        # Plural entries (e.g. "provisions") sometimes carry only a narrow,
        # idiomatic sense in the dictionary while the singular lemma has the
        # fuller set of common meanings. Top up from the singular when thin,
        # but only as an addition -- it must not change whether translation
        # fallback runs, or it can bump a better Google/Papago sense for a
        # weaker singular-lemma one (e.g. "embodiments" losing "실시예").
        if use_naver and len(naver_meanings) <= 2:
            singular = guess_singular(term)
            if singular:
                singular_data = get_search_data(singular, cache, delay)
                if singular_data and not singular_data.get("_error"):
                    extra = collect_naver_meanings(singular, singular_data)
                    seen_norm = {re.sub(r"\s+", "", m) for m in naver_meanings}
                    for candidate in extra:
                        normalized = re.sub(r"\s+", "", candidate)
                        if normalized in seen_norm:
                            continue
                        seen_norm.add(normalized)
                        naver_meanings.append(candidate)

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
        meanings = collect_meanings(term, naver_meanings, search_data, google_data, papago_data)
        if meanings:
            entries[generate_words_data.normalize_key(term)] = ", ".join(meanings[:5])
        else:
            missing.append(term)

        if index % 50 == 0:
            if len(cache) != saved_cache_size:
                save_json(cache_path, cache)
                saved_cache_size = len(cache)
            if len(translation_cache) != saved_translation_cache_size:
                save_json(translation_cache_path, translation_cache)
                saved_translation_cache_size = len(translation_cache)
            print(f"Processed {index}/{len(unique_terms)}")

    if len(cache) != saved_cache_size:
        save_json(cache_path, cache)
    if len(translation_cache) != saved_translation_cache_size:
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
