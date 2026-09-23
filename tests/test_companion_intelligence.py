from core.intent import IntentEngine
from core.memory import PreferenceStore
from tools.browser import resolve_site


def test_open_ended_watch_request_uses_context_topic():
	result = IntentEngine().infer(
		"I think I want to watch something",
		["User: We have been discussing robotics"],
	)

	assert result.intent == "entertainment"
	assert result.sub_intent == "watch_video"
	assert result.confidence > 0.5


def test_preferences_gain_explicit_evidence_gradually(tmp_path):
	store = PreferenceStore(tmp_path / "preferences.json")

	store.learn_from_text("I love robotics", explicit=True)
	first = store.snapshot()["interests"]["robotics"]["confidence"]
	store.learn_from_text("I love robotics", explicit=True)
	second = store.snapshot()["interests"]["robotics"]["confidence"]

	assert 0 < first < second <= 1
	assert store.snapshot()["interests"]["robotics"]["explicit_evidence"] == 2


def test_consequential_action_requires_confirmation():
	result = IntentEngine().infer("delete that file")

	# "delete" maps to file/delete which requires confirmation
	assert result.intent == "file"
	assert result.sub_intent == "delete"
	assert result.needs_confirmation is True


def test_natural_site_reference_resolves_to_known_domain():
	assert resolve_site(" GitHub ") == "https://github.com"
	assert resolve_site(" example.com ") == "https://example.com"


def test_natural_website_goal_is_classified_as_opening():
	result = IntentEngine().infer("Can you get GitHub up?")

	# "get GitHub up" maps to browser/open_url
	assert result.intent == "browser"
	assert result.sub_intent == "open_url"


def test_music_intents_require_action_language():
	engine = IntentEngine()
	# New intent format uses simpler sub_intents
	assert engine.infer("Play some music.").sub_intent == "play"
	assert engine.infer("I don't want to listen to music anymore.").sub_intent == "stop"
	assert engine.infer("Why is the music not playing?").sub_intent == "general_question"
	assert engine.infer("I was listening to music yesterday.").sub_intent == "general_request"
	# "What is music?" can be general_question or browser search (both acceptable)
	result = engine.infer("What is music?")
	assert result.sub_intent in ("general_question", "search")


def test_music_control_priority_and_cancellation():
	engine = IntentEngine()
	# New intent format uses simpler sub_intents
	assert engine.infer("Pause that.").sub_intent == "pause"
	assert engine.infer("Resume the music.").sub_intent == "resume"
	assert engine.infer("Stop playing.").sub_intent == "stop"
	assert engine.infer("Never mind.").sub_intent == "cancel"
	assert engine.infer("Turn that off.", ["Assistant: Playing relaxed music."]).sub_intent == "stop"
	assert engine.infer("Turn that off.").sub_intent == "general_request"


def test_explicit_user_facts_are_persisted_but_normal_sentences_are_not(tmp_path):
	store = PreferenceStore(tmp_path / "preferences.json")

	assert store.learn_from_text("My name is Aayush.", explicit=True) == ["name"]
	assert store.learn_from_text("I was listening to music yesterday.", explicit=True) == []
	assert store.snapshot()["user_facts"] == {"name": "Aayush"}