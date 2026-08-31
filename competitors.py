"""Rakip kesfi - KENDI raporlarindan, performansla birlikte.

NEDEN KAZIMA DEGIL
Amazon sunucu tarafi istekleri engeller (503). Keepa aboneligi ayri
maliyet. Ama daha iyisi zaten elimizde: kendi reklam raporlarin.

Uc kaynak, ucu de performans tasir:
  1. ARAMA TERIMI = ASIN  Musteri o rakibi aradi, SENIN urunun cikti.
     Tiklama/satis biliniyor - hangi rakibin trafiginin donustugu belli.
  2. ASIN HEDEFLEME       Zaten hedefledigin rakipler ve sonuclari.
  3. BRAND ANALYTICS      Ayni sepette satin alinan urunler.

Kazinan listede "bu rakip sana satis getirir mi" bilgisi YOKTUR.
Burada VARDIR - bu yuzden daha degerli.
"""
import re
from collections import defaultdict

ASIN_KALIBI = re.compile(r"\b(B0[A-Z0-9]{8})\b")


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _asin(metin):
    m = ASIN_KALIBI.search(str(metin or "").upper())
    return m.group(1) if m else None


def own_asins_from(rows_list):
    """Markanin KENDI ASIN'lerini her kaynaktan toplar.

    NEDEN COK KAYNAK: advertised_product ya da listings raporu yoksa kendi
    urunun "rakip" diye onerilebilir. Kampanya adlarinda ASIN tasindigi
    icin (mimari standardi) oradan da cikarilir. Kendi urunune reklam
    vermek ISTENEN bir sey degildir - kendi kendine rekabet.
    """
    kendi = set()
    for rows in rows_list or []:
        for r in rows or []:
            for alan in ("asin", "advertised_asin", "ASIN"):
                a = _asin(r.get(alan)) if isinstance(r, dict) else None
                if a:
                    kendi.add(a)
            # Kampanya/ad group adinda gecen ASIN de bize aittir
            for alan in ("campaign", "ad_group"):
                a = _asin((r or {}).get(alan))
                if a:
                    kendi.add(a)
    return kendi


def from_reports(search_terms=None, targeting=None, market_basket=None,
                 own_asins=None):
    """Raporlardan rakip ASIN'leri cikarir ve performansa gore siralar.

    own_asins: markanin kendi ASIN'leri - listeden CIKARILIR. Kendi urunun
    rakip olarak onerilirse kendi kendine rekabet ettirmis olursun.
    """
    kendi = {str(a).upper() for a in (own_asins or []) if a}
    # Kampanya adlarindan da kendi ASIN'lerini topla - guvenlik agi
    kendi |= own_asins_from([search_terms, targeting])
    kayit = defaultdict(lambda: {
        "asin": None, "clicks": 0.0, "spend": 0.0, "orders": 0.0,
        "sales": 0.0, "sources": set()})

    # 1) Arama terimi ASIN ise: musteri o rakibi aradi, senin urunun cikti
    for r in (search_terms or []):
        a = _asin(r.get("term"))
        if not a or a in kendi:
            continue
        k = kayit[a]
        k["asin"] = a
        k["clicks"] += _f(r.get("clicks"))
        k["spend"] += _f(r.get("spend"))
        k["orders"] += _f(r.get("orders"))
        k["sales"] += _f(r.get("sales"))
        k["sources"].add("arama-terimi")

    # 2) Hedefledigin ASIN'ler
    for r in (targeting or []):
        a = _asin(r.get("targeting"))
        if not a or a in kendi:
            continue
        k = kayit[a]
        k["asin"] = a
        k["clicks"] += _f(r.get("clicks"))
        k["spend"] += _f(r.get("spend"))
        k["orders"] += _f(r.get("orders"))
        k["sales"] += _f(r.get("sales"))
        k["sources"].add("asin-hedefleme")

    # 3) Brand Analytics: ayni sepette alinanlar
    for r in (market_basket or []):
        for v in (r or {}).values():
            a = _asin(v) if isinstance(v, str) else None
            if not a or a in kendi:
                continue
            k = kayit[a]
            k["asin"] = a
            k["sources"].add("market-basket")

    out = []
    for a, k in kayit.items():
        roas = (k["sales"] / k["spend"]) if k["spend"] > 0 else None
        acos = (k["spend"] / k["sales"] * 100) if k["sales"] > 0 else None
        out.append({
            "asin": a,
            "clicks": round(k["clicks"]), "spend": round(k["spend"], 2),
            "orders": round(k["orders"]), "sales": round(k["sales"], 2),
            "roas": round(roas, 1) if roas else None,
            "acos_pct": round(acos, 1) if acos else None,
            "sources": sorted(k["sources"]),
            # Kanitlanmis = bu rakibin trafigi sana SATIS getirmis
            "proven": k["sales"] > 0,
        })
    out.sort(key=lambda x: (-(x["sales"] or 0), -(x["clicks"] or 0)))
    return out


def classify(rakipler, accepted_acos_pct=100.0, min_clicks=3):
    """Rakipleri aksiyona gore ayirir.

    hedefle    : satis getirmis, ACOS kabul edilebilir -> ASIN kampanyasi ac
    izle       : tiklama var ama henuz satis yok -> veri birikmeli
    disla      : yeterli tiklama, satis yok, para yakiyor -> negatif ASIN
    bilgi      : sadece market basket'ten geliyor, reklam verisi yok
    """
    hedefle, izle, disla, bilgi = [], [], [], []
    for r in rakipler:
        if not r["clicks"] and "market-basket" in r["sources"]:
            bilgi.append(r)
        elif r["proven"] and (r["acos_pct"] or 0) <= accepted_acos_pct:
            hedefle.append(r)
        elif r["proven"]:
            izle.append(r)          # satiyor ama pahali - teklif ayari
        elif r["clicks"] >= min_clicks * 3 and r["spend"] > 0:
            disla.append(r)
        else:
            izle.append(r)
    return {"target": hedefle, "watch": izle, "exclude": disla, "info": bilgi}
