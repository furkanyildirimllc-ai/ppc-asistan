"""Kampanya mimarisi - standart yapi, denetim ve eksik katman uretimi.

STANDART YAPI (her urun icin)
  AUTO    kesif    Amazon'un kendi eslesmesi. En ucuz kesif kaynagi,
                   yeni kelime buradan cikar. ASLA kapatilmaz - kesif
                   durursa kazanan havuzu buyumez.
  BROAD   kesif    Kazanan kavramlarin cevresini tarar. Auto'nun
                   bulamadigi varyasyonlari yakalar.
  PHRASE  ara      Kavram dogrulandi ama tam sorgu belli degil.
  EXACT   hasat    Kanitlanmis kelimeler. En yuksek teklif buraya gider -
                   donusecegini BILIYORUZ.
  PT      ASIN     Rakip urun sayfalarinda gorunme.

KATMANLAR BIRBIRINI DESTEKLER, YARISMAZ
Kesif katmani (auto/broad) yeni kelime bulur -> kanitlananlar EXACT'e
tasinir -> tasinan kelime kesif katmanlarina NEGATIF olarak eklenir.
Negatif eklenmezse ayni kelime iki yerde yarisir: kesif katmani pahali
tikligi alir, hasat katmani ac kalir ve olcum bozulur.

ISIMLENDIRME (takip edilebilirlik)
  {marka} | {ASIN} | {KATMAN}
Amazon raporlarinda ASIN kampanya adinda oldugu icin urun bazinda
ayristirma her zaman mumkun olur. Marka adi basta oldugu icin markalar
ASLA karismaz.
"""
import re

import benchmarks

KATMANLAR = {
    "AUTO":   {"targeting": "AUTO", "match": None,
               "rol": "keşif", "butce_payi": 0.20,
               "aciklama": "Amazon'un kendi eşleşmesi — yeni kelime kaynağı"},
    "BROAD":  {"targeting": "MANUAL", "match": "broad",
               "rol": "keşif", "butce_payi": 0.15,
               "aciklama": "Kavram çevresini tarar"},
    "PHRASE": {"targeting": "MANUAL", "match": "phrase",
               "rol": "ara", "butce_payi": 0.20,
               "aciklama": "Kavram doğrulandı, sorgu aranıyor"},
    "EXACT":  {"targeting": "MANUAL", "match": "exact",
               "rol": "hasat", "butce_payi": 0.40,
               "aciklama": "Kanıtlanmış kelimeler — en yüksek teklif"},
}
ZORUNLU = ["AUTO", "EXACT"]          # bunlar olmadan yapi calismaz
ONERILEN = ["AUTO", "BROAD", "PHRASE", "EXACT"]


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def campaign_name(brand, asin, layer):
    """Standart ad. ASIN adda oldugu icin urun bazinda takip mumkun."""
    m = re.sub(r"[^A-Za-z0-9]+", "", str(brand or "Marka"))[:14] or "Marka"
    return f"{m} | {asin} | {layer}"


def audit(bulk, brand_name=""):
    """Her urun icin hangi katmanlar var, hangileri eksik?"""
    g = lambda r, k: benchmarks_get(bulk, r, k)
    import bulk_doctor as BD
    g = lambda r, k: BD._get(bulk, r, k)

    kam = {g(r, "Campaign ID"): r for r in bulk["rows"]
           if g(r, "Entity") == "Campaign"}
    kw, pt, pa = {}, {}, {}
    for r in bulk["rows"]:
        cid, e = g(r, "Campaign ID"), g(r, "Entity")
        if e == "Keyword" and g(r, "State") == "enabled":
            kw.setdefault(cid, []).append(str(g(r, "Match Type") or "").lower())
        elif e == "Product Targeting" and g(r, "State") == "enabled":
            pt[cid] = pt.get(cid, 0) + 1
        elif e == "Product Ad" and g(r, "State") == "enabled":
            a = str(g(r, "ASIN (Informational only)") or "").upper()
            if len(a) == 10:
                pa.setdefault(cid, set()).add(a)

    urunler = {}
    for cid, kr in kam.items():
        if g(kr, "State") != "enabled":
            continue
        tip = str(g(kr, "Targeting Type") or "").lower()
        m = kw.get(cid, [])
        if tip == "auto":
            katman = "AUTO"
        elif pt.get(cid) and not m:
            katman = "PT"
        elif m and all(x == "exact" for x in m):
            katman = "EXACT"
        elif m and "phrase" in m:
            katman = "PHRASE"
        elif m and "broad" in m:
            katman = "BROAD"
        else:
            katman = "?"
        for a in pa.get(cid, ()):
            u = urunler.setdefault(a, {"asin": a, "layers": {}, "sku": None,
                                       "spend": 0.0, "sales": 0.0})
            u["layers"].setdefault(katman, []).append({
                "campaign_id": cid, "name": str(g(kr, "Campaign Name") or ""),
                "budget": _f(g(kr, "Daily Budget")),
                "spend": _f(g(kr, "Spend")), "sales": _f(g(kr, "Sales"))})
            u["spend"] += _f(g(kr, "Spend"))
            u["sales"] += _f(g(kr, "Sales"))

    # SKU'lari topla (Product Ad satirindan)
    for r in bulk["rows"]:
        if g(r, "Entity") == "Product Ad" and g(r, "State") == "enabled":
            a = str(g(r, "ASIN (Informational only)") or "").upper()
            if a in urunler and not urunler[a]["sku"]:
                urunler[a]["sku"] = g(r, "SKU")

    out = []
    for a, u in sorted(urunler.items()):
        var = set(u["layers"])
        out.append({
            **u,
            "has": sorted(var),
            "missing_required": [k for k in ZORUNLU if k not in var],
            "missing_recommended": [k for k in ONERILEN if k not in var],
            "healthy": all(k in var for k in ZORUNLU),
        })
    return {"products": out,
            "complete": sum(1 for x in out if not x["missing_recommended"]),
            "total": len(out)}


