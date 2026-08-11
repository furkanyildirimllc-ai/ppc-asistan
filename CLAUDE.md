# PPC Asistan — proje haritası

Amazon Sponsored Products için AI destekli optimizasyon aracı. FastAPI + vanilla JS + SQLite.
Toplam ~10.700 satır. **Bu dosya, kod okumadan doğru yeri bulmak içindir — önce burayı oku, sonra sadece gereken dosyayı/satır aralığını aç.**

## Çalıştırma

```bash
.venv/bin/uvicorn app:app --port 8642   # http://localhost:8642
```
`.env`: `ANTHROPIC_API_KEY`, `STRATEGY_MODEL`, `SUPERVISOR_MODEL` (config.py okur).

## Akış

```
Excel rapor → parsers.py (normalize) → report_rows tablosu
   ├→ analysis.py    → deterministik öneriler → recommendations tablosu
   ├→ insights.py    → dashboard / sağlık skoru / uzman analizler
   ├→ ai_agent.py    (Sonnet) → strateji JSON
   │      └→ supervisor.py (Fable 5) → onay/uyarı → ai_strategies tablosu
   └→ bulksheet.py   → Amazon Bulk Operations xlsx

Ayrı hat (yeni ürün lansmanı):
  launch.py + competitor_intel.py + market_intel.py + keepa_engine.py
```

## Dosya → sorumluluk (hangi iş nerede)

| Dosya | Satır | Ne zaman aç |
|---|---|---|
| `app.py` | 1228 | Tüm API endpoint'leri, DB init, upload akışı |
| `static/index.html` | 3159 | **Tüm frontend** (HTML+CSS+JS tek dosya) |
| `market_intel.py` | 1103 | Arama terimi vokabüleri, alaka skoru, yabancı marka tespiti, bid matematiği, kampanya planı |
| `insights.py` | 801 | Dashboard, KPI, sağlık skoru, SKAG/TOS/brand-defense, `campaign_advisor` |
| `analysis.py` | 684 | Deterministik motor: harvest, negatif, bid, placement, bütçe |
| `launch.py` | 547 | Yeni ürün lansman planı + lansman bulksheet'i |
| `bulksheet.py` | 541 | Amazon Bulk Operations formatı (kolon sırası kritik) |
| `extension/popup.js` | 471 | Chrome eklentisi UI |
| `parsers.py` | 375 | Excel okuma + rapor tipi tespiti + satır normalizasyonu |
| `competitor_intel.py` | 344 | Rakip analizi, reverse-engineer keyword, pazar fırsatı |
| `extension/content.js` | 294 | Amazon sayfa scraping |
| `supervisor.py` | 234 | AI çıktısı denetimi (heuristik + Fable 5) |
| `ai_agent.py` | 221 | Sonnet strateji çağrısı, payload derleme |
| `brain.py` | 216 | "Bugün ne yapmalı" özet üretici |
| `expert_knowledge.py` | 190 | PPC terim/hint sözlüğü (sadece sabit veri) |
| `chat.py` | 142 | Marka context'li sohbet |
| `keepa_engine.py` | 74 | Keepa ile ilgili ASIN |
| `config.py` | 22 | Env/model sabitleri |

## API uçları (app.py)

Marka: `GET/POST /api/brands`, `PUT/DELETE /api/brands/{id}`
Veri: `POST .../upload`, `GET .../summary`, `.../data-summary`, `.../history`, `POST .../history/undo`
Öneriler: `GET .../recommendations`, `POST .../recommendations/action`, `PUT /api/recommendations/{id}/bid`
AI: `POST .../ai-strategy`, `GET .../ai-strategy/latest|history`, `POST/GET/DELETE .../chat`
Analiz: `.../insights`, `.../today`, `.../opportunities`, `POST .../opportunities/plan|export`, `.../competitor-brands`
Export: `.../export`, `.../export-bulksheet`, `.../bulk-readiness`, `.../campaign-ad-groups`
Ürün: `GET/POST .../products`, `PUT/DELETE /api/products/{id}`
Lansman: `POST /api/launch/analyze`, `POST /api/launch/bulksheet`
Eklenti: `/api/extension/files|file/{name}|download`

## DB (ppc.db, SQLite — git'te değil)

`brands` (hedef ACOS, eşikler, fiyat/cogs/fee, harvest kampanya, rakip markalar)
`uploads` · `report_rows` (report_type + JSON data) · `recommendations` (status: pending/approved/rejected)
`ai_strategies` (strategy_json + review_json + approved/safe_to_send) · `rec_history` (undo için snapshot)
`chat_messages` · `products` (asin, fiyat, cogs, share_pct)

## Frontend (static/index.html)

Tek dosya, `<style>` 8-828, HTML view'ları 829-1046, JS 1048+.
View'lar: `opp` (fırsatlar), `home`, `camp`, `charts`, `recs`, `ai` — `showView(k)` ile geçiş.
Ortak yardımcılar: `api()` 1132, `toast()` 1129, `loadBrands()` 1139, `selectBrand()` 1176.
Render fonksiyonları isimlendirme kalıbı: `render*` / `load*`.

## Konvansiyonlar

- Tüm kullanıcıya görünen metin **Türkçe**.
- Para/oran yardımcıları her modülde lokal (`_f`, `_num`, `_money`, `_acos`) — tekrar tanımlama normal, ortaklaştırma yapılmadı.
- `_` ile başlayan fonksiyonlar modül-içi; dışarıdan çağrılmaz.
- ACOS oran olarak tutulur (0.30 = %30), yüzde değil.
- Bulksheet kolon sırası Amazon şablonuna bağlı — `bulksheet.py:_empty_row()` değişirse export bozulur.

## Token tasarrufu kuralları (yeni oturumda uygula)

1. Önce bu dosyayı oku, tam dosya okuma yapma.
2. `app.py` / `index.html` / `market_intel.py` gibi büyük dosyalarda **Grep ile satır bul → Read offset/limit ile sadece o bloğu aç.**
3. Değişiklikten sonra doğrulama için dosyayı yeniden okuma; Edit hata vermediyse uygulanmıştır.
4. Bu haritayı bozan yapısal değişiklik yaparsan (yeni modül, yeni endpoint grubu, tablo) ilgili satırı burada güncelle.
