from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import generate_words_data


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = ROOT / "pronunciations.json"
CMUDICT_SOURCE_URL = "https://github.com/cmusphinx/cmudict"

ARPABET_IPA = {
    "AA": "ɑ",
    "AE": "æ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "EH": "ɛ",
    "EY": "eɪ",
    "IH": "ɪ",
    "IY": "i",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "UH": "ʊ",
    "UW": "u",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "P": "p",
    "R": "r",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}


def phones_to_ipa(phones: list[str]) -> str:
    output: list[str] = []
    for phone in phones:
        match = re.match(r"^([A-Z]+)([012])?$", phone)
        if not match:
            continue

        base, stress = match.groups()
        if base == "AH":
            ipa = "ə" if stress == "0" else "ʌ"
        elif base == "ER":
            ipa = "ər" if stress == "0" else "ɝ"
        else:
            ipa = ARPABET_IPA.get(base, "")

        if not ipa:
            continue
        if stress == "1":
            ipa = "ˈ" + ipa
        elif stress == "2":
            ipa = "ˌ" + ipa
        output.append(ipa)

    return "".join(output)


def load_cmudict(path: Path) -> dict[str, str]:
    pronunciations: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or line.startswith(";;;"):
            continue

        parts = line.strip().split()
        if len(parts) < 2:
            continue

        word = re.sub(r"\(\d+\)$", "", parts[0]).lower()
        pronunciations.setdefault(word, phones_to_ipa(parts[1:]))

    return pronunciations


def lookup_token(token: str, cmudict: dict[str, str]) -> str:
    if token in cmudict:
        return cmudict[token]
    if token.endswith("'s") and token[:-2] in cmudict:
        return cmudict[token[:-2]] + "z"
    if token.endswith("s") and token[:-1] in cmudict:
        return cmudict[token[:-1]] + "z"
    return ""


def term_to_ipa(term: str, cmudict: dict[str, str]) -> str:
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", term.lower().replace("’", "'"))
    if not tokens:
        return ""

    ipa_tokens: list[str] = []
    for token in tokens:
        ipa = lookup_token(token, cmudict)
        if not ipa:
            return ""
        ipa_tokens.append(ipa)

    return " ".join(ipa_tokens)


def build_pronunciations(cmudict_path: Path) -> dict:
    cmudict = load_cmudict(cmudict_path)
    words = generate_words_data.build_words()
    entries: dict[str, str] = {}
    missing: list[str] = []

    for word in words:
        key = generate_words_data.normalize_key(word["word"])
        if key in entries:
            continue

        pronunciation = term_to_ipa(word["word"], cmudict)
        if pronunciation:
            entries[key] = pronunciation
        else:
            missing.append(word["word"])

    return {
        "_meta": {
            "source": "CMU Pronouncing Dictionary",
            "sourceUrl": CMUDICT_SOURCE_URL,
            "format": "IPA converted from ARPABET",
            "coverage": len(entries),
            "missing": len(missing),
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate IPA pronunciations for the TEPS word list.")
    parser.add_argument("cmudict", type=Path, help="Path to a CMUdict .dict file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    payload = build_pronunciations(args.cmudict)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(payload['entries'])} pronunciations to {args.output} "
        f"({payload['_meta']['missing']} missing)"
    )


if __name__ == "__main__":
    main()
