# Performans Analiz Uzmanı — proje haritası

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
| `autopilot.py` | 260 | **Otopilot**: tek dosyadan tam analiz; `did` (araç yaptı) / `todo` (insan yapmalı) ayrımı |
| `phases.py` | 230 | **Faz motoru (TEK KAYNAK)**: hangi fazdasın, neden, sıradaki iş, çıkış kriteri |
| `growth.py` | 190 | **Hedef planlayıcı**: %30 marjlı büyüme planı + açığı kapatacak kaldıraçlar (CTR/CVR/AOV/hacim) |
| `listing.py` | 220 | **Listing optimizasyonu**: reklam verisinden başlık/bullet/arka plan önerisi, rakip marka koruması |
| `verify.py` | 210 | **Yükleme sonrası denetim**: hesabın son hali kurallara uyuyor mu (yazılana değil, olana bakar) |
| `bulk_doctor.py` | 250 | **Canlı hesap doktoru**: Bulk Operations dosyasını okur, teşhis eder, `Operation=Update` düzeltme dosyası üretir |
| `benchmarks.py` | 600 | Ölçülmüş CVR/CPC/AOV çözümleyici, marka izolasyonu, harcama kapasitesi |
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
Rekabet: `GET /api/brands/{id}/competitiveness` (teklif pazarı karşılıyor mu)
Otopilot: `POST /api/brands/{id}/autopilot` (tam analiz) · `.../autopilot/file` (tek düzeltme dosyası)
Faz: `GET /api/brands/{id}/phase` (faz + neden + yapılacaklar) · `.../autofill` (ürünleri otomatik doldur)
Büyüme: `POST /api/brands/{id}/growth-plan` (%30 marjlı hedef planı)
Listing: `GET /api/brands/{id}/listing-plan` (başlık/arka plan önerisi)
Doktor: `POST /api/brands/{id}/bulk-doctor` (teşhis), `.../bulk-doctor/file` (düzeltme dosyası), `.../bulk-doctor/verify` (yükleme sonrası denetim)
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

## Amazon bulksheet kuralları (resmi şablondan doğrulandı)

Referans: `AmazonAdvertisingBulksheetSellerTemplate.xlsx` → `Config` sayfası.
**Bu değerler tahmin değil, Amazon'un kendi listesidir. Değiştirmeden önce şablona bak.**

| Alan | Geçerli değerler |
|---|---|
| `Product` | `Sponsored Products` |
| `Entity` | Campaign, Ad Group, Bidding Adjustment, Campaign Negative Keyword, Keyword, Negative Keyword, Product Targeting, Negative Product Targeting, Product Ad |
| `Operation` | Create, Update, Archive |
| `Targeting Type` | **`AUTO` / `MANUAL` (BÜYÜK HARF)** — şablon böyle diyor; pratikte `Auto`/`Manual` de kabul edildi ama büyük harf yaz |
| `Bidding Strategy` | Dynamic bids - down only / Dynamic bids - up and down / Fixed bid |
| Keyword `Match Type` | exact, phrase, broad |
| Negative Keyword `Match Type` | negativeExact, negativePhrase |
| `State` (Create) | enabled, paused |
| Auto targeting ifadeleri | close-match, loose-match, substitutes, complements |

Create için zorunlu kolonlar (entity bazında):
- Campaign: Campaign ID, Campaign Name, Daily Budget, Targeting Type, State, Start Date, Bidding Strategy
- Ad Group: Campaign ID, Ad Group ID, Ad Group Name, Ad Group Default Bid, State
- Product Ad: Campaign ID, Ad Group ID, **SKU**, State
- Keyword / Negative Keyword: Campaign ID, Ad Group ID, State, Keyword Text, Match Type
- Product Targeting: Campaign ID, Ad Group ID, State, Product Targeting Expression

Kolon formatı: Bizim çıktımız Amazon'un **indirme (rapor)** formatını taklit eder — 46 kolon,
`(Read only)` / `(Informational only)` ekli kolonlar ve performans kolonları dahil.
Yükleme şablonu 32 kolondur. Amazon eşleştirmeyi **kolon adına göre** yapar, sıraya göre değil;
fazla kolonlar yok sayılır. Bu format indirip-düzenleyip-tekrar yükleme akışının aynısıdır ve
gerçek yüklemede kabul edildiği doğrulandı.

**SKU tuzağı:** `launch.py` SKU boşsa ASIN'e düşer (`sku = product.get("sku") or asin`).
Seller hesabında ASIN geçerli SKU değildir → Product Ad satırları reddedilir. Formda SKU doldurulmalı.

## Kritik hesap kuralları (bozarsan sayılar sessizce yanlış çıkar)

- **`RELATIVE_CVR` ve `RELATIVE_CPC` aynı tabana göredir: hesap ortalaması = 1.00.**
  Biri phrase tabanına göre yazılıp diğeriyle aynı şekilde çarpılırsa tüm CVR
  tahminleri ~%20 kayar. Değiştirmeden önce gerçek veriyle kalibre et.
- **Lansman rampası (0.65) yalnızca ÖLÇÜM YOKKEN uygulanır.** Ölçülmüş CVR zaten
  gerçek; rampa uygulamak bid'i olması gerekenin altına indirir.
- **Bütçe harcama değildir.** Bu hesapta bütçenin %19-28'i harcanıyor. Bütçe kısıtlı
  (kullanım ≥%80) ve talep kısıtlı (<%30) kampanyaların çözümü ZITTIR: biri bütçe,
  diğeri teklif ister. `benchmarks.spend_capacity()` bunu ayırır.
