"""Amazon Ads API kurulum yardimcisi.

Calistir:  .venv/bin/python setup_ads.py

Ne yapar:
  1. .env'deki ADS_CLIENT_ID ile yetkilendirme baglantisini uretir
  2. Tarayicidan aldigin authorization code'u refresh token'a cevirir
  3. Refresh token'i .env'e KENDISI yazar (kopyala-yapistir yok)
  4. Reklam hesaplarini listeler, sectigini ADS_PROFILE_ID olarak yazar
  5. Bolgeyi (NA/EU/FE) hesabin ulkesinden otomatik belirler

Hicbir deger ekrana tam olarak basilmaz; .env disina cikmaz.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ENV = pathlib.Path(__file__).parent / ".env"
REDIRECT = "https://ppc-asistan.onrender.com/callback"
AUTH_BASE = "https://www.amazon.com/ap/oa"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# Marketplace ulkesi -> Ads API bolgesi
REGION_BY_COUNTRY = {
    "US": "NA", "CA": "NA", "MX": "NA", "BR": "NA",
    "UK": "EU", "GB": "EU", "DE": "EU", "FR": "EU", "IT": "EU", "ES": "EU",
    "NL": "EU", "SE": "EU", "PL": "EU", "BE": "EU", "TR": "EU",
    "AE": "EU", "SA": "EU", "EG": "EU", "IN": "EU",
    "JP": "FE", "AU": "FE", "SG": "FE",
}


def read_env():
    vals = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def write_env(key, value):
    """Anahtari .env'de gunceller; yoksa ekler. Diger satirlara dokunmaz."""
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    done = False
    for i, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            lines[i] = f"{key}={value}"
            done = True
            break
    if not done:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask(s):
    s = str(s or "")
    return (s[:6] + "…" + s[-4:]) if len(s) > 12 else "(kisa)"


def post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("\nHATA:", e.code, e.read().decode("utf-8", "replace")[:400])
        sys.exit(1)


def main():
    env = read_env()
    cid, secret = env.get("ADS_CLIENT_ID"), env.get("ADS_CLIENT_SECRET")
    if not cid or not secret:
        print("ADS_CLIENT_ID veya ADS_CLIENT_SECRET .env'de bos.")
        print("Once bu ikisini .env'e yaz, sonra tekrar calistir.")
        sys.exit(1)
    print(f"Client ID bulundu: {mask(cid)}")

    if env.get("ADS_REFRESH_TOKEN"):
        print(f"Refresh token zaten var: {mask(env['ADS_REFRESH_TOKEN'])}")
        if input("Yenisini almak ister misin? (e/H) ").strip().lower() != "e":
            return finish(read_env())

    auth_url = AUTH_BASE + "?" + urllib.parse.urlencode({
        "client_id": cid,
        "scope": "advertising::campaign_management",
        "response_type": "code",
        "redirect_uri": REDIRECT,
    })
    print("\n1) Su baglantiyi tarayicida ac ve onayla:\n")
    print(auth_url)
    print("\n2) Amazon seni callback sayfasina dondurecek ve ekranda bir")
    print("   'authorization code' gosterecek. Onu buraya yapistir.")
    code = input("\nAuthorization code: ").strip()
    if not code:
        print("Kod bos, cikiliyor.")
        sys.exit(1)

    print("\nToken aliniyor...")
    tok = post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": cid,
        "client_secret": secret,
    })
    rt = tok.get("refresh_token")
    if not rt:
        print("Refresh token donmedi:", json.dumps(tok)[:300])
        sys.exit(1)
    write_env("ADS_REFRESH_TOKEN", rt)
    print(f"Refresh token .env'e yazildi: {mask(rt)}")
    finish(read_env())


def finish(env):
    """Profilleri listele, sec, ADS_PROFILE_ID + ADS_REGION yaz."""
    import os
    for k, v in env.items():
        os.environ[k] = v
    # Profil sorgusu bolge bazlidir; hepsini dene.
    import amazon_ads
    found = []
    for region in ("NA", "EU", "FE"):
        os.environ["ADS_REGION"] = region
        try:
            for p in amazon_ads.profiles():
                p["_region"] = region
                found.append(p)
        except Exception:
            continue
    if not found:
        print("\nHicbir reklam profili bulunamadi.")
        print("API basvurun onaylandi mi? Onay gelmeden profil listelenmez.")
        return

    print("\nErisilebilen reklam hesaplari:")
    for i, p in enumerate(found, 1):
        acc = p.get("accountInfo") or {}
        print(f"  {i}) profileId={p.get('profileId')}  "
              f"ulke={p.get('countryCode')}  tip={acc.get('type')}  "
              f"ad={acc.get('name')}  [{p['_region']}]")

    sel = input("\nHangisini kullanacaksin? (numara) ").strip()
    try:
        chosen = found[int(sel) - 1]
    except Exception:
        print("Gecersiz secim.")
        return
    country = (chosen.get("countryCode") or "").upper()
    region = REGION_BY_COUNTRY.get(country, chosen["_region"])
    write_env("ADS_PROFILE_ID", str(chosen.get("profileId")))
    write_env("ADS_REGION", region)
    print(f"\n.env guncellendi: ADS_PROFILE_ID={chosen.get('profileId')}  "
          f"ADS_REGION={region}")
    print("\nKurulum tamam. Dogrulama:")
    print('  .venv/bin/python -c "import amazon_ads,json; '
          'print(json.dumps(amazon_ads.check(),indent=1))"')


if __name__ == "__main__":
    main()
