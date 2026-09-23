"""Fast JARVIS Chrome + YouTube Music controller."""

from __future__ import annotations

import ctypes
import subprocess
import time
import urllib.parse
from dataclasses import dataclass

import pyautogui
import pygetwindow as gw


YOUTUBE_MUSIC_URL = "https://music.youtube.com"

# Tested on 1920x1080.


# Fast timings.
ACTIVATE_WAIT = 0.15
TAB_SEARCH_WAIT = 0.20
NAVIGATION_WAIT = 1.50
SEARCH_WAIT = 2.50
PLAY_WAIT = 0.25


@dataclass
class MusicState:
    playing: bool = False
    paused: bool = False
    current_track: str | None = None
    source: str | None = None
    tab_ready: bool = False


music_state = MusicState()

# Remember the Chrome window we used.
_chrome_window = None


# ============================================================================
# CHROME
# ============================================================================

def _activate_chrome() -> bool:
    """Activate the user's existing Chrome window."""

    global _chrome_window

    # First try cached window.
    try:
        if _chrome_window and _chrome_window.title:
            if _chrome_window.isMinimized:
                _chrome_window.restore()

            _chrome_window.activate()
            time.sleep(ACTIVATE_WAIT)
            return True
    except Exception:
        _chrome_window = None

    # Find an existing Chrome window.
    try:
        windows = gw.getAllWindows()

        for window in windows:
            title = (window.title or "").lower()

            if "chrome" in title:
                if window.isMinimized:
                    window.restore()

                window.activate()
                _chrome_window = window
                time.sleep(ACTIVATE_WAIT)
                return True

    except Exception:
        pass

    # Last-resort Windows activation.
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$wshell=New-Object -ComObject WScript.Shell; "
                    "$wshell.AppActivate('Google Chrome')"
                ),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )

        time.sleep(ACTIVATE_WAIT)
        return True

    except Exception as exc:
        print(f"[MEDIA] Chrome activation error: {exc}")
        return False


def _active_title() -> str:
    """Return the active Chrome tab/window title."""

    try:
        window = gw.getActiveWindow()
        return window.title if window else ""
    except Exception:
        return ""


def _is_youtube_music(title: str) -> bool:
    """Check whether the active Chrome page is YouTube Music."""

    title = title.lower()

    return (
        "youtube music" in title
        or "music.youtube.com" in title
    )


# ============================================================================
# TAB SEARCH
# ============================================================================

def _find_or_reopen_music_tab() -> bool:
    """
    Find YouTube Music using Chrome's built-in Tab Search.

    This avoids cycling through Chrome tabs.
    """

    if not _activate_chrome():
        return False

    try:
        # Chrome Tab Search.
        pyautogui.hotkey("ctrl", "shift", "a")
        time.sleep(TAB_SEARCH_WAIT)

        # Search for an existing YouTube Music tab.
        pyautogui.write("YouTube Music", interval=0)

        time.sleep(TAB_SEARCH_WAIT)

        # Enter selects the first matching result.
        #
        # If an open YT Music tab exists, Chrome selects it.
        # If only a recently-closed YT Music tab exists, Chrome
        # can reopen it.
        pyautogui.press("enter")

        time.sleep(TAB_SEARCH_WAIT)

        title = _active_title()

        if _is_youtube_music(title):
            print(f"[MEDIA] Reusing YouTube Music: {title}")
            music_state.tab_ready = True
            return True

        # Escape in case the search popup is still open.
        pyautogui.press("esc")

        return False

    except Exception as exc:
        print(f"[MEDIA] Tab search error: {exc}")

        try:
            pyautogui.press("esc")
        except Exception:
            pass

        return False


# ============================================================================
# OPEN YOUTUBE MUSIC IN EXISTING CHROME
# ============================================================================

def _open_youtube_music_in_current_tab() -> bool:
    """
    Open YouTube Music in the current Chrome tab.

    IMPORTANT:
    This does NOT create a new Chrome window or profile.
    """

    if not _activate_chrome():
        return False

    try:
        pyautogui.hotkey("ctrl", "l")

        pyautogui.write(
            YOUTUBE_MUSIC_URL,
            interval=0,
        )

        pyautogui.press("enter")

        print("[MEDIA] Opening YouTube Music in current Chrome tab.")

        # Wait only for the initial page.
        deadline = time.time() + 4.0

        while time.time() < deadline:
            title = _active_title()

            if _is_youtube_music(title):
                music_state.tab_ready = True
                return True

            time.sleep(0.10)

        # Chrome may still be loading, but the navigation was issued.
        music_state.tab_ready = True
        return True

    except Exception as exc:
        print(f"[MEDIA] Could not open YouTube Music: {exc}")
        return False


