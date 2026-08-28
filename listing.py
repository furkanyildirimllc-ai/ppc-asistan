"""Listing optimizasyonu - reklam verisinden baslik/bullet onerisi.

NEDEN REKLAM VERISI: hangi kelimenin SATIS getirdigini yalnizca reklam
raporu bilir. Anahtar kelime araclari arama HACMINI gosterir, DONUSUMU
degil. Bu modul "musteriler bu kelimeyle arayip SATIN ALDI" diyebildigi
kelimeleri listeye tasir.

CTR en buyuk ve en ucuz kaldiractir: gosterimin parasi zaten odendi.
Baslikta dogru kelime olmasi hem CTR'yi hem organik siralamayi yukseltir.
"""
import re
from collections import defaultdict

import benchmarks

TITLE_MAX = 200          # Amazon baslik siniri (kategoriye gore 150-200)
TITLE_PRIME = 80         # ilk 80 karakter mobilde gorunur - en degerli alan
BULLET_MAX = 500
BACKEND_MAX = 249        # arka plan arama terimleri (bytes)

# Baslikta/bullet'ta bulunmasi Amazon tarafindan sorun edilen ifadeler
YASAKLI = {
    "best", "cheapest", "free shipping", "sale", "guarantee", "guaranteed",
    "cure", "treat", "heal", "fda", "approved", "#1", "top rated",
}

STOP = {"for", "the", "and", "with", "of", "to", "in", "a", "on", "my",
        "de", "para", "el", "la", "y", "que", "un", "una"}

# RAKIP MARKA TUZAGI
# Arama terimi raporunda en karli terimler sik sik RAKIP MARKA adlaridir -
# musteri rakibi arar, senin urunun cikar, satin alir. Bu reklam icin
# mesrudur (marka hedefleme) ama BASLIGA ya da arka plan kelimelerine
# rakip marka yazmak Amazon marka ihlalidir ve listeyi askiya aldirir.
# Bu yuzden onerilerde ayrilir: reklamda KULLAN, listeye YAZMA.
BILINEN_RAKIP_MARKALAR = {
    "alpecin", "dercos", "vichy", "nioxin", "kerastase", "olaplex",
    "redken", "aveda", "moroccanoil", "briogeo", "pura", "purador",
    "viviscal", "rogaine", "minoxidil", "keeps", "hims", "nutrafol",
    "fiera", "stembox", "obsidienne", "ariyv", "strongville", "dip7",
    "cerave", "cetaphil", "olay", "neutrogena", "loreal", "garnier",
}


def looks_like_brand(word, known=None):
    """Bu kelime bir marka adi olabilir mi?

    Kesin bilemeyiz - ama supheliyse listeye YAZMAMAK dogru taraftir.
    Yanlis pozitif: bir kelimeyi basliga koymazsin (kucuk kayip).
    Yanlis negatif: rakip markayi basliga koyarsin, liste askiya alinir
    (buyuk kayip). Asimetri nedeniyle temkinli davranilir.
    """
    w = str(word or "").strip().lower()
    if not w:
        return False
    if w in (known or set()) or w in BILINEN_RAKIP_MARKALAR:
        return True
    # Sozlukte olmayan, tirelisiz, rakam iceren tekil kelimeler sikca marka
    if any(ch.isdigit() for ch in w) and len(w) >= 4:
        return True
    return False


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def winning_terms(search_terms, min_orders=1):
    """Satis ureten arama terimleri, tik basina ciroya gore sirali."""
    agg = defaultdict(lambda: {"clicks": 0, "spend": 0.0, "orders": 0, "sales": 0.0})
    for r in search_terms or []:
        t = str(r.get("term") or "").strip().lower()
        if not t or r.get("is_asin"):
            continue
        g = agg[t]
        g["clicks"] += _f(r.get("clicks"))
        g["spend"] += _f(r.get("spend"))
        g["orders"] += _f(r.get("orders"))
        g["sales"] += _f(r.get("sales"))
    out = []
    for t, g in agg.items():
        if g["orders"] < min_orders or g["sales"] <= 0:
            continue
        out.append({
            "term": t, **{k: round(v, 2) for k, v in g.items()},
            "rpc": round(g["sales"] / g["clicks"], 2) if g["clicks"] else 0,
            "roas": round(g["sales"] / g["spend"], 1) if g["spend"] else 0,
        })
    out.sort(key=lambda x: -x["sales"])
    return out


