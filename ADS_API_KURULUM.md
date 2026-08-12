# Amazon Ads API kurulumu

Bunu tamamlayınca araç, **reklam açmadan önce** kelime bazında Amazon'un
kendi önerdiği bid aralığını çeker. CPC artık varsayım olmaz.

> **Önemli:** Aşağıdaki değerleri bana yazma, mesajlaşmaya yapıştırma.
> Kendi bilgisayarında `.env` dosyasına sen yaz. O dosya git'e girmiyor.

---

## 1. API erişimi başvurusu (onay gerekiyor, en uzun adım)

1. https://advertising.amazon.com/API/docs/en-us/index-overview adresine git
2. Sağ üstten **"Get started"** → Amazon Ads hesabınla giriş yap
3. Başvuru formunu doldur:
   - Kullanım amacı: *kendi hesabımın kampanya yönetimi ve raporlama*
   - Uygulama tipi: **internal / first-party** (kendi hesabın için, müşteriye satmıyorsan)
4. Onay bekle. Genelde birkaç gün, bazen 1-2 hafta sürer.

Onay gelmeden aşağıdaki adımlar çalışmaz.

## 2. Login with Amazon (LWA) uygulaması → client ID + secret

1. https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html
2. **Create a New Security Profile**
   - Name: `PPC Asistan`
   - Description: kendi kullanımın
   - Consent Privacy Notice URL: `https://ppc-asistan.onrender.com/privacy`
     (localhost kabul edilmez — herkese açık HTTPS adres olmalı)
3. Oluşturduktan sonra **Web Settings** → **Edit**
   - Allowed Return URLs: `https://ppc-asistan.onrender.com/callback`
4. Buradan iki değeri al: **Client ID** ve **Client Secret**

## 3. Refresh token (bir kez alınır, kalıcıdır)

Tarayıcıda şu adrese git (`CLIENT_ID` ve gerekiyorsa bölgeyi kendi
değerinle değiştir):

```
https://www.amazon.com/ap/oa?client_id=CLIENT_ID&scope=advertising::campaign_management&response_type=code&redirect_uri=https://ppc-asistan.onrender.com/callback
```

- Onayla. Tarayıcı canlı sunucundaki callback sayfasına döner ve
  **authorization code'u ekranda gösterir** — oradan kopyala.

Sonra terminalde (kendi değerlerini koyarak):

```bash
curl -X POST https://api.amazon.com/auth/o2/token \
  -d "grant_type=authorization_code" \
  -d "code=BURAYA_CODE" \
  -d "redirect_uri=https://ppc-asistan.onrender.com/callback" \
  -d "client_id=BURAYA_CLIENT_ID" \
  -d "client_secret=BURAYA_CLIENT_SECRET"
```

Dönen JSON'daki **`refresh_token`** değerini sakla. Bu kalıcıdır.

> `code` yalnızca birkaç dakika geçerlidir; hemen kullan.

## 4. Profile ID

`.env`'e ilk üç değeri yazdıktan sonra:

```bash
.venv/bin/python -c "import amazon_ads; print(amazon_ads.profiles())"
```

Çıktıda hesaplarını görürsün. Reklam verdiğin marketplace'in
(`countryCode: US` gibi) **`profileId`** değerini al.

## 5. .env dosyası

Proje klasöründeki `.env` dosyasına ekle:

```
ADS_CLIENT_ID=amzn1.application-oa2-client....
ADS_CLIENT_SECRET=....
ADS_REFRESH_TOKEN=Atzr|....
ADS_PROFILE_ID=1234567890
ADS_REGION=NA
```

`ADS_REGION`: ABD/Kanada/Meksika → `NA`, Avrupa/Türkiye → `EU`, Japonya/Avustralya → `FE`

## 6. Doğrulama

```bash
.venv/bin/python -c "import amazon_ads, json; print(json.dumps(amazon_ads.check(), indent=1))"
```

`"ok": true` ve hesap listesi görünüyorsa kurulum tamam.

---

## Sonra ne değişir

- **CPC varsayım olmaktan çıkar** — kelime bazında Amazon'un önerdiği bid aralığı kullanılır
- **Ölç-düzelt turuna gerek kalmaz** (yine de ilk hafta gerçek veriyle doğrulamak iyidir)
- Raporlar otomatik çekilebilir; haftalık manuel `.xlsx` yükleme biter

## Güvenlik

- `.env` git'e girmez (`.gitignore`'da `.env` ve `.env.*` var)
- Bu değerleri kimseye gönderme, ekran görüntüsüne alma
- Sızarsa: LWA konsolundan secret'ı yenile, refresh token'ı iptal et
