"""Safe browser actions for JARVIS."""

from __future__ import annotations

import webbrowser
import re
from urllib.parse import quote_plus


def open_url(url: str) -> str:
	"""Open an explicit HTTP(S) URL in the default browser."""
	clean = url.strip()
	if not clean.startswith(("https://", "http://")):
		raise ValueError("Only HTTP and HTTPS URLs can be opened.")
	if not webbrowser.open(clean):
		raise RuntimeError("The default browser did not accept the URL.")
	return f"Opened {clean} in your browser."


def search_web(query: str) -> str:
	"""Search the web using the default browser."""
	clean = query.strip()
	if not clean:
		raise ValueError("The search query is empty.")
	url = f"https://www.google.com/search?q={quote_plus(clean)}"
	if not webbrowser.open(url):
		raise RuntimeError("The default browser did not accept the search.")
	return f"Searching the web for {clean}."


def resolve_site(text: str) -> str | None:
	"""Resolve a natural site reference into a URL without an LLM call."""
	lower = text.lower()
	known_sites = {"github": "github.com", "youtube": "youtube.com", "spotify": "open.spotify.com", "google": "google.com", "instagram": "instagram.com", "facebook": "facebook.com", "whatsapp": "web.whatsapp.com", "linkedin": "linkedin.com", "tiktok": "tiktok.com", "telegram": "web.telegram.org"}
	known_match = next((name for name in known_sites if re.search(rf"\b{re.escape(name)}(?:\.com)?\b", lower)), None)
	if known_match:
		return f"https://{known_sites[known_match]}"
	match = re.search(r"\b([a-z0-9][a-z0-9-]*(?:\.[a-z]{2,})?)\b", lower)
	if not match:
		return None
	domain = match.group(1)
	domain = known_sites.get(domain, domain)
	if "." not in domain:
		return None
	return f"https://{domain}"


# ===========================================================================
# BROWSER NAVIGATION
# ===========================================================================


def go_back():
	"""Navigate back in the current browser (uses keyboard shortcut)."""
	import pyautogui
	pyautogui.hotkey("alt", "left")
	return "Navigated back."


def go_forward():
	"""Navigate forward in the current browser (uses keyboard shortcut)."""
	import pyautogui
	pyautogui.hotkey("alt", "right")
	return "Navigated forward."


def reload_page():
	"""Reload the current browser page (uses keyboard shortcut)."""
	import pyautogui
	pyautogui.hotkey("f5")
	return "Page reloaded."