def _get_youtube_music() -> bool:
    """
    Get YouTube Music without creating a separate Chrome window.

    Priority:
        1. Existing YT Music tab
        2. Recently closed YT Music tab
        3. Current Chrome tab
    """

    if _find_or_reopen_music_tab():
        return True

    return _open_youtube_music_in_current_tab()


# ============================================================================
# NAVIGATION / SEARCH
# ============================================================================

def _navigate(url: str) -> bool:
    """Navigate the current Chrome tab directly."""

    if not _activate_chrome():
        return False

    try:
        pyautogui.hotkey("ctrl", "l")
        pyautogui.write(url, interval=0)
        pyautogui.press("enter")

        return True

    except Exception as exc:
        print(f"[MEDIA] Navigation error: {exc}")
        return False


def _search_youtube_music(query: str) -> bool:
    """Navigate directly to a YouTube Music search."""

    query = query.strip()

    if not query:
        return False

    encoded = urllib.parse.quote_plus(query)

    url = f"{YOUTUBE_MUSIC_URL}/search?q={encoded}"

    print(f"[MEDIA] Search: {query}")

    if not _navigate(url):
        return False

    time.sleep(SEARCH_WAIT)

    return True


# ============================================================================
# PLAY BUTTON
# ============================================================================


def _click_play_button() -> bool:
    """Activate Chrome again, then click the YouTube Music Play button."""
    try:
        if not _activate_chrome():
            print("[MEDIA] Could not reactivate Chrome.")
            return False

        time.sleep(1.0) # wait for search results to load
        
        import pyautogui
        width, height = pyautogui.size()
        
        from core.screencontrol import get_screen_control
        sc = get_screen_control()
        
        # Try to click "Shuffle" which is always present on Top Result in YT Music
        res = sc.click_element("Shuffle")
        if not res.success:
            # Fallback to direct clicking the Top Result thumbnail area
            print("[MEDIA] Shuffle button not found, clicking top result area.")
            # Top result is usually around x=40%, y=40% on desktop layout
            pyautogui.moveTo(int(width * 0.4), int(height * 0.4), duration=0.2)
            pyautogui.click()
            time.sleep(0.5)
            # Just in case we clicked into an album, hit play (tab + enter usually plays first track)
            pyautogui.press('tab')
            pyautogui.press('enter')
            
        time.sleep(PLAY_WAIT)
        return True

    except Exception as exc:
        print(f"[MEDIA] Play error: {exc}")
        return False

# ============================================================================
# PUBLIC MUSIC API
# ============================================================================

def play_music(
    query: str | None = None,
    mood: str = "default",
) -> str:
    """Play a song or mood-based music."""

    if not query:
        mood_lower = (mood or "default").lower()

        mood_queries = {
            "relaxed": "relaxing music",
            "energetic": "energetic music",
            "fast": "energetic music",
            "upbeat": "upbeat music",
            "workout": "workout music",
            "hype": "hype music",
            "sad": "sad music",
            "romantic": "romantic music",
            "default": "music",
        }

        query = mood_queries.get(
            mood_lower,
            "music",
        )

    query = str(query).strip()

    if not query:
        query = "music"

    print(f"[MEDIA] PLAY REQUEST: {query}")

    # Reuse existing Chrome/YT Music.
    if not _get_youtube_music():
        raise RuntimeError(
            "I could not open or activate YouTube Music."
        )

    # Search.
    if not _search_youtube_music(query):
        raise RuntimeError(
            "I could not search YouTube Music."
        )

    # Play.
    if not _click_play_button():
        raise RuntimeError(
            "I could not start playback."
        )

    music_state.playing = True
    music_state.paused = False
    music_state.current_track = query
    music_state.source = "YouTube Music"
    music_state.tab_ready = True

    return f"Playing {query} on YouTube Music."


# ============================================================================
# MEDIA CONTROLS
# ============================================================================

def _media_key(vk: int):
    """Send a Windows media key."""

    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def stop_music() -> str:
    """Stop media playback."""

    _media_key(0xB2)

    music_state.playing = False
    music_state.paused = False

    return "Music stopped."


def pause_music() -> str:
    """Pause media playback."""

    _media_key(0xB3)

    music_state.playing = False
    music_state.paused = True

    return "Music paused."


def resume_music() -> str:
    """Resume media playback."""

    _media_key(0xB3)

    music_state.playing = True
    music_state.paused = False

    return "Music resumed."


def next_music() -> str:
    """Skip to the next track."""

    _media_key(0xB0)

    return "Skipped to the next track."


def get_music_state() -> dict:
    """Return current music state."""

    return {
        "playing": music_state.playing,
        "paused": music_state.paused,
        "current_track": music_state.current_track,
        "source": music_state.source,
        "tab_ready": music_state.tab_ready,
    }