import json
try:
    import pytest
except ImportError:
    pass
from services.ai_service import ai_service, AIService
from config.settings import settings


def test_facts_validation_positive():
    facts = {
        "rule": "'agree' fiildir.",
        "correct_english": "I agree with you",
        "example_sentence": "I completely agree with your proposal."
    }
    sample_text = (
        "Türkçe düşünüp konuşurken en sık yapılan hata:\n\n"
        "❌ I am agree with you\n"
        "✅ I agree with you\n\n"
        "'Agree' zaten fiildir, başına am/is gelmez.\n\n"
        "Sen bu hatayı yaptın mı? Yoruma yaz!"
    )
    valid, msg = ai_service._validate_facts_in_output(sample_text, facts)
    assert valid is True
    assert msg == "OK"


def test_facts_validation_missing_english():
    facts = {
        "correct_english": "It depends on the weather",
    }
    # Deliberately omit the correct expression
    flawed_text = "Hava durumuna göre değişir demek için depend kelimesini kullanırız."
    valid, msg = ai_service._validate_facts_in_output(flawed_text, facts)
    assert valid is False
    assert "eksik" in msg


def test_character_limit_rejection():
    facts = {"correct_english": "test"}
    oversized_text = "test " + ("a" * (settings.MAX_POST_CHARS + 10))
    valid, msg = ai_service._validate_post_integrity(oversized_text, facts)
    assert valid is False
    assert "sınırı aştı" in msg


def test_fake_statistics_rejection():
    facts = {"correct_english": "I agree with you"}
    clickbait_text = "İnsanların %90'ının yaptığı o büyük hata: I agree with you!"
    valid, msg = ai_service._validate_post_integrity(clickbait_text, facts)
    assert valid is False
    assert "Yasaklı" in msg


def test_fallback_activation_when_no_api_key():
    seed = {
        "seed_id": 999,
        "slot_type": "LUNCH_COMMON_MISTAKE",
        "key_term": "test term",
        "facts": {"correct_english": "I agree with you"},
        "verified_fallback": "✅ I agree with you\n\nBu insan onaylı güvenli test fallback metnidir.",
        "verified_at": "2026-09-24T12:00:00Z",
        "verified_by": "curator"
    }

    # Temporarily instantiate service with dummy empty key
    dummy_service = AIService()
    dummy_service.api_key = ""

    result = dummy_service.generate_post_for_seed(seed)
    assert result.is_fallback is True
    assert result.source_model == "human_verified_fallback"
    assert "I agree with you" in result.raw_full_text
    assert len(result.raw_full_text) <= settings.MAX_POST_CHARS


def test_thursday_prefix_length_accounting():
    seed = {
        "seed_id": 999,
        "slot_type": "LUNCH_PHRASAL_VERB",
        "key_term": "call off",
        "facts": {"correct_english": "call off the meeting"},
        "verified_fallback": "Günün kalıbı: call off the meeting.",
        "verified_at": "2026-09-24T12:00:00Z",
        "verified_by": "curator"
    }

    dummy_service = AIService()
    dummy_service.api_key = ""

    result = dummy_service.generate_post_for_seed(seed, yesterday_quiz_answer="C) in the morning")
    assert "Dünün Quiz Cevabı: C) in the morning" in result.raw_full_text
    assert len(result.raw_full_text) <= settings.MAX_POST_CHARS
