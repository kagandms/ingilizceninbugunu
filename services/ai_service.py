import json
import re
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, Tuple, List
try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self):
            return self.__dict__
    def Field(default=None, **kwargs):
        return default

from config.settings import settings
from config.logger import logger


class GeneratedPost(BaseModel):
    hook: str
    explanation: str
    examples: str
    cta: str
    raw_full_text: str
    is_fallback: bool = False
    source_model: str = "seed_fallback"


class AIService:
    """
    AI Content Engine enforcing strict Facts vs. Voice separation,
    active recall comment challenges, colorful emojis, and deterministic verification.
    """

    FORBIDDEN_CLICKBAIT_PATTERNS = [
        r"%\s*\d+",                   # e.g. %90, % 99
        r"yüzde\s*\d+",                # e.g. yüzde 90
        r"kimse\s+bilm(ez|iyor)",      # e.g. kimse bilmez
        r"şok\s+olacak",               # e.g. şok olacaksınız
        r"inanılmaz\s+taktik",         # clickbait phrases
    ]

    FORBIDDEN_RAW_KEYS = [
        "correct_english:", "wrong_english:", "example_sentence:",
        "basic_english:", "advanced_english:", "rule:",
        "correct_english :", "example_sentence :"
    ]

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY.get_secret_value()
        self.url = "https://openrouter.ai/api/v1/chat/completions"
        self.models = [
            settings.AI_MODEL,
            settings.BACKUP_MODEL,
            settings.TERTIARY_MODEL,
        ]

    def _call_openrouter(self, messages: List[Dict[str, str]], model: str, temperature: float = 0.4) -> Optional[str]:
        """Calls OpenRouter Chat Completions API with JSON output mode."""
        if not self.api_key:
            logger.warning("No OpenRouter API key configured. Cannot call AI model.")
            return None

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "max_tokens": 600,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/english_in_threads",
            "X-Title": "English in Threads Bot",
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                if resp.status == 200:
                    res = json.loads(resp.read().decode("utf-8"))
                    choices = res.get("choices", [])
                    if choices:
                        return choices[0]["message"]["content"].strip()
                else:
                    logger.warning(f"OpenRouter returned HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"OpenRouter exception on {model}: {e}")
        return None

    def _strip_raw_keys(self, text: str) -> str:
        """Safety layer: Strips any accidental raw JSON keys from text."""
        cleaned = text
        for k in self.FORBIDDEN_RAW_KEYS:
            cleaned = re.sub(re.escape(k), "", cleaned, flags=re.IGNORECASE)
        # Clean extra leading spaces on lines
        lines = [line.strip() for line in cleaned.split("\n")]
        return "\n".join(lines).strip()

    def _validate_facts_in_output(self, text: str, facts: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Deterministic Verification:
        Ensures that core English expressions from facts appear verbatim (case-insensitive) in the output.
        """
        text_lower = text.lower()

        # Check required fields
        for field in ["correct_english", "question", "basic_english", "advanced_english"]:
            val = facts.get(field)
            if val and isinstance(val, str):
                target = val.strip().lower()
                if "," in target:
                    parts = [p.strip() for p in target.split(",") if p.strip()]
                    matched_parts = sum(1 for p in parts if p in text_lower)
                    if matched_parts < len(parts) // 2 + 1:
                        return False, f"Facts ifadesi metinde eksik: '{val}'"
                else:
                    if target not in text_lower:
                        return False, f"Facts zorunlu ifadesi eksik: '{val}'"

        return True, "OK"

    def _validate_post_integrity(self, full_text: str, facts: Dict[str, Any]) -> Tuple[bool, str]:
        """Validates all strict constraints on full combined text."""
        total_len = len(full_text)
        if total_len > settings.MAX_POST_CHARS:
            return False, f"Metin uzunluğu {total_len} karakter, sınırı aştı (maks {settings.MAX_POST_CHARS})."

        if total_len < 100:
            return False, f"Metin çok kısa ({total_len} karakter)."

        for pattern in self.FORBIDDEN_CLICKBAIT_PATTERNS:
            if re.search(pattern, full_text, flags=re.IGNORECASE):
                return False, f"Yasaklı sahte istatistik veya clickbait kalıbı tespit edildi: '{pattern}'"

        # Check that raw JSON keys were not printed
        for k in self.FORBIDDEN_RAW_KEYS:
            if k in full_text.lower():
                return False, f"Teknik JSON anahtarı metne basılmış: '{k}'"

        facts_ok, facts_msg = self._validate_facts_in_output(full_text, facts)
        if not facts_ok:
            return False, facts_msg

        return True, "OK"

    def _build_system_prompt(self, is_thursday: bool = False, max_allowed_chars: int = 470) -> str:
        base_prompt = (
            "Sen Threads platformunda Türkçe konuşanlara hap bilgiler veren, enerjik, samimi ve ETKİLEŞİM AVCISI bir İngilizce eğitmenisin.\n"
            "GÖREVİN: Sana verilen dil kuralını ve İngilizce ifadeleri (facts) kullanarak CANLI, RENKLİ, EMOJİLİ ve DOĞRUDAN ALIŞTIRMA YAPTIRAN bir mikro-öğrenme gönderisi üretmektir.\n\n"
            "ÇOK ÖNEMLİ KURALLAR:\n"
            "1. ASLA VE ASLA 'correct_english:', 'wrong_english:', 'example_sentence:' gibi teknik JSON anahtar kelimelerini metne yazma! İfadeleri doğrudan ve doğal bir şekilde yaz.\n"
            "2. GÖRSEL DÜZEN & EMOJİLER: Gönderiyi sıkıcı düz metin olmaktan kurtar. Karşılaştırmalarda '❌' ve '✅' kullan. Örnek cümlenin başına '📌 Örnek:' veya '🗣️' koy. Açıklamada '💡' kullan.\n"
            "3. AKTİF ALIŞTIRMA ÇAĞRISI (CTA - En Kritik Kısım):\n"
            "   Takipçiye soyut genel kültür veya hayat sorusu sormak KESİNLİKLE YASAKTIR ('Senin hayalin ne?' gibi sorular sorma!).\n"
            "   Kullanıcıya ÖĞRETİLEN İNGİLİZCE KALIBI / KELİMEYİ YORUMLARDA KULLANDIRTACAK BİR MEYDAN OKUMA veya TEST görevi ver!\n"
            "   Mükemmel CTA Örnekleri:\n"
            "   - '✍️ Hadi test: Bu kalıpla 1 cümle kur, bakalım kimler hatasız yazacak? Doğruları yorumlarda kontrol edelim!'\n"
            "   - '🎯 Sıra sende! Cümleyi tamamla: \"I will never give up on ______.\" İngilizce cevabını yoruma yaz!'\n"
            "   - '🔥 Kendini test et: \"give up on\" kullanarak bugün pes etmediğin bir şeyi İngilizce yaz, düzeltelim!'\n"
            "4. FACTS ZORUNLULUĞU: 'correct_english' veya 'example_sentence' içindeki İngilizce ifadeler metinde EKSİKSİZ VE BİREBİR geçmelidir.\n"
            "5. Sahte istatistikler (%90 hata vb.) ve clickbait ASLA KULLANMA.\n"
            f"6. BİRLEŞTİRİLMİŞ TÜM METİN TOPLAMDA KESİNLİKLE {max_allowed_chars} KARAKTERİ AŞAMAZ.\n"
            "7. Sadece ve sadece belirtilen JSON formatında yanıt ver.\n\n"
            "JSON ÇIKTI FORMATI:\n"
            "{\n"
            "  \"hook\": \"Vurucu, dikkat çekici giriş (emojili, maks 75 karakter)\",\n"
            "  \"explanation\": \"Kuralın kısa, net ve samimi açıklaması (💡 emojili, maks 160 karakter)\",\n"
            "  \"examples\": \"Doğru/yanlış veya örnek cümleler (❌/✅/📌 emojili, maks 150 karakter)\",\n"
            "  \"cta\": \"Kullanıcıya o kalıpla İngilizce pratik yaptıran net meydan okuma (✍️/🎯 emojili, maks 85 karakter)\"\n"
            "}"
        )
        return base_prompt

    def generate_post_for_seed(
        self,
        seed: Dict[str, Any],
        yesterday_quiz_answer: Optional[str] = None
    ) -> GeneratedPost:
        """
        Generates a validated post for the given seed.
        If AI fails, times out, or produces invalid output, returns verified_fallback.
        """
        facts = seed.get("facts", {})
        fallback_text = seed.get("verified_fallback", "")

        prefix_header = ""
        if yesterday_quiz_answer:
            prefix_header = f"💡 Dünün Quiz Cevabı: {yesterday_quiz_answer}\n\n"

        max_gen_chars = settings.MAX_POST_CHARS - len(prefix_header)

        system_prompt = self._build_system_prompt(
            is_thursday=bool(yesterday_quiz_answer),
            max_allowed_chars=max_gen_chars
        )
        user_prompt = (
            f"Kategori: {seed.get('slot_type')}\n"
            f"Anahtar Terim: {seed.get('key_term')}\n"
            f"Değiştirilemez Gerçekler (Facts): {json.dumps(facts, ensure_ascii=False)}\n\n"
            f"Yukarıdaki gerçekleri kullanarak renkli, emojili ve yorumlarda İngilizce alıştırma yaptıran JSON post üret."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for model in self.models:
            raw_json = self._call_openrouter(messages, model=model)
            if not raw_json:
                continue

            try:
                parsed = json.loads(raw_json)
                hook = self._strip_raw_keys(parsed.get("hook", "").strip())
                explanation = self._strip_raw_keys(parsed.get("explanation", "").strip())
                examples = self._strip_raw_keys(parsed.get("examples", "").strip())
                cta = self._strip_raw_keys(parsed.get("cta", "").strip())

                candidate_body = f"{hook}\n\n{explanation}\n\n{examples}\n\n{cta}"
                full_post_text = f"{prefix_header}{candidate_body}".strip()

                valid, reason = self._validate_post_integrity(full_post_text, facts)
                if valid:
                    logger.info(f"✅ AI Post successfully generated and verified ({model}). Length: {len(full_post_text)}")
                    return GeneratedPost(
                        hook=hook,
                        explanation=explanation,
                        examples=examples,
                        cta=cta,
                        raw_full_text=full_post_text,
                        is_fallback=False,
                        source_model=model
                    )

                logger.warning(f"⚠️ Validation failed ({model}): {reason}. Triggering repair prompt...")

                # Single Repair Attempt
                repair_messages = list(messages)
                repair_messages.append({"role": "assistant", "content": raw_json})
                repair_messages.append({
                    "role": "user",
                    "content": f"HATA TESPİT EDİLDİ: {reason}\nLütfen hatayı düzelterek, teknik JSON anahtarlarını metne basmadan, emojili ve alıştırma yaptıran formatta {max_gen_chars} karakter altında yeniden üret."
                })

                repaired_json = self._call_openrouter(repair_messages, model=model, temperature=0.2)
                if repaired_json:
                    parsed_rep = json.loads(repaired_json)
                    r_hook = self._strip_raw_keys(parsed_rep.get("hook", "").strip())
                    r_explanation = self._strip_raw_keys(parsed_rep.get("explanation", "").strip())
                    r_examples = self._strip_raw_keys(parsed_rep.get("examples", "").strip())
                    r_cta = self._strip_raw_keys(parsed_rep.get("cta", "").strip())

                    r_body = f"{r_hook}\n\n{r_explanation}\n\n{r_examples}\n\n{r_cta}"
                    r_full = f"{prefix_header}{r_body}".strip()

                    r_valid, r_reason = self._validate_post_integrity(r_full, facts)
                    if r_valid:
                        logger.info(f"✅ AI Post repaired successfully ({model}). Length: {len(r_full)}")
                        return GeneratedPost(
                            hook=r_hook,
                            explanation=r_explanation,
                            examples=r_examples,
                            cta=r_cta,
                            raw_full_text=r_full,
                            is_fallback=False,
                            source_model=f"{model}-repaired"
                        )
                    else:
                        logger.warning(f"⚠️ Repair attempt failed ({model}): {r_reason}")

            except Exception as e:
                logger.warning(f"Failed to parse JSON from {model}: {e}")
                continue

        # Verified fallback
        logger.warning(f"🛡️ Activating verified human fallback for Seed #{seed.get('seed_id')}.")
        final_fallback = f"{prefix_header}{fallback_text}".strip()

        if len(final_fallback) > settings.MAX_POST_CHARS:
            final_fallback = final_fallback[:settings.MAX_POST_CHARS]

        return GeneratedPost(
            hook="",
            explanation=final_fallback,
            examples="",
            cta="",
            raw_full_text=final_fallback,
            is_fallback=True,
            source_model="human_verified_fallback"
        )


ai_service = AIService()
