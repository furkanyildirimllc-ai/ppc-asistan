# PPC Launch Asistan — Chrome Uzantısı

Yeni listelediğin Amazon ürünü için tek tıkla: **rakip + keyword araştır → kâr
analizi → auto/manual kampanya planı → Amazon bulk sheet indir.**

## 1) Backend'i çalıştır
```bash
cd ppc-tool
.venv/bin/uvicorn app:app --port 8642
```
`.env` içinde `ANTHROPIC_API_KEY` olmalı (keyword/strateji AI'si için).
İsteğe bağlı: `KEEPA_API_KEY` (rakip ASIN keşfi), `LAUNCH_MODEL` (varsayılan
`claude-opus-5` — en güçlü; ucuzlatmak için `.env`'de `LAUNCH_MODEL=claude-sonnet-5` yap).

## 2) Uzantıyı yükle
1. Chrome → `chrome://extensions`
2. Sağ üstten **Developer mode** aç
3. **Load unpacked** → bu `extension/` klasörünü seç

## 3) Kullan
1. Bir Amazon ürün sayfası **veya** arama sonucu sayfası aç
2. Uzantı ikonuna tıkla → ürün + rakipler otomatik okunur
3. (İsteğe bağlı) COGS / FBA gir → kâr & break-even ACOS hesaplanır
4. **"Rakip + Keyword araştır, plan kur"** → AI stratejiyi üretir
5. **"Amazon Bulk Sheet indir"** → Seller Central → Bulk Operations →
   Spreadsheet upload'a yükle

## Üretilen kampanya yapısı
- **Auto | Discovery** — 4 hedefleme grubu, keşif
- **Manual | Broad Research** — geniş keşif
- **Manual | Phrase** — orta niyet
- **Manual | Exact (Scale)** — en yüksek dönüşüm, agresif bid + bütçe
- **Manual | ASIN Targeting** — rakip ASIN'leri (varsa)
- Auto/Broad/Phrase'e otomatik **negatif exact** keyword'ler eklenir.

## Not
- Amazon'un resmi Ads API onayı olmadan yazılım doğrudan kampanya açamaz;
  bu yüzden akış **bulk sheet** üretir (onaysız, hızlı, güvenli).
- SKU girmezsen Product Ad satırlarında ASIN placeholder kullanılır — seller
  isen gerçek SKU'nu yazman gerekir.
