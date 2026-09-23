"""Convert model output into natural, speakable text."""

from __future__ import annotations

import re


_NUMBER_WORDS = (
	"zero", "one", "two", "three", "four", "five", "six", "seven",
	"eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
	"fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS_WORDS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _integer_to_words(value: int) -> str:
	if value < 20:
		return _NUMBER_WORDS[value]
	if value < 100:
		return _TENS_WORDS[value // 10] + (f"-{_NUMBER_WORDS[value % 10]}" if value % 10 else "")
	if value < 1000:
		remainder = value % 100
		return f"{_NUMBER_WORDS[value // 100]} hundred" + (f" {_integer_to_words(remainder)}" if remainder else "")
	if value < 1_000_000:
		remainder = value % 1000
		return f"{_integer_to_words(value // 1000)} thousand" + (f" {_integer_to_words(remainder)}" if remainder else "")
	return str(value)


def _replace_numbers(match: re.Match[str]) -> str:
	value = match.group(0)
	if "." in value:
		whole, fraction = value.split(".", 1)
		return f"{_integer_to_words(int(whole))} point {' '.join(_NUMBER_WORDS[int(d)] for d in fraction)}"
	if len(value) == 4 and 1000 <= int(value) <= 2099:
		year = int(value)
		return f"{_integer_to_words(year // 100)} {_integer_to_words(year % 100)}"
	return _integer_to_words(int(value))


def clean_for_speech(text: str) -> str:
	"""Strip document formatting and turn common numeric content into speech."""
	cleaned = text.replace("\r", " ")
	cleaned = re.sub(r"```[\s\S]*?```", " Here's the code. ", cleaned)
	cleaned = re.sub(r"!\[[^]]*\]\([^)]*\)", "", cleaned)
	cleaned = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", cleaned)
	cleaned = re.sub(r"https?://\S+|www\.\S+", " the linked page ", cleaned)
	cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"^\s*[-*+]\s+", ". ", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"^\s*\d+[.)]\s+", ". ", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"[*_`~]", "", cleaned)
	cleaned = re.sub(r"[^\w\s.,!?;:'%/-]", " ", cleaned, flags=re.UNICODE)
	cleaned = re.sub(r"(?<=\d)%", " percent", cleaned)
	cleaned = re.sub(r"\b\d+(?:\.\d+)?\b", _replace_numbers, cleaned)
	cleaned = re.sub(r"\s*\.\s*", ". ", cleaned)
	cleaned = re.sub(r":\s*\.", ".", cleaned)
	cleaned = re.sub(r"([!?.,])\1+", r"\1", cleaned)
	cleaned = re.sub(r"\s+", " ", cleaned).strip()
	return cleaned


def sentence_chunks(text: str) -> list[str]:
	"""Return speakable chunks without splitting ordinary decimal numbers."""
	cleaned = clean_for_speech(text)
	return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", cleaned) if chunk.strip()]
