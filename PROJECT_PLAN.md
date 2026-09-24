# English in Threads – Mimari ve Geliştirme Planı (v2.1 - Production-Grade)

Bu belge, **English in Threads** botunun sistem mimarisini, veri modelini, hata toleransını, içerik doğruluk güvencesini ve aşamalı geliştirme yol haritasını tanımlar.

---

## 0. Genel Mühendislik ve Operasyon İlkeleri

1. **Varsayım Yok:** Meta API davranışları hakkında varsayım yapılmaz. "Doğrula" işaretli her madde güncel resmi Meta Graph API dokümantasyonundan veya sandbox test çağrısıyla doğrulanır.
2. **Sıfır Sızıntı (Zero Secret Leak):** Token, API anahtarı ve secret'lar hiçbir koşulda log'a, GitHub reposuna, hata mesajına veya state veri tabanına düz metin (unmasked) yazılmaz.
3. **Kademeli İlerleme:** Her aşama sonunda kabul kriterleri doğrulanmadan bir sonraki aşamaya geçilmez.

---

## 1. Temel Standartlar ve Karakter Bütçesi

* **Platform:** Yalnızca **Meta Threads**. Platformun sert sınırı 500 karakterdir.
* **Maksimum Karakter Sınırı:**
  $$\text{MAX\_POST\_CHARS} = 470$$
  * Ayırıcılar (`\n\n`) dahil birleştirilmiş tam metin ($\text{len}(\text{full\_text}) \le 470$) kesin kuraldır.
  * Pydantic şemasındaki alan sınırları LLM'e yol gösterici yumuşak sınırlardır. Asıl denetim tam metin üzerinde yapılır.
  * 470 karakter kuralı ihlal edilirse LLM'e 1 kez `repair_prompt` gönderilir. İkinci ihlalde doğrudan `verified_fallback` devreye girer.
  * `verified_fallback` metninin kendisi de $\le 470$ karakter olmak zorundadır (CI lint denetimiyle garanti edilir).

---

## 2. Durum Yönetimi (StateStore) ve Idempotency

### 2.1 State Backend: Turso (libSQL)
Geçici GitHub Actions runner'ları nedeniyle yerel SQLite kullanılmaz. Git reposu yalnızca kod ve müfredat içindir; durum verisi repoya geri commit edilmez.
Durum saklama katmanı olarak **Turso (Serverless SQLite over HTTPS)** kullanılır. Test ortamları için ise bellek içi (In-Memory) fake backend bulunur.

**Turso Veri Şeması (`state` tablosu / JSON nesnesi):**
* `token_data`: `access_token` (şifrelenmiş/güvenli saklama), `last_token_refresh` (ISO8601).
* `pending_execution`: `slot_key`, `started_at`, `payload_hash`, `status` (PENDING/COMPLETED/FAILED).
* `used_seed_ids`: Kullanılan tohum ID listesi ve son kullanılma tarihi (60 günlük cooldown takibi için).
* `weekly_key_terms`: Hafta içi paylaşılan terimlerin listesi (Pazar özeti için).
* `recent_posts`: Son 60 günlük kayan pencere (gönderi ID, slot anahtarı, format ataması, insights metrikleri). 60 günü aşan kayıtlar haftalık özet istatistiğine indirgenir.

### 2.2 Idempotency (Çift Gönderi Engeli)
* **Slot Anahtarı (`slot_key`):** `YYYY-MM-DD_{LUNCH|EVENING}` (hesaplama strictly `Europe/Istanbul` saat dilimine göredir).
* **Akış:**
  1. Run başında Meta Threads API (`/me/threads`) sorgulanarak son 6 saatte bu slotta yayınlanmış gönderi olup olmadığı taranır.
  2. Eğer bu slot için gönderi Threads'te zaten mevcutsa işlem **atlanır** ve yerel durum Threads'teki gerçek duruma göre onarılır.
  3. Gönderi hazırlığı tamamlandığında, API çağrısından **önce** Turso'ya atomik `pending_execution` yazılır.
  4. Başarılı yayından sonra durum `COMPLETED` olarak güncellenir ve slot kapatılır.

### 2.3 Token Rotasyonu Kuralı
* Meta Graph API dokümantasyonu doğrulaması: Long-lived token'lar yalnızca **en az 24 saat** yaşındaysa yenilenebilir.
* **Yenileme Mantığı:** Her çalıştırmada yenileme denenmez. `last_token_refresh` yaşı **$\ge 7$ gün** ise `refresh_access_token` çağrılır ve Turso güncellenir.
* Yenileme başarısız olursa derhal Telegram kritik alarmı fırlatılır.

