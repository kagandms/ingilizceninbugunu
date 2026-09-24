import pytest
from config.settings import settings

def test_character_budget_constants():
    assert settings.MAX_POST_CHARS == 470

def test_turkish_character_counting():
    turkish_text = "Çocuğun ışıklı şapkası üzerindeki örme düğmeler."
    # Python len() counts unicode code points
    assert len(turkish_text) == 48
    # UTF-8 encoded bytes
    assert len(turkish_text.encode("utf-8")) > len(turkish_text)

def test_emoji_counting_behavior():
    # Demonstrating Meta API emoji byte counting phenomenon:
    # Python len('🚀') == 1, but UTF-8 bytes == 4.
    emoji_sample = "🚀💡✅❌💬"
    assert len(emoji_sample) == 5
    assert len(emoji_sample.encode("utf-8")) == 18  # Emojis consume multiple bytes

    # Verified test text length
    sample_post = (
        "🇬🇧 Günün İpucu\n\n"
        "İngilizcede 'katılıyorum' derken yapılan en sık hata:\n"
        "❌ I am agree with you\n"
        "✅ I agree with you\n\n"
        "'Agree' zaten bir fiildir, başına am/is/are gelmez.\n\n"
        "💬 Sen bu hatayı daha önce yaptın mı? Yorumlarda belirt!"
    )
    assert len(sample_post) <= settings.MAX_POST_CHARS
