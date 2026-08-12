"""Amazon Advertising API baglantisi.

NEDEN: Reklam acilmadan CPC olculemez - CPC bir acik artirma sonucudur.
Amazon Ads API bunun TEK istisnasidir: Amazon kendi acik artirma verisinden
kelime bazinda onerilen bid araligini verir. Yani reklam acmadan once
gercek CPC beklentisini ogrenebiliriz.

Ayrica raporlari otomatik ceker; haftalik manuel xlsx yukleme derdi biter.

KIMLIK BILGILERI .env'DEN OKUNUR, KODA YAZILMAZ:
    ADS_CLIENT_ID       = LWA uygulamasinin client ID'si
    ADS_CLIENT_SECRET   = LWA uygulamasinin client secret'i
    ADS_REFRESH_TOKEN   = OAuth ile alinan refresh token
    ADS_PROFILE_ID      = Reklam hesabinin profil ID'si
    ADS_REGION          = NA | EU | FE   (varsayilan NA)

Kurulum adimlari icin: ADS_API_KURULUM.md
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ENDPOINTS = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}


def _cfg(name, default=""):
    return os.getenv(name, default).strip()


def is_configured():
    """Kimlik bilgileri tam mi? Eksikse arac sessizce degil, acikca soyler."""
    return all(_cfg(k) for k in
               ("ADS_CLIENT_ID", "ADS_CLIENT_SECRET", "ADS_REFRESH_TOKEN",
                "ADS_PROFILE_ID"))


def missing_config():
    return [k for k in ("ADS_CLIENT_ID", "ADS_CLIENT_SECRET",
                        "ADS_REFRESH_TOKEN", "ADS_PROFILE_ID") if not _cfg(k)]


_token_cache = {"value": None, "expires": 0}


def _access_token():
    """Refresh token -> kisa omurlu access token. Sonuc bellekte tutulur."""
    now = time.time()
    if _token_cache["value"] and _token_cache["expires"] - 60 > now:
        return _token_cache["value"]

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": _cfg("ADS_REFRESH_TOKEN"),
        "client_id": _cfg("ADS_CLIENT_ID"),
        "client_secret": _cfg("ADS_CLIENT_SECRET"),
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    _token_cache["value"] = body["access_token"]
    _token_cache["expires"] = now + int(body.get("expires_in", 3600))
    return _token_cache["value"]


def _call(path, payload=None, method="GET", content_type=None, timeout=60):
    base = ENDPOINTS.get(_cfg("ADS_REGION", "NA").upper(), ENDPOINTS["NA"])
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "Amazon-Advertising-API-ClientId": _cfg("ADS_CLIENT_ID"),
        "Amazon-Advertising-API-Scope": _cfg("ADS_PROFILE_ID"),
    }
    if content_type:
        headers["Content-Type"] = content_type
        headers["Accept"] = content_type
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=body, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Ads API {e.code}: {detail}") from None


def profiles():
    """Erisilebilen reklam hesaplari. ADS_PROFILE_ID'yi buradan secersin."""
    return _call("/v2/profiles")


def check():
    """Baglanti saglikli mi? Kurulum sonrasi dogrulama icin."""
    if not is_configured():
        return {"ok": False, "missing": missing_config(),
                "hint": ".env dosyasina eksik degerleri ekle"}
    try:
        ps = profiles()
        return {"ok": True, "profiles": [
            {"profileId": p.get("profileId"),
             "country": p.get("countryCode"),
             "type": (p.get("accountInfo") or {}).get("type"),
             "name": (p.get("accountInfo") or {}).get("name")} for p in ps]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def keyword_bid_recommendations(keywords, match_types=None, asin=None,
                                campaign_id=None, ad_group_id=None):
    """Kelime bazinda ONERILEN BID araligi (reklam acmadan!).

    Amazon'un kendi acik artirma verisinden gelir; tahmin degildir.
    Doner: {keyword: {match: {"low": x, "median": y, "high": z}}}

    NOT: Amazon bu ucu surumler ve zaman zaman sozlesmeyi degistirir.
    Cagri basarisiz olursa arac sessizce yanlis sayi uretmez - hata doner
    ve olc-duzelt moduna dusulur.
    """
    if not is_configured():
        raise RuntimeError("Ads API kimlik bilgileri eksik: "
                           + ", ".join(missing_config()))
    match_types = match_types or ["EXACT", "PHRASE", "BROAD"]
    ct = "application/vnd.spkeywordbidrecommendation.v3+json"

    payload = {
        "recommendationType": "KEYWORDS_FOR_ADGROUP" if ad_group_id
                              else "KEYWORDS_FOR_ASIN",
        "targetingExpressions": [
            {"type": f"KEYWORD_{m}_MATCH", "value": k}
            for k in keywords for m in match_types
        ],
    }
    if ad_group_id:
        payload["adGroupId"] = str(ad_group_id)
        payload["campaignId"] = str(campaign_id or "")
    elif asin:
        payload["asins"] = [asin]

    raw = _call("/sp/targets/bid/recommendations", payload,
                method="POST", content_type=ct)

    out = {}
    for item in (raw.get("bidRecommendations") or raw.get("recommendations") or []):
        expr = item.get("targetingExpression") or {}
        kw = expr.get("value")
        mt = (expr.get("type") or "").replace("KEYWORD_", "").replace("_MATCH", "")
        if not kw:
            continue
        vals = item.get("bidValues") or []
        nums = sorted(float(v.get("suggestedBid") or v.get("bid") or 0)
                      for v in vals if (v.get("suggestedBid") or v.get("bid")))
        if not nums:
            continue
        out.setdefault(kw, {})[mt.lower()] = {
            "low": round(nums[0], 2),
            "median": round(nums[len(nums) // 2], 2),
            "high": round(nums[-1], 2),
        }
    return out


def cpc_reference(keywords, asin=None):
    """Bid onerilerini benchmarks'in bekledigi CPC referansina cevirir.

    Median oneri, pazarin o kelimede istedigi CPC'nin en iyi vekilidir.
    """
    recs = keyword_bid_recommendations(keywords, asin=asin)
    per_match = {}
    for kw, by_match in recs.items():
        for m, v in by_match.items():
            per_match.setdefault(m, []).append(v["median"])
    summary = {m: round(sum(v) / len(v), 2) for m, v in per_match.items() if v}
    return {"per_keyword": recs, "avg_by_match": summary,
            "source": "Amazon Ads API bid recommendations"}
