"""Olculmus performans referanslari.

Lansman planindaki her sayi (bid, butce, tahmini ACOS) su zincire dayanir:

    max_cpc = AOV x beklenen_CVR x hedef_ACOS

Bu zincirdeki CVR ve pazar CPC'si daha once UYDURMA sabitlerdi
(kategori CVR %10, match carpanlari 1.30/0.65/0.70...). Uydurma sayilar
carpilinca sonuc ya gosterim almayacak kadar dusuk ya da absurd yuksek
cikiyordu.

Bu modul sirayla su kaynaklari dener:
  1) MARKANIN KENDI OLCULMUS VERISI  (report_rows -> gercek CPC/CVR)
  2) Ayni hesaptan turetilmis KALIBRE VARSAYILANLAR
  3) Hicbiri yoksa temkinli genel varsayilan

Her sonuc "source" ve "confidence" ile birlikte doner; kullaniciya hangi
sayinin olculdugu hangisinin tahmin oldugu acikca soylenir.
"""

# Gercek hesap verisinden kalibre edildi (Amazon SP, sac bakim kategorisi,
# ~6200 tiklama). Olculen degerler:
#   EXACT   CPC $3.00  CVR %15.15   (1914 tik)
#   PHRASE  CPC $3.16  CVR %14.64   (1639 tik)
#   AUTO    CPC $2.04  CVR % 5.57   (1956 tik)
#   ASIN/PT CPC $1.71  CVR % 7.72   ( 661 tik)
#   BROAD   CPC $1.92  CVR % 5.26   (  38 tik - dusuk guven)
#   Hesap geneli: CPC $2.60, CVR %11.2, AOV $36.95
CALIBRATION = {
    "source": "olculmus hesap verisi (~6200 tiklama, sac bakim)",
    "account_cpc": 2.60,
    "account_cvr": 0.112,
    "aov": 36.95,
    # Olgun (veri birikmis) listing icin match type bazinda CVR
    "cvr": {"exact": 0.1515, "phrase": 0.1464, "broad": 0.0526,
            "auto": 0.0557, "pt": 0.0772},
    # Hesap ortalama CPC'sine gore match type CPC carpani
    "cpc_factor": {"exact": 1.15, "phrase": 1.22, "broad": 0.74,
                   "auto": 0.78, "pt": 0.66},
}

# Yeni listing olgun listing kadar donusturmez: yorum yok, organik sira yok,
# Amazon henuz alaka ogrenmemis. Ilk 2-4 haftada olgun CVR'in ~%65'i beklenir.
LAUNCH_RAMP = 0.65

# Olculmus veriye guvenmek icin gereken minimum tiklama (match type basina).
MIN_CLICKS_TRUST = 100
# Bu esigin altinda ama ustunde veri varsa kismen harmanlanir.
MIN_CLICKS_BLEND = 25


def _norm_match(row):
    """Rapor satirini match type kovasina koy: exact/phrase/broad/auto/pt."""
    t = str(row.get("targeting") or "").lower()
    if t.startswith("asin") or t.startswith("category") or t.startswith("b0"):
        return "pt"
    mt = str(row.get("match_type") or "").strip().upper()
    if mt in ("EXACT", "PHRASE", "BROAD"):
        return mt.lower()
    # Auto kampanyalarda match type bos ya da "-" gelir
    return "auto"


