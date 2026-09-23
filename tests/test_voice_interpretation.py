from voice.interpretation import TranscriptInterpreter, TranscriptQuality


def test_high_confidence_transcript_is_kept():
    interpreter = TranscriptInterpreter()
    quality = interpreter.assess_quality("Can you hear me?")
    assert quality.label == TranscriptQuality.HIGH
    assert quality.confidence >= 0.8


def test_medium_confidence_transcript_corrects_common_errors():
    interpreter = TranscriptInterpreter()
    result = interpreter.interpret("what is you processing time")
    assert result.meaning.lower() == "what is your processing time?"
    assert result.confidence >= 0.5
    assert result.needs_clarification is False


def test_low_confidence_transcript_requests_clarification():
    interpreter = TranscriptInterpreter()
    result = interpreter.interpret("Wi-Fi tell you that I am missing my eggs")
    assert result.needs_clarification is True
    assert "clarify" in result.meaning.lower() or "sorry" in result.meaning.lower() or "did you say" in result.meaning.lower()


def test_wake_word_prefix_is_stripped_before_interpretation():
    interpreter = TranscriptInterpreter()
    result = interpreter.interpret("hey jarvis what time is it")
    assert result.meaning.lower().startswith("what time is it")


def test_leading_filler_words_are_stripped():
    interpreter = TranscriptInterpreter()
    for phrase, expected in [
        ("um uh like what is this", "what is this"),
        ("just play some music", "play some music"),
        ("so what is the weather", "what is the weather"),
        ("ok jarvis, um, can you hear me", "can you hear me"),
    ]:
        assert interpreter._strip_filler(phrase) == expected, phrase


def test_content_words_are_not_stripped():
    interpreter = TranscriptInterpreter()
    assert interpreter._strip_filler("play jazz music") == "play jazz music"
    assert interpreter._strip_filler("open youtube") == "open youtube"


def test_filler_only_input_requests_repeat():
    interpreter = TranscriptInterpreter()
    result = interpreter.interpret("um uh erm")
    assert result.needs_clarification is True