def keyword_themes(search_terms, min_clicks=3):
    """Tek tek terim degil TEMA analizi.

    Uzun kuyruk terimlerin her biri kucuktur; ama ayni kelimeyi iceren
    terimlerin toplami bir temayi gosterir. Basliga tek terim degil TEMA
    yazilir - "hair grow acondicionador" degil "acondicionador".
    """
    kazanan = defaultdict(lambda: {"clicks": 0, "spend": 0.0, "sales": 0.0, "terms": 0})
    for r in search_terms or []:
        t = str(r.get("term") or "").strip().lower()
        if not t or r.get("is_asin"):
            continue
        for w in set(t.split()):
            if w in STOP or len(w) < 3:
                continue
            g = kazanan[w]
            g["clicks"] += _f(r.get("clicks"))
            g["spend"] += _f(r.get("spend"))
            g["sales"] += _f(r.get("sales"))
            g["terms"] += 1
    guclu, zayif = [], []
    for w, g in kazanan.items():
        if g["clicks"] < min_clicks:
            continue
        kayit = {"theme": w, "terms": g["terms"], "clicks": round(g["clicks"]),
                 "spend": round(g["spend"], 2), "sales": round(g["sales"], 2),
                 "roas": round(g["sales"] / g["spend"], 1) if g["spend"] else 0}
        (guclu if g["sales"] > 0 else zayif).append(kayit)
    guclu.sort(key=lambda x: -x["roas"])
    zayif.sort(key=lambda x: -x["spend"])
    return {"winning": guclu, "wasting": zayif}


def suggest(search_terms, current_title="", brand_name="", product_type=""):
    """Baslik/bullet/arka plan onerisi uretir.

    Uydurma kelime ONERMEZ - yalnizca bu urunun reklam verisinde SATIS
    uretmis terimlerden calisir.
    """
    kazanan = winning_terms(search_terms)
    temalar = keyword_themes(search_terms)
    baslik = (current_title or "").lower()

    # Satis uretmis ama baslikta OLMAYAN temalar = en degerli bosluk
    kendi = {p.lower() for p in str(brand_name or "").split() if len(p) > 2}
    eksik, rakip_temalar = [], []
    for t in temalar["winning"][:25]:
        w = t["theme"]
        if w in YASAKLI or w in kendi:
            continue
        if looks_like_brand(w, kendi):
            # Reklamda kullanilabilir, listeye yazilamaz.
            rakip_temalar.append(t)
            continue
        if w not in baslik:
            eksik.append(t)

    # Baslikta olan ama para yakan temalar = cikarilmali
    cikar = []
    for t in temalar["wasting"][:15]:
        if t["theme"] in baslik and t["spend"] >= 20:
            cikar.append(t)

    # Ilk 80 karakter icin en degerli 3-5 tema
    oncelik = [t["theme"] for t in eksik[:5]]

    return {
        "winning_terms": kazanan[:20],
        "competitor_brands": rakip_temalar,
        "competitor_warning": (
            "Bu terimler satış üretiyor ama RAKİP MARKA adları. "
            "Reklamda hedeflemek meşrudur; başlığa/arka plana yazmak Amazon "
            "marka ihlalidir ve listeyi askıya aldırır."
            if rakip_temalar else None),
        "themes_winning": temalar["winning"][:15],
        "themes_wasting": temalar["wasting"][:10],
        "missing_from_title": eksik[:10],
        "remove_from_title": cikar,
        "title_priority": oncelik,
        "title_advice": (
            f"İlk {TITLE_PRIME} karaktere şunları koy (mobilde sadece bu görünür): "
            + ", ".join(oncelik) if oncelik else
            "Başlık zaten satış üreten temaları içeriyor."),
        "backend_keywords": _backend(kazanan, baslik),
        "rules": {
            "title_max": TITLE_MAX, "title_prime": TITLE_PRIME,
            "bullet_max": BULLET_MAX, "backend_max": BACKEND_MAX,
            "banned": sorted(YASAKLI),
        },
    }


def _backend(kazanan, baslik):
    """Arka plan arama terimleri: baslikta OLMAYAN kazanan kelimeler.

    Amazon baslikta zaten olan kelimeyi arka planda tekrar istemez -
    tekrar, 249 byte'lik degerli alani israf eder.
    """
    gorulen, out, boyut = set(), [], 0
    for k in kazanan:
        for w in k["term"].split():
            w = re.sub(r"[^a-z0-9']", "", w.lower())
            if not w or len(w) < 3 or w in STOP or w in gorulen or w in baslik:
                continue
            if looks_like_brand(w):
                continue      # rakip marka arka plana da yazilmaz
            if boyut + len(w) + 1 > BACKEND_MAX:
                break
            gorulen.add(w)
            out.append(w)
            boyut += len(w) + 1
    return {"keywords": out, "bytes": boyut, "limit": BACKEND_MAX}
