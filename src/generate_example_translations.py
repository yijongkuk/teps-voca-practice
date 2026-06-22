from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import generate_words_data


ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_PATH = ROOT / "example_translation_cache.json"
DEFAULT_OUTPUT_PATH = ROOT / "example_overrides.json"

GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&dj=1&q={query}"
PAPAGO_TRANSLATE_URL = "https://dict.naver.com/api3/enko/papago/translate?query={query}"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://en.dict.naver.com/",
}


def clean(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cache_key(provider: str, sentence: str) -> str:
    digest = hashlib.sha1(sentence.encode("utf-8")).hexdigest()
    return f"{provider}:{digest}"


def fetch_json(url_template: str, sentence: str) -> dict:
    url = url_template.format(query=urllib.parse.quote(sentence))
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def parse_google(data: dict) -> str:
    parts = [clean(sentence.get("trans")) for sentence in data.get("sentences", []) or []]
    return clean(" ".join(part for part in parts if part))


def parse_papago(data: dict) -> str:
    return clean(data.get("translateResult", {}).get("translatedText", ""))


def valid_translation(value: str) -> bool:
    if not value or not re.search(r"[가-힣]", value):
        return False
    if re.search(r"문제가 발생|다시 시도|error|https?://", value, flags=re.IGNORECASE):
        return False
    return True


def english_token_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'-]+", value or ""))


def compact_korean_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value or ""))


def is_suspect_example(word: dict) -> bool:
    example_en = clean(word.get("exampleEn"))
    example_ko = clean(word.get("exampleKo"))
    if not example_en:
        return False
    if not example_ko:
        return True
    if re.search(r"문제가 발생|다시 시도|error", example_ko, flags=re.IGNORECASE):
        return True
    english_words = english_token_count(example_en)
    korean_length = compact_korean_length(example_ko)
    return english_words >= 8 and korean_length < max(12, english_words * 1.1)


def translate_with_provider(provider: str, sentence: str, cache: dict[str, dict], lock: threading.Lock) -> str:
    key = cache_key(provider, sentence)
    with lock:
        cached = cache.get(key)
    if cached:
        return clean(cached.get("translation", ""))

    try:
        if provider == "papago":
            data = fetch_json(PAPAGO_TRANSLATE_URL, sentence)
            translation = parse_papago(data)
        elif provider == "google":
            data = fetch_json(GOOGLE_TRANSLATE_URL, sentence)
            translation = parse_google(data)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    except Exception as exc:
        with lock:
            cache[key] = {
                "provider": provider,
                "source": sentence,
                "translation": "",
                "error": str(exc),
            }
        return ""

    with lock:
        cache[key] = {
            "provider": provider,
            "source": sentence,
            "translation": translation,
        }
    return translation


def translate_sentence(sentence: str, providers: list[str], cache: dict[str, dict], lock: threading.Lock) -> str:
    for provider in providers:
        translation = translate_with_provider(provider, sentence, cache, lock)
        if valid_translation(translation):
            return translation
    return ""


def build_sentence_map(limit: int | None, only_suspect: bool) -> dict[str, list[str]]:
    words = generate_words_data.build_words()
    sentence_to_ids: dict[str, list[str]] = {}
    for word in words:
        if only_suspect and not is_suspect_example(word):
            continue
        sentence = clean(word.get("exampleEn"))
        if not sentence:
            continue
        sentence_to_ids.setdefault(sentence, []).append(word["id"])
    if limit is None:
        return sentence_to_ids
    return dict(list(sentence_to_ids.items())[:limit])


def merge_overrides(output_path: Path, translations: dict[str, str], sentence_to_ids: dict[str, list[str]]) -> dict:
    payload = load_json(output_path, {"entries": {}})
    entries = payload.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        payload["entries"] = entries

    for sentence, translation in translations.items():
        if not valid_translation(translation):
            continue
        for word_id in sentence_to_ids.get(sentence, []):
            existing = entries.get(word_id, {})
            if not isinstance(existing, dict):
                existing = {}
            existing["exampleKo"] = translation
            entries[word_id] = existing

    payload["_meta"] = {
        "source": "Papago first, Google Translate fallback",
        "translatedExamples": sum(1 for value in entries.values() if isinstance(value, dict) and value.get("exampleKo")),
    }
    return payload


def build_translations(
    limit: int | None,
    cache_path: Path,
    output_path: Path,
    providers: list[str],
    workers: int,
    only_suspect: bool,
) -> dict:
    sentence_to_ids = build_sentence_map(limit, only_suspect)
    cache = load_json(cache_path, {})
    cache_lock = threading.Lock()
    translations: dict[str, str] = {}

    sentences = list(sentence_to_ids)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_sentence = {
            executor.submit(translate_sentence, sentence, providers, cache, cache_lock): sentence
            for sentence in sentences
        }
        for index, future in enumerate(as_completed(future_to_sentence), start=1):
            sentence = future_to_sentence[future]
            translations[sentence] = clean(future.result())
            if index % 50 == 0 or index == len(sentences):
                with cache_lock:
                    save_json(cache_path, cache)
                print(f"Translated {index}/{len(sentences)} examples")
                sys.stdout.flush()

    with cache_lock:
        save_json(cache_path, cache)
    payload = merge_overrides(output_path, translations, sentence_to_ids)
    save_json(output_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Korean example translations for TEPS cards.")
    parser.add_argument("--limit", type=int, default=None, help="Only translate the first N unique examples.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--only-suspect",
        action="store_true",
        help="Only translate examples with blank, error-like, or unusually short Korean text.",
    )
    parser.add_argument(
        "--providers",
        default="papago,google",
        help="Comma-separated provider order: papago,google",
    )
    args = parser.parse_args()

    providers = [provider.strip() for provider in args.providers.split(",") if provider.strip()]
    payload = build_translations(
        args.limit,
        args.cache,
        args.output,
        providers,
        max(1, args.workers),
        args.only_suspect,
    )
    print(f"Wrote example translations to {args.output} ({payload['_meta']['translatedExamples']} translated examples)")


if __name__ == "__main__":
    main()