- **Bütçe ≥ teklif × 5.** Altındaysa kampanya günde 5 tıklama bile alamaz, ölü doğar.
  `launch.enforce_budget_floor()` ve `bulk_doctor.MIN_CLICKS_PER_DAY` bunu uygular.
- **Kampanya raporunda Campaign ID YOKTUR.** Güncelleme dosyası yalnızca Bulk
  Operations indirmesinden üretilebilir.
- **Sessiz düşüş yasak.** Bilinmeyen bid stratejisi `ValueError` fırlatır; sessizce
  "profit"e düşmez.
- **Az veriyle karar verme.** 15 tık altında "kötü" denmez; sıfır sipariş kararı için
  `zero_order_confidence >= %80` aranır.
- **Kanıtlanmış kelimeye ham CVR ile teklif verme — "kazananın laneti".** Terimleri
  kazandıkları için seçeriz, ölçülen CVR yukarı sapar. 2 tıkta 1 sipariş = %50 değildir.
  `benchmarks.shrunk_cvr()` küçük örneği hesap ortalamasına çeker (k=30 tık).
  `benchmarks.keyword_bid()` bunu kullanır ve teklifi pazar CPC'sinin 3 katıyla sınırlar.
- **Hesap ortalaması tavanı, kanıtlanmış kelimeye uygulanmaz.** Hasat kelimeleri hesap
  ortalamasından çok daha iyi dönüşür (ölçüldü: Natural %56 vs hesap %4.67). Hesap
  tavanını onlara uygulamak teklifi karşılıksız bırakır — gösterim gelmez.
- **EKONOMİK TAVAN her stratejide son sözdür.** Tıklama başına ciro = AOV × CVR; bu,
  %100 ACOS'taki maksimum tekliftir. Pazar CPC'si bu markanın ekonomisini taşımak
  zorunda değil — pazara çapa atmadan önce tavan gelir. `benchmarks.economic_ceiling()`.
- **Kelimeler `guard_row()` kapısından geçer.** Amazon: max 80 karakter, max 10 kelime,
  noktalama yok, ASCII dışı yok. Arama terimi ≠ geçerli kelime.
- **`enforce_budget_floor()` asla boş dönmez.** Bütçe hiçbir kampanyayı taşımıyorsa en
  öncelikli kampanya korunur ve bütçesi yükseltilir; boş dosya üretmek daha kötüdür.

- **Öneri üreten her yol `analysis.cap_recommendations()`'dan geçer.** Ham CVR yerine
  `benchmarks.shrunk_cvr()` kullanılır — 3 siparişle %20 CVR görüp bid'i +%40 artırmak
  kazananın lanetidir.
- **Rakip marka adı reklamda meşru, listede ihlaldir.** Arama terimi raporundaki en kârlı
  terimler sık sık rakip markadır. `listing.looks_like_brand()` bunları ayırır; şüpheliyse
  listeye yazmamak doğru taraftır (asimetrik risk: yanlış pozitif = küçük kayıp,
  yanlış negatif = liste askıya alınır).
- **Projeksiyon %30 marjla yapılır** (`growth.SAFETY_MARGIN`). Hedefe tam oturan plan,
  %30 sapmada hedefi kaçırır.

### Faz modeli (phases.py — TEK KAYNAK)

Faz sınırlarını **istatistik** belirler, takvim değil. "2 hafta geçti, faz atlayalım"
yanlıştır; "CPC'yi ölçecek kadar tıklama biriktim" doğrudur.

| Faz | Amaç | Çıkış koşulu |
|---|---|---|
| 0 Keşif | Tıklama başına ne ödediğini ölç | ≥15 tık (CPC ±%9) |
| 1 Doğrulama | Hangi kelimenin dönüştüğünü bul | ≥100 tık **ve** ≥1 kazanan terim |
| 2 Hasat | Parayı kazananlara yığ, israfı kes | ACOS ≤ hedef **ve** ≥5 kazanan |
| 3 Büyüme | Kârlı yapıyı büyüt | — |

- **Faz 3 kârlılık iddiasıdır.** Hedef ACOS bilinmiyorsa en fazla Faz 2'de kalınır —
  "bilmiyoruz" demek "kârlıyız" demekten doğrudur.
- **Faz mantığı başka hiçbir yerde hesaplanmaz.** Önceden `discovery-status`,
  `product-status` ve `autofill` ayrı kurallarla karar veriyordu; aynı marka bir
  ekranda Faz 0, diğerinde Faz 1 görünüyordu. Yeni faz kuralı gerekiyorsa
  `phases.assess()` içine yazılır, kopyalanmaz.

### Kural yazmak ≠ kural uygulamak

Bu projede bir kez oldu: `economic_ceiling`, `sanitize_keyword`, `enforce_budget_floor`
ve `spend_capacity` yazıldı ama **hiçbir yerden çağrılmadı**. Araç eski hatalarını
üretmeye devam etti. Yeni kural eklerken:
1. Kuralı **tek yerde** tanımla (tercihen `benchmarks.py`)
2. Tüm yollara bağla, tek kapıdan geçir (`guard_row`, `emit`)
3. Kuralın **ihlal edildiği bir girdiyle** test et — geçtiğini değil, engellediğini gör
4. `verify.py`'ye denetim maddesi ekle

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