### 2.4 Dead-Man's Switch (Healthchecks.io)
* Her başarılı yayın döngüsünün sonunda Healthchecks.io endpoint'ine ping gönderilir.
* Eğer **26 saat** boyunca ping ulaşmazsa Healthchecks.io tarafından doğrudan Telegram acil bildirim kanalına uyarı gönderilir. Bu, GitHub Actions workflow failure bildiriminin yanında çalışan harici güvencedir.

---

## 3. İçerik ve Doğruluk Mimarisi (Facts vs. Voice Ayrımı)

Eğitim hesabında dilbilgisi veya kullanım hatası kabul edilemez. Bu nedenle içerik üretimi ikiye ayrılır:

```text
[Müfredat Tohumu (curriculum.json)]
  └── facts: Değiştirilemez kural, İngilizce örnekler, Türkçe karşılıklar (İnsan Onaylı)
        │
        ▼
[LLM (OpenRouter)] ────► Yalnızca: Kanca (Hook), Samimi Ton, Yorum Çağrısı (CTA)
        │
        ▼
[Deterministik Kod Denetimi]
  ├── facts içindeki tüm İngilizce ifadeler çıktıda BİREBİR geçiyor mu? (Geçmiyorsa RED)
  ├── len(full_text) <= 470 kuralı sağlandı mı? (Aşıyorsa 1 repair, olmazsa FALLBACK)
  └── Sahte istatistik / clickbait var mı? (Varsa RED)
        │
        ▼
[Yayın / Fallback] ────► Hata anında doğrudan seed.verified_fallback devreye girer.
```

### 3.1 Müfredat Tohumu Şeması (`curriculum.json`)
```json
{
  "seed_id": 101,
  "slot_type": "LUNCH_COMMON_MISTAKE",
  "key_term": "agree with",
  "facts": {
    "rule": "'agree' zaten fiildir, 'am agree' denmez.",
    "correct_english": "I agree with you",
    "wrong_english": "I am agree with you",
    "example_sentence": "I completely agree with your proposal."
  },
  "verified_fallback": "❌ I am agree with you\n✅ I agree with you\n\n'Agree' zaten bir fiil olduğu için başına 'am/is/are' getirmiyoruz. 'Sana katılıyorum' derken doğrudan 'I agree with you' demelisin.\n\nSıra sende: Bu kalıpla bugün katıldığın bir fikri yoruma yaz!",
  "verified_at": "2026-09-24T12:00:00Z",
  "verified_by": "human_reviewer"
}
```

### 3.2 Bağımlı İçerikler (Çarşamba Quiz ➔ Perşembe Cevap)
* **Çarşamba Akşam:** 3 seçenekli Quiz (Doğru cevap tohum içinde belirlidir).
* **Perşembe Öğle:** Ayrı bir şema varyantı kullanılır:
  $$\text{Post} = [\text{Dünün Quiz Cevabı Satırı}] + [\text{Günün Phrasal Verb Paylaşımı}]$$
  * Dünün doğru cevabı AI tarafından üretilmez; Çarşamba günkü tohum verisinden **deterministik** olarak çekilir.
  * Eğer `recent_posts` içinde Çarşamba gününe ait geçerli bir quiz kaydı bulunamazsa, Perşembe gönderisi cevap satırı olmadan bağımsız bir phrasal verb postu olarak yayınlanır.
* **Pazar Özeti:** Hafta boyunca paylaşılan tohumların `key_term` alanları Turso'daki `weekly_key_terms` listesinden derlenerek tek bir özet gönderide toplanır.
* **Pazar CTA Kuralı:** İnsanları yanıltıcı "yarın öne çıkaralım" vaadi ilk 4 hafta boyunca sistemden ve CTA metinlerinden tamamen kaldırılmıştır. Sade, kişisel cümle kurmaya teşvik eden bir CTA kullanılır.

---

## 4. Deney Tasarımı ve A/B Testi

Görsel kartın metin gönderisine göre daha fazla yorum getirdiği varsayımı doğrudan test edilecektir:

* **Format Ataması (`format_assignment`):** Gönderi formatı (Görsel Kart vs. Sadece Metin), gün ve içerik tipinden bağımsız olarak **%50 rastgele** atanır.
* **Metrik:** Birincil başarı metriği:
  $$\text{Engagement Rate} = \frac{\text{Replies}}{\text{Views}}$$
* **Karar Eşiği:** Kol başına (Görsel vs. Metin) en az **25'er gönderi** (toplam 50 gönderi $\approx$ 25 gün) tamamlanmadan format stratejisi değiştirilmez. 25 gönderi sonunda iki grup arasında istatistiksel anlamlı fark oluşursa kazanan formatın ağırlığı artırılır.
* **Insights Toplama:** Her çalıştırma başında 24 saatten eski ve henüz metrikleri çekilmemiş gönderiler için `threads_manage_insights` çağrılır. Bu çağrı **best-effort** çalışır; API hatası yayını kesinlikle durdurmaz, düşük seviyeli log üretir.