def measure(rows):
    """Rapor satirlarindan match type bazinda GERCEK CPC/CVR olcer.

    rows: targeting veya search_term raporu satirlari (dict listesi).
    Doner: {match: {cpc, cvr, clicks, orders, spend, sales}} + "_account".
    """
    buckets = {}
    for r in rows or []:
        k = _norm_match(r)
        b = buckets.setdefault(k, dict(clicks=0, spend=0.0, orders=0, sales=0.0))
        b["clicks"] += r.get("clicks", 0) or 0
        b["spend"] += r.get("spend", 0) or 0.0
        b["orders"] += r.get("orders", 0) or 0
        b["sales"] += r.get("sales", 0) or 0.0

    out = {}
    tot = dict(clicks=0, spend=0.0, orders=0, sales=0.0)
    for k, b in buckets.items():
        for f in tot:
            tot[f] += b[f]
        if b["clicks"] > 0:
            out[k] = {
                "cpc": round(b["spend"] / b["clicks"], 4),
                "cvr": round(b["orders"] / b["clicks"], 4),
                "clicks": b["clicks"], "orders": b["orders"],
                "spend": round(b["spend"], 2), "sales": round(b["sales"], 2),
            }
    if tot["clicks"] > 0:
        out["_account"] = {
            "cpc": round(tot["spend"] / tot["clicks"], 4),
            "cvr": round(tot["orders"] / tot["clicks"], 4),
            "aov": round(tot["sales"] / tot["orders"], 2) if tot["orders"] else None,
            "acos": round(tot["spend"] / tot["sales"], 4) if tot["sales"] else None,
            "clicks": tot["clicks"], "orders": tot["orders"],
        }
    return out


def _blend(measured_val, default_val, clicks):
    """Az veri varsa olculen ile varsayilani karistir; cok veri varsa olculene guven."""
    if clicks >= MIN_CLICKS_TRUST:
        return measured_val, 1.0
    if clicks >= MIN_CLICKS_BLEND:
        w = (clicks - MIN_CLICKS_BLEND) / (MIN_CLICKS_TRUST - MIN_CLICKS_BLEND)
        return measured_val * w + default_val * (1 - w), w
    return default_val, 0.0


def resolve(rows=None, price=None, ramp=LAUNCH_RAMP, override_cpc=None):
    """Lansman icin kullanilacak CVR ve CPC referanslarini belirler.

    rows verilirse markanin kendi olcumu esas alinir; yetersizse kalibre
    varsayilanlarla harmanlanir. Sonuc her zaman hangi kaynaktan geldigini
    ve ne kadar guvenilir oldugunu soyler.
    """
    m = measure(rows) if rows else {}
    acct = m.get("_account") or {}

    cvr, cpc, conf, src = {}, {}, {}, {}
    for key, dflt_cvr in CALIBRATION["cvr"].items():
        got = m.get(key) or {}
        clicks = got.get("clicks", 0)
        v, w = _blend(got.get("cvr", dflt_cvr), dflt_cvr, clicks)
        # Olgun CVR -> lansman CVR
        cvr[key] = round(max(0.005, v * ramp), 4)
        conf[key] = round(w, 2)
        src[key] = ("olculdu" if w >= 1.0 else
                    "kismen olculdu" if w > 0 else "kalibre varsayilan")

        # CPC: once override, sonra olculen, sonra hesap ortalamasi x carpan
        if override_cpc:
            cpc[key] = round(float(override_cpc) * CALIBRATION["cpc_factor"][key], 2)
        elif clicks >= MIN_CLICKS_BLEND and got.get("cpc"):
            cpc[key] = round(got["cpc"], 2)
        elif acct.get("cpc"):
            cpc[key] = round(acct["cpc"] * CALIBRATION["cpc_factor"][key], 2)
        else:
            cpc[key] = round(CALIBRATION["account_cpc"]
                             * CALIBRATION["cpc_factor"][key], 2)

    if override_cpc:
        cpc_source = f"kullanici girdi (${float(override_cpc):.2f})"
    elif acct.get("cpc"):
        cpc_source = f"markanin olculmus CPC'si (${acct['cpc']:.2f}, {acct['clicks']:.0f} tik)"
    else:
        cpc_source = f"kalibre varsayilan (${CALIBRATION['account_cpc']:.2f})"

    return {
        "cvr": cvr,                    # lansman icin beklenen CVR (oran)
        "cpc": cpc,                    # match type bazinda beklenen CPC ($)
        "confidence": conf,            # 0-1, olculmus veri agirligi
        "cvr_source": src,
        "cpc_source": cpc_source,
        "ramp": ramp,
        "account": acct or None,
        "calibration_note": CALIBRATION["source"],
    }