def benchmarks_get(bulk, r, k):     # geriye uyum
    import bulk_doctor as BD
    return BD._get(bulk, r, k)


def cross_negatives(bulk, harvested_keywords, search_terms=None,
                    min_clicks=2):
    """Hasat edilen kelimeleri KESIF katmanlarina negatif ekler.

    NEDEN: bir kelime EXACT'e tasindiktan sonra auto/broad kampanyada da
    calismaya devam ederse ayni sorgu icin iki kampanyan yarisir. Amazon
    tek reklam gosterir; genelde gecmisi olan kesif kampanyasi kazanir ve
    pahali tikligi o alir. Hasat kampanyan ac kalir, olcum bozulur.

    Doner: [{campaign_id, ad_group_id, keyword}] - negatif eklenecekler.
    """
    import bulk_doctor as BD
    g = lambda r, k: BD._get(bulk, r, k)
    kam = {g(r, "Campaign ID"): r for r in bulk["rows"]
           if g(r, "Entity") == "Campaign"}
    ag = {g(r, "Campaign ID"): g(r, "Ad Group ID") for r in bulk["rows"]
          if g(r, "Entity") == "Ad Group"}
    # Mevcut negatifler - tekrar eklemeyelim
    mevcut = set()
    for r in bulk["rows"]:
        if g(r, "Entity") in ("Negative Keyword", "Campaign Negative Keyword"):
            mevcut.add((g(r, "Campaign ID"),
                        str(g(r, "Keyword Text") or "").strip().lower()))
    kelimeler = {str(k).strip().lower() for k in (harvested_keywords or []) if k}

    # HANGI KAMPANYADA hangi terim GERCEKTEN geciyor?
    #
    # HATA GECMISI: her hasat kelimesi her kesif kampanyasina negatif
    # ekleniyordu - 43 kelime x 24 kampanya = 1037 satir. Cogu o
    # kampanyada hic gecmemis terimlerdi: dosyayi sisiriyor ve kesfi
    # gereksiz kisitliyordu. Negatif ancak GERCEK bir catisma varsa
    # anlamlidir: terim o kampanyada tiklama almis olmali.
    gecen = {}
    for r in (search_terms or []):
        t = str(r.get("term") or "").strip().lower()
        if t not in kelimeler:
            continue
        if _f(r.get("clicks")) < min_clicks:
            continue
        gecen.setdefault(str(r.get("campaign") or ""), set()).add(t)

    ad_to_id = {str(g(r, "Campaign Name") or ""): g(r, "Campaign ID")
                for r in bulk["rows"] if g(r, "Entity") == "Campaign"}

    out = []
    for kam_adi, terimler in gecen.items():
        cid = ad_to_id.get(kam_adi)
        if cid is None or cid not in kam:
            continue
        kr = kam[cid]
        if g(kr, "State") != "enabled":
            continue
        ad = str(g(kr, "Campaign Name") or "")
        tip = str(g(kr, "Targeting Type") or "").lower()
        # Yalnizca KESIF katmanlarina negatif eklenir - hasat katmanina
        # eklenirse kendi kelimesini bloklamis oluruz.
        kesif = (tip == "auto" or "BROAD" in ad.upper() or "PHRASE" in ad.upper()
                 or "Discovery" in ad or "Research" in ad)
        if not kesif or "EXACT" in ad.upper() or "HASAT" in ad.upper():
            continue
        for kw in sorted(terimler):
            if (cid, kw) in mevcut:
                continue
            out.append({"campaign_id": cid, "ad_group_id": ag.get(cid),
                        "campaign": ad, "keyword": kw,
                        "reason": "EXACT'e taşındı - keşifte tekrar yarışmasın"})
    return out