---

## 5. Görsel Motoru ve Cloudinary

* **Pillow Kart Tasarımı:** 1080x1350 (4:5 dikey) veya 1080x1080. Yüksek kontrastlı koyu tema.
* **Yazı Bütünlüğü:** Metin uzunluğuna göre dinamik font ölçekleme (auto-shrink) ve kelime sarma (text-wrap). Inter fontu kullanılır. CI testinde Türkçe karakter (İ, ı, ş, ğ, ü, ö, ç) golden-image testi koşulur.
* **Erişilebilirlik:** Her görsel için Threads API'ye `alt_text` zorunlu geçilir.
* **Geçici Barındırma:** Görsel Cloudinary'ye yüklenir. Threads container durumu `FINISHED` olduğunda Cloudinary'deki görsel silinerek kota tasarrufu sağlanır.
* **Zarif Düşüş (Graceful Degradation):** Kart üretimi veya CDN yüklemesi başarısız olursa sistem hiçbir şey olmamış gibi **SADECE METİN (TEXT)** moduna geçerek yayını tamamlar.

---

## 6. Operasyonel Zamanlama ve Cron Politikası

* **Saat Dilimi:** Strictly `Europe/Istanbul`.
* **Zamanlama (GitHub Actions UTC):**
  * Öğle Slotu: 12:43 TSI = **09:43 UTC**
  * Akşam Slotu: 20:18 TSI = **17:18 UTC**
  *(Meta ve GitHub yük dalgalanmalarından kaçınmak için tam saat başlarından kaçınılmış, dakikalar rastgele belirlenmiştir).*
* **Jitter:** Workflow başında rastgele 1–5 dakika bekleme (jitter) eklenerek bot izlenimi azaltılır.
* **Kaçırılan Slot Politikası:** Geciken veya kaçırılan slot telafi edilmez; bir sonraki slota geçilir ve uyarı logu düşülür.
* **Manuel Tetikleme:** `workflow_dispatch` üzerinden `slot` parametresi verilerek acil/manuel paylaşım desteklenir.
* **Eşzamanlılık Koruması:** `concurrency` grubu ile aynı anda birden fazla runner'ın çalışması kesin olarak engellenir.

---

## 7. CI / Test Mimarisi (`tests/`)\n\nRepository içinde testler mevcuttur:\n- Seed Linting (`curriculum.json` alan ve karakter bütçesi kontrolü)\n- Karakter Bütçesi ve Türkçe karakter sayım testleri (`test_character_budget.py`)\n- AI Facts/Voice ve tamir döngüsü testleri (`test_ai_service.py`)\n- StateStore atomik kilit ve 60 günlük kayan pencere testleri (`test_state_store.py`)\n- Threads API container ve token yenileme testleri (`test_threads_service.py`)

---

## 8. Uygulama Yol Haritası

- [x] **Aşama 1: İnce Dikey Dilim (Tracer Bullet) — TAMAMLANDI**
  * Meta Developer App & Threads API izinleri (`threads_basic`, `threads_content_publish`, `threads_manage_insights`).
  * `config/settings.py` (env/secret yönetimi).
  * `data/state_store.py` (StateStore arayüzü, Turso backend ve In-Memory fake).
  * `services/threads_service.py` (metin yayınlama, son gönderi sorgulama, token yenileme).
  * İlk canlı test postu (@ingilizceninbugunu) başarıyla atıldı ve idempotency doğrulandı.
- [x] **Aşama 2: Doğruluk Garantili AI Motoru & Tohum Havuzu — TAMAMLANDI**
  * `data/seeds/curriculum.json` (15 zengin tohum, verified fallback <= 470 karakter).
  * `services/ai_service.py` (facts/voice ayrımı, deterministik denetim, repair döngüsü).
  * Perşembe quiz cevap varyantı ve Pazar kelime takibi.
- [x] **Aşama 3: Görsel Motoru & Cloudinary Entegrasyonu — TAMAMLANDI**
  * `services/card_generator.py` (Pillow 1080x1350 koyu tema tipografik kart, text-wrap).
  * `services/image_host_service.py` (Cloudinary upload ve yayın sonrası otomatik silme).
  * Görsel ➔ Metin graceful fallback garantisi.
- [x] **Aşama 4: Insights Toplama & A/B Test Altyapısı — TAMAMLANDI**
  * `services/threads_service.py` içinde `get_post_insights` (best-effort metrik okuma).
  * %50 rastgele format ataması (CARD_IMAGE vs TEXT_ONLY).
- [x] **Aşama 5: GitHub Actions ve Canlı Dağıtım — TAMAMLANDI**
  * `.github/workflows/daily_post.yml` (09:43 UTC öğle ve 17:18 UTC akşam zamanlayıcıları, concurrency kilidi, failure alert).
