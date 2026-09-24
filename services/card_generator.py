import os
import textwrap
from typing import Optional, Dict, Any, Tuple
from config.logger import logger

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


class CardGenerator:
    """
    Renders high-contrast, modern dark-mode typographic cards (1080x1350 - 4:5 vertical)
    for Threads. Supports automatic text-wrapping, font scaling, and graceful degradation.
    """

    WIDTH = 1080
    HEIGHT = 1350
    BG_COLOR = (13, 17, 23)        # Deep GitHub/Terminal Dark
    CARD_BG = (22, 27, 34)         # Card surface
    ACCENT_YELLOW = (249, 232, 88) # Thumb-stopper Yellow
    ACCENT_CYAN = (56, 189, 248)   # Calm Cyan
    TEXT_WHITE = (240, 246, 252)   # High-contrast White
    TEXT_MUTED = (139, 148, 158)   # Secondary Muted Gray
    RED_WRONG = (239, 68, 68)      # ❌ Error Red
    GREEN_RIGHT = (34, 197, 94)    # ✅ Success Green
    BORDER_COLOR = (48, 54, 61)    # Subtle card border

    def __init__(self, output_dir: str = "temp_cards"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.font_path = self._find_system_font()

    def _find_system_font(self) -> Optional[str]:
        """Finds a clean readable sans-serif font on macOS/Linux."""
        candidates = [
            "/System/Library/Fonts/SFPro.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _get_font(self, size: int):
        if not HAS_PILLOW:
            return None
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def generate_card(self, seed: Dict[str, Any]) -> Optional[str]:
        """
        Generates an image card based on seed facts.
        Returns the absolute local file path of the generated PNG, or None if failed.
        """
        if not HAS_PILLOW:
            logger.warning("Pillow is not installed. Skipping card generation (falling back to text).")
            return None

        slot_type = seed.get("slot_type", "")
        facts = seed.get("facts", {})
        seed_id = seed.get("seed_id", "temp")

        out_path = os.path.join(self.output_dir, f"card_seed_{seed_id}.png")

        try:
            img = Image.new("RGB", (self.WIDTH, self.HEIGHT), color=self.BG_COLOR)
            draw = ImageDraw.Draw(img)

            # Draw outer container card with rounded rectangle
            margin = 60
            draw.rounded_rectangle(
                [margin, margin, self.WIDTH - margin, self.HEIGHT - margin],
                radius=32,
                fill=self.CARD_BG,
                outline=self.BORDER_COLOR,
                width=3
            )

            # Header brand line
            brand_font = self._get_font(36)
            draw.text((margin + 50, margin + 50), "🇬🇧 ENGLISH IN THREADS", font=brand_font, fill=self.ACCENT_CYAN)

            # Route by content type
            if "COMMON_MISTAKE" in slot_type:
                self._draw_mistake_card(draw, facts, margin)
            elif "QUIZ" in slot_type:
                self._draw_quiz_card(draw, facts, margin)
            elif "LEVEL_UP" in slot_type:
                self._draw_level_up_card(draw, facts, margin)
            else:
                self._draw_standard_phrase_card(draw, facts, seed.get("key_term", ""), margin)

            # Footer CTA prompt
            footer_font = self._get_font(32)
            draw.text(
                (margin + 50, self.HEIGHT - margin - 80),
                "💬 Doğrusunu ve cümleni yorumlara yaz!",
                font=footer_font,
                fill=self.ACCENT_YELLOW
            )

            img.save(out_path, format="PNG", optimize=True)
            logger.info(f"✅ Typographic card generated: {out_path}")
            return os.path.abspath(out_path)

        except Exception as e:
            logger.error(f"Failed to generate card for seed {seed_id}: {e}")
            return None

    def _draw_mistake_card(self, draw: Any, facts: Dict[str, Any], margin: int):
        title_font = self._get_font(48)
        content_font = self._get_font(52)
        rule_font = self._get_font(36)

        y = margin + 160
        draw.text((margin + 50, y), "SIK YAPILAN ÇEVİRİ HATASI", font=title_font, fill=self.TEXT_MUTED)

        # ❌ Wrong Box
        y += 100
        wrong_text = facts.get("wrong_english", "")
        draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 150], radius=20, fill=(45, 20, 24), outline=self.RED_WRONG, width=2)
        draw.text((margin + 80, y + 45), f"❌  {wrong_text}", font=content_font, fill=(254, 202, 202))

        # ✅ Right Box
        y += 200
        right_text = facts.get("correct_english", "")
        draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 150], radius=20, fill=(20, 45, 30), outline=self.GREEN_RIGHT, width=2)
        draw.text((margin + 80, y + 45), f"✅  {right_text}", font=content_font, fill=(187, 247, 208))

        # Rule explanation
        y += 230
        rule_text = facts.get("rule", "")
        wrapped_rule = textwrap.fill(f"Kural: {rule_text}", width=38)
        draw.text((margin + 60, y), wrapped_rule, font=rule_font, fill=self.TEXT_WHITE)

    def _draw_quiz_card(self, draw: Any, facts: Dict[str, Any], margin: int):
        title_font = self._get_font(48)
        q_font = self._get_font(54)
        opt_font = self._get_font(42)

        y = margin + 160
        draw.text((margin + 50, y), "GÜNÜN İNGİLİZCE TESTİ 🧠", font=title_font, fill=self.ACCENT_YELLOW)

        y += 100
        q_text = facts.get("question", "")
        wrapped_q = textwrap.fill(q_text, width=32)
        draw.text((margin + 60, y), wrapped_q, font=q_font, fill=self.TEXT_WHITE)

        # Options
        options = facts.get("options", [])
        y += 280
        for opt in options:
            draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 110], radius=16, fill=(30, 36, 46), outline=self.BORDER_COLOR, width=2)
            draw.text((margin + 80, y + 30), opt, font=opt_font, fill=self.TEXT_WHITE)
            y += 140

    def _draw_level_up_card(self, draw: Any, facts: Dict[str, Any], margin: int):
        title_font = self._get_font(48)
        content_font = self._get_font(54)
        rule_font = self._get_font(36)

        y = margin + 160
        draw.text((margin + 50, y), "SEVİYE DÖNÜŞÜMÜ (A2 ➔ B2)", font=title_font, fill=self.ACCENT_CYAN)

        y += 120
        basic = facts.get("basic_english", "")
        draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 140], radius=18, fill=(30, 36, 46), outline=self.BORDER_COLOR, width=2)
        draw.text((margin + 80, y + 40), f"🔹 A2: {basic}", font=content_font, fill=self.TEXT_MUTED)

        y += 190
        advanced = facts.get("advanced_english", "")
        draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 140], radius=18, fill=(35, 45, 60), outline=self.ACCENT_CYAN, width=2)
        draw.text((margin + 80, y + 40), f"🔸 B2: {advanced}", font=content_font, fill=self.ACCENT_YELLOW)

        y += 220
        rule = facts.get("rule", "")
        wrapped_rule = textwrap.fill(rule, width=38)
        draw.text((margin + 60, y), wrapped_rule, font=rule_font, fill=self.TEXT_WHITE)

    def _draw_standard_phrase_card(self, draw: Any, facts: Dict[str, Any], key_term: str, margin: int):
        title_font = self._get_font(48)
        term_font = self._get_font(68)
        content_font = self._get_font(40)

        y = margin + 180
        draw.text((margin + 50, y), "GÜNÜN KALIBI", font=title_font, fill=self.ACCENT_CYAN)

        y += 100
        draw.text((margin + 50, y), key_term.upper(), font=term_font, fill=self.ACCENT_YELLOW)

        y += 160
        correct = facts.get("correct_english", "")
        if correct:
            draw.rounded_rectangle([margin + 50, y, self.WIDTH - margin - 50, y + 140], radius=18, fill=(20, 45, 30), outline=self.GREEN_RIGHT, width=2)
            draw.text((margin + 80, y + 45), f"✨ {correct}", font=self._get_font(48), fill=self.TEXT_WHITE)
            y += 200

        example = facts.get("example_sentence", "")
        if example:
            wrapped_ex = textwrap.fill(f"Örnek:\n\"{example}\"", width=34)
            draw.text((margin + 60, y), wrapped_ex, font=content_font, fill=self.TEXT_MUTED)


card_generator = CardGenerator()
