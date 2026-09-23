from queue import Queue
from threading import Event, Lock

from core.planner import ActionPlanner
from core.conversation import ConversationManager
from voice.speaker import Speaker


def test_natural_github_request_executes_browser_capability(monkeypatch):
	calls = []
	monkeypatch.setattr(
		"core.planner.execute_capability",
		lambda name, **arguments: calls.append((name, arguments)) or type("Result", (), {"success": True, "result": "GitHub is open.", "tool": name, "error": None})(),
	)

	result = ActionPlanner().execute("Take me to GitHub.")

	assert result.success is True
	assert calls == [("browser.open_url", {"url": "https://github.com"})]


def test_music_goal_executes_play_capability_with_mood(monkeypatch):
	calls = []
	monkeypatch.setattr(
		"core.planner.execute_capability",
		lambda name, **arguments: calls.append((name, arguments)) or type("Result", (), {"success": True, "result": "Playing.", "tool": name, "error": None})(),
	)

	result = ActionPlanner().execute("Play something chill while I work.")

	assert result.success is True
	assert calls == [("media.play", {"mood": "relaxed"})]


def test_speaker_stop_purges_engine_and_invalidates_generation():
	speaker = Speaker.__new__(Speaker)
	speaker.queue = Queue()
	speaker.queue.put(("stale sentence", 0))
	speaker.engine = type("Engine", (), {"calls": [], "Speak": lambda self, text, flags: self.calls.append((text, flags))})()
	speaker.engine_lock = Lock()
	speaker.cancel_event = Event()
	speaker.speaking = Event()
	speaker.generation = 0

	speaker.stop_speaking()

	assert speaker.generation == 1
	assert speaker.cancel_event.is_set()
	assert speaker.engine.calls == [("", 2)]
	assert speaker.queue.empty()


def test_begin_utterance_resets_latched_cancel_state():
	"""After an interruption the cancel latch must clear, or every later
	enqueued sentence is silently dropped and JARVIS stops reading."""
	speaker = Speaker.__new__(Speaker)
	speaker.queue = Queue()
	speaker.cancel_event = Event()
	speaker.speaking = Event()
	speaker.cancel_event.set()
	speaker.speaking.set()
	speaker.begin_utterance()
	assert not speaker.cancel_event.is_set()
	assert not speaker.speaking.is_set()


def test_simple_voice_response_is_one_sentence():
	manager = ConversationManager.__new__(ConversationManager)
	response = manager._voice_response(
		"Hello Aayush. I can see you've started a conversation. I'm ready to chat.",
		"general_request",
		"Hello.",
	)

	assert response == "Hello Aayush."


def test_explanation_request_is_not_truncated():
	manager = ConversationManager.__new__(ConversationManager)
	response = manager._voice_response(
		"Quantum entanglement links measurements across distance. It is a useful concept in quantum information.",
		"general_question",
		"Why is quantum entanglement important?",
	)

	assert response.count(".") == 2


def test_common_social_checks_use_short_local_responses():
	manager = ConversationManager.__new__(ConversationManager)
	manager.preference_store = type("Store", (), {"snapshot": lambda self: {"user_facts": {"name": "Aayush"}}})()

	assert manager._quick_response("Can you hear me?") == "I'm here."
	assert manager._quick_response("Thanks") == "Anytime."
	assert manager._quick_response("What's my name?") == "You're Aayush."
	assert manager._quick_response("What is quantum entanglement?") is None
