"""Yukleme sonrasi dogrulama: hesap gercekten istedigimiz halde mi?

NEDEN: "106/109 basarili" demek "hesap dogru" demek DEGILDIR. Basarili
yazilan bir deger yanlis deger olabilir, ya da dokunulmayan bir kampanya
eski hatali ayarini korumus olabilir. Bu modul hesabin SON HALINI kurallara
karsi denetler - ne yazildigina degil, ne oldugu bakar.
"""
import benchmarks
import bulk_doctor as BD

MIN_CLICKS_PER_DAY = BD.MIN_CLICKS_PER_DAY


def _g(bulk, row, key):
    return BD._get(bulk, row, key)


def audit(bulk, ceilings=None, expect_campaigns=None):
    """Canli hesabi denetler.

    ceilings: {"exact": 3.00, "auto": 2.29, ...} match type basina ekonomik
              tavan. Verilmezse teklif tavani kontrolu atlanir.
    expect_campaigns: bulunmasi beklenen kampanya adlari (or. hasat).
    """
    g = lambda r, k: _g(bulk, r, k)
    kam, ag, pa, kw, pt, badj = {}, {}, {}, {}, {}, {}
    ag_sayisi = {}
    for r in bulk["rows"]:
        e, cid = g(r, "Entity"), g(r, "Campaign ID")
        if e == "Campaign":
            kam[cid] = r
        elif e == "Ad Group":
            ag[cid] = r
            ag_sayisi[cid] = ag_sayisi.get(cid, 0) + 1
        elif e == "Product Ad":
            pa.setdefault(cid, []).append(r)
        elif e == "Keyword":
            kw.setdefault(cid, []).append(r)
        elif e == "Product Targeting":
            pt.setdefault(cid, []).append(r)
        elif e == "Bidding Adjustment":
            badj.setdefault(cid, []).append(r)

    aktif = {c: r for c, r in kam.items() if g(r, "State") == "enabled"}
    bulgular = []

    def ekle(agirlik, tur, kampanya, detay):
        bulgular.append({"severity": agirlik, "type": tur,
                         "campaign": str(kampanya or "")[:60], "detail": detay})

    # --- 1) Yapisal butunluk ---------------------------------------------
    for cid, r in aktif.items():
        ad = g(r, "Campaign Name")
        if ag_sayisi.get(cid, 0) == 0:
            ekle("kritik", "ad-group-yok", ad,
                 "aktif kampanyanin ad group'u yok - hic yayinlanamaz")
            continue
        if ag_sayisi.get(cid, 0) > 1:
            ekle("bilgi", "coklu-ad-group", ad,
                 f"{ag_sayisi[cid]} ad group - rapor okumasi zorlasir")
        if not pa.get(cid):
            ekle("kritik", "urun-reklami-yok", ad,
                 "aktif kampanyada urun reklami yok - hic yayinlanamaz")
        if not kw.get(cid) and not pt.get(cid):
            ekle("kritik", "hedefleme-yok", ad,
                 "ne kelime ne hedef var - hic yayinlanamaz")

    # --- 2) Butce tabani (olu kampanya) ----------------------------------
    for cid, r in aktif.items():
        ar = ag.get(cid)
        if ar is None:
            continue
        bid = BD._f(g(ar, "Ad Group Default Bid"))
        bu = BD._f(g(r, "Daily Budget"))
        if bid <= 0:
            ekle("kritik", "teklif-sifir", g(r, "Campaign Name"),
                 "ad group teklifi $0 - kampanya hic calisamaz")
            continue
        tik = bu / bid
        if tik < MIN_CLICKS_PER_DAY:
            ekle("kritik" if tik < 2 else "uyari", "olu-butce",
                 g(r, "Campaign Name"),
                 f"${bu:.0f} butce / ${bid:.2f} teklif = {tik:.1f} tik/gun "
                 f"(en az {MIN_CLICKS_PER_DAY} olmali, ${bid*MIN_CLICKS_PER_DAY:.0f} gerekir)")

    # --- 3) Ekonomik tavan ------------------------------------------------
    if ceilings:
        for cid, r in aktif.items():
            ar = ag.get(cid)
            if ar is None:
                continue
            bid = BD._f(g(ar, "Ad Group Default Bid"))
            tip = str(g(r, "Targeting Type") or "").lower()
            if tip == "auto":
                mk = "auto"
            else:
                tipler = [str(g(x, "Match Type") or "").lower() for x in kw.get(cid, [])]
                mk = max(set(tipler), key=tipler.count) if tipler else "exact"
            tv = ceilings.get(mk)
            if tv and bid > tv + 0.01:
                ekle("uyari", "tavan-asimi", g(r, "Campaign Name"),
                     f"teklif ${bid:.2f} > {mk} ekonomik tavani ${tv:.2f} "
                     f"(yapisal olarak %{bid/tv*100:.0f} ACOS)")

    # --- 4) Kelime gecerliligi -------------------------------------------
    import launch
    for cid, lst in kw.items():
        if cid not in aktif:
            continue
        for r in lst:
            if g(r, "State") != "enabled":
                continue
            metin = g(r, "Keyword Text")
            temiz, sebep = launch.sanitize_keyword(metin)
            if temiz is None:
                ekle("uyari", "gecersiz-kelime", g(kam[cid], "Campaign Name"),
                     f"'{str(metin)[:40]}' - {sebep}")

    # --- 5) Mukerrer kampanya adi ----------------------------------------
    adlar = {}
    for cid, r in kam.items():
        a = str(g(r, "Campaign Name") or "")
        adlar.setdefault(a, []).append(cid)
    for a, cids in adlar.items():
        if len(cids) > 1:
            ekle("kritik", "mukerrer-kampanya", a,
                 f"ayni adla {len(cids)} kampanya var")

    # --- 6) Beklenen kampanyalar geldi mi --------------------------------
    if expect_campaigns:
        mevcut = {str(g(r, "Campaign Name") or "") for r in kam.values()}
        for bekle in expect_campaigns:
            if not any(bekle in m for m in mevcut):
                ekle("kritik", "eksik-kampanya", bekle,
                     "beklenen kampanya hesapta yok - yukleme basarisiz olmus olabilir")

    # --- 7) Ozet ----------------------------------------------------------
    tb = sum(BD._f(g(r, "Daily Budget")) for r in aktif.values())
    u = BD.utilization(bulk)
    return {
        "campaigns_total": len(kam),
        "campaigns_live": len(aktif),
        "daily_budget": round(tb, 2),
        "utilization": u["utilization"],
        "budget_limited": u["budget_limited"],
        "demand_limited": u["demand_limited"],
        "findings": sorted(bulgular, key=lambda x: {"kritik": 0, "uyari": 1,
                                                    "bilgi": 2}[x["severity"]]),
        "critical": sum(1 for b in bulgular if b["severity"] == "kritik"),
        "warnings": sum(1 for b in bulgular if b["severity"] == "uyari"),
        "clean": not any(b["severity"] == "kritik" for b in bulgular),
    }


def ceilings_for(rows, brand_name=None, acos_ceiling=1.00):
    """Markanin olculmus verisinden match type basina ekonomik tavan."""
    bench = benchmarks.resolve(rows=rows, brand_name=brand_name)
    acct = bench.get("account") or {}
    out = {}
    for k in ("exact", "phrase", "broad", "auto", "pt"):
        aov = (bench.get("aov") or {}).get(k) or acct.get("aov")
        cvr = (bench.get("cvr") or {}).get(k) or acct.get("cvr")
        tv = benchmarks.economic_ceiling(aov, cvr, acos_ceiling)
        if tv > 0:
            out[k] = tv
    return out
