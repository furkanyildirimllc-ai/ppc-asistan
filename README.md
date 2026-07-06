# PPC Asistan

Amazon Sponsored Products reklamları için AI destekli optimizasyon aracı.
Rapor yükle → analiz + öneri al → onaylıları Amazon'a uygula.

## Öne çıkan özellikler

- **Deterministik motor**: harvest, negatif, bid optimizasyonu, placement (Ad Badger / AdLabs formülleri)
- **AI Strateji Katmanı** (Claude Sonnet): yeni kampanya planları, kelime grupları, semantik negatifler, bütçe dağılımı
- **Denetçi (Müdür)** (Claude Fable 5): AI çıktısını matematik/policy/format için kontrol eder, "gönderme" diyebilir
- **Uzman Analizler**: SKAG adayları, TOS placement multiplier fırsatı, brand defense boşluğu, kampanya momentum
- **Görsel Dashboard**: sağlık skoru, KPI ribbon, portföy metrikleri, trend/match/kampanya grafikleri
- **AI Chat**: marka context'i ile uzman sohbeti
- **Amazon Bulksheet Export**: onaylıları tek tıkla Amazon Ads Bulk Operations'a yüklenecek formatta
- **Uzman Hint Sistemi**: 25+ pro terim (SKAG, traffic sculpting, TOS IS, bid stacking, dayparting, ranking juice…)

## Kurulum

```bash
python3.14 -m venv .venv
.venv/bin/pip install fastapi uvicorn openpyxl anthropic python-dotenv
cp .env.example .env  # ANTHROPIC_API_KEY doldur
.venv/bin/uvicorn app:app --port 8642
```

`.env` dosyası:
```
ANTHROPIC_API_KEY=sk-ant-...
STRATEGY_MODEL=claude-sonnet-4-6
SUPERVISOR_MODEL=claude-fable-5
```

Sonra `http://localhost:8642` aç.

## Kullanım

1. Marka ekle (ad + hedef ACOS)
2. Amazon Ads Console'dan raporları indir: Search Term, Targeting, Campaign, Placement
3. Drop zone'a sürükle → otomatik analiz
4. Sekmelerde önerileri gez → ✓ ile onayla / ✗ ile reddet
5. **🤖 AI Strateji** ile derin plan al (müdür kontrolünden geçer)
6. **📋 Uygulama Rehberi** ile adım adım Amazon'a uygula
7. **📦 Bulksheet** indir → Amazon Ads Console → Bulk Operations'a yükle

## Mimari

```
Raporlar → analysis.py (matematik) → deterministik öneriler
                ↓
        ai_agent.py (Sonnet + web_search) → strateji JSON
                ↓
        supervisor.py (Fable 5) → onay/uyarı
                ↓
        UI (kırmızı/turuncu/yeşil müdür rozeti)
```

## Dosyalar

- `app.py` — FastAPI endpoint'leri
- `analysis.py` — deterministik öneri motoru
- `parsers.py` — CSV/XLSX rapor okuyucu
- `insights.py` — dashboard metrikleri + pro insights
- `ai_agent.py` — AI strateji üretici (Sonnet)
- `supervisor.py` — denetçi (Fable 5)
- `chat.py` — AI chat sohbet
- `bulksheet.py` — Amazon Bulk Upload xlsx üretici
- `expert_knowledge.py` — 16 bölümlü uzman bilgi bankası (tüm AI prompt'larına inject edilir)
- `static/index.html` — tek dosyalık SPA

## Uzman bilgi

`expert_knowledge.py` içindeki 16 bölüm — sadece 8+ yıl deneyimli Amazon PPC uzmanlarının kullandığı taktikler tüm AI çağrılarına enjekte edilir:

1. Match Type Funnel (Broad → Phrase → Exact) + Traffic Sculpting
2. Placement Multiplier optimizasyonu + Bid Stacking
3. Bidding strategy seçimi (Fixed / Down Only / Up&Down)
4. Negative strategy (exact vs phrase riski, kendi ASIN'ini negatifle)
5. Brand Defense (kendi ASIN'ini kendi ASIN'inle target et)
6. Sponsored Display (Views/Purchase Remarketing)
7. Dayparting (peak 09-12, 19-23)
8. Ranking Juice / Organic Halo
9. Kampanya öğrenme dönemi + bid change cap %25
10. Impression Share sinyalleri
11. SKAG (Single Keyword Ad Group)
12. İdeal 8 katmanlı marka mimarisi
13. SP/SB/SD bütçe dağılımı
14. Troubleshooting (klasik hatalar)
15. Attribution zamanlaması
16. Kârlılık vs ACOS matematiği
