# English in Threads 🇬🇧

Production-oriented autonomous Threads bot designed for Turkish speakers. Delivers daily high-engagement English micro-learning posts (common translation traps, idioms, native vs textbook phrasing, quizzes, and phrasal verbs) with built-in active recall comment hooks.

---

## What It Does

* **Strict Character Budget:** Enforces a hard budget of $\le 470$ characters (leaving safety margin under Threads' 500-char limit).
* **Facts vs. Voice Architecture:** Immutable core English expressions and rules are strictly verified via deterministic code checks; LLM generates only tone, hook, and engaging call-to-actions.
* **A/B Testing Engine:** Automatically assigns 50% random format (Modern Dark Mode 1080x1350 Typographical Card vs. Pure Text).
* **Graceful Degradation:** If image generation or Cloudinary hosting encounters an issue, automatically degrades to pure TEXT without dropping a post.
* **Smart Token Lifecycle:** Long-lived tokens (60 days) are refreshed automatically after 7 days, avoiding Meta's 24-hour refresh restriction.
* **Double-Post Protection (Idempotency):** Scans `/me/threads` for the last 6 hours before publishing, locking slots atomically.
* **Dead-Man's Switch:** Pings Healthchecks.io on each success; alerts Telegram immediately on unexpected failures.

---

## Project Structure

```text
english_in_threads/
├── .github/
│   └── workflows/
│       └── daily_post.yml         # Scheduled GitHub Actions (09:43 UTC and 17:18 UTC)
├── config/
│   ├── settings.py                # Environment and secret configuration (Pydantic + standalone)
│   └── logger.py                  # Formatted logging with secret masking
├── data/
│   ├── state_store.py             # Turso (libSQL HTTPS) & InMemoryStateStore with atomic locking
│   └── seeds/
│       └── curriculum.json        # Curated seeds with human-verified fallbacks
├── services/
│   ├── threads_service.py         # Meta Threads Graph API (container polling, publish, insights)
│   ├── ai_service.py              # OpenRouter AI (facts enforcement, repair prompt, fallback)
│   ├── card_generator.py          # Pillow dark-mode typographic card renderer (1080x1350)
│   ├── image_host_service.py      # Cloudinary CDN uploader & auto-cleaner
│   ├── curriculum_service.py      # Seed selection, cooldown, and yesterday's quiz answer linker
│   └── alert_service.py           # Telegram critical alerts & Healthchecks.io pings
├── tests/
│   ├── test_character_budget.py   # Character counting, Turkish glyphs & emoji byte tests
│   ├── test_state_store.py        # Lock flow & rolling window tests
│   ├── test_threads_service.py    # Threads service unit tests
│   └── test_ai_service.py         # Facts verification & repair tests
├── main.py                        # Unified CLI runner and pipeline orchestrator
├── requirements.txt               # Dependencies
├── PROJECT_PLAN.md                # Engineering architecture and roadmap
└── README.md
```

---

## Quick Start

### 1. Environment Setup
```bash
cp .env.example .env
# Fill in your THREADS_ACCESS_TOKEN, THREADS_USER_ID, OPENROUTER_API_KEY, etc.
```

### 2. Local Simulation (In-Memory State)
```bash
python3 main.py --use-in-memory
```

### 3. Production Run (Turso State)
```bash
python3 main.py
```

### 4. Manual Slot Override
```bash
python3 main.py --slot 2026-09-24_LUNCH
```

---

## Daily Schedule (Europe/Istanbul)

| Slot | Time (TSI) | UTC Time | Focus |
| :--- | :--- | :--- | :--- |
| **Lunch** | **12:43** | **09:43** | Bite-sized rule, false friends, prepositions, phrasal verbs |
| **Evening** | **20:18** | **17:18** | High-engagement interactive challenge, quiz, or level-up |
