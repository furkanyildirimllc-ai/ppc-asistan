"""Otopilot - tek dosyadan tam analiz + tek aksiyon dosyasi.

NEDEN: kullanici Doktor / Buyume / Listing / Rekabet panellerini tek tek
gezmek zorundaydi ve her biri ayri dosya uretiyordu. Otopilot hepsini bir
kerede yapar, TEK duzeltme dosyasi cikarir.

IKI LISTE URETIR - ayrimi net tutmak onemli:
  did      : aracin YAPTIGI isler (duzeltme dosyasinda)
  todo     : yalnizca INSANIN yapabilecegi isler (liste, kupon, fiyat,
             paket). Bunlar reklam API'siyle degistirilemez; arac sadece
             ne yapilacagini ve neden onemli oldugunu soyler.

Boylece "arac ne yapti, bana ne kaldi" sorusu her zaman cevapli olur.
"""
import math
from collections import defaultdict

import benchmarks
import bulk_doctor as BD
import growth
import launch
import listing as listing_mod
import phases


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _kampanya_ozeti(bulk, days):
    g = lambda r, k: BD._get(bulk, r, k)
    ag = {g(r, "Campaign ID"): _f(g(r, "Ad Group Default Bid"))
          for r in bulk["rows"] if g(r, "Entity") == "Ad Group"}
    out = []
    for r in bulk["rows"]:
        if g(r, "Entity") != "Campaign" or g(r, "State") != "enabled":
            continue
        out.append({
            "name": str(g(r, "Campaign Name") or ""),
            "budget": _f(g(r, "Daily Budget")), "spend": _f(g(r, "Spend")),
            "sales": _f(g(r, "Sales")), "clicks": _f(g(r, "Clicks")),
            "orders": _f(g(r, "Orders")), "impressions": _f(g(r, "Impressions")),
            "bid": ag.get(g(r, "Campaign ID"), 0), "days": days,
        })
    return out


def _katman_verimi(bulk):
    """Kampanya ADI onekine gore katmanlari ayirir ve verimlerini olcer.

    Ayni ASIN'e birden fazla kampanya katmani reklam veriyorsa (elle
    kurulmus + arac urettigi gibi), hangisinin gercekten calistigi
    butce basina satisla gorulur. Uretmeyen katman butce tutar ama is
    yapmaz - kapatilmasi dogrudan kazanctir.
    """
    g = lambda r, k: BD._get(bulk, r, k)
    kat = defaultdict(lambda: {"n": 0, "budget": 0.0, "spend": 0.0,
                               "sales": 0.0, "impressions": 0.0, "ids": []})
    for r in bulk["rows"]:
        if g(r, "Entity") != "Campaign" or g(r, "State") != "enabled":
            continue
        ad = str(g(r, "Campaign Name") or "")
        # Onek = ilk "|" oncesi, yoksa ilk iki kelime
        onek = ad.split("|")[0].strip() if "|" in ad else " ".join(ad.split()[:2])
        k = kat[onek or "(adsiz)"]
        k["n"] += 1
        k["budget"] += _f(g(r, "Daily Budget"))
        k["spend"] += _f(g(r, "Spend"))
        k["sales"] += _f(g(r, "Sales"))
        k["impressions"] += _f(g(r, "Impressions"))
        k["ids"].append(g(r, "Campaign ID"))
    out = []
    for onek, k in kat.items():
        out.append({
            "prefix": onek, "campaigns": k["n"],
            "budget": round(k["budget"], 2), "spend": round(k["spend"], 2),
            "sales": round(k["sales"], 2), "impressions": round(k["impressions"]),
            "sales_per_budget": round(k["sales"] / k["budget"], 1) if k["budget"] else 0,
            "ids": k["ids"],
        })
    out.sort(key=lambda x: -x["sales_per_budget"])
    return out


def run(bulk, targeting_rows=None, search_term_rows=None, campaign_rows=None,
        monthly_target=5000, days=30, accepted_acos_pct=None,
        break_even_acos_pct=None, target_acos_pct=None, brand_name="",
        current_title=""):
    """Her seyi bir kerede yapar. Doner: (rapor, duzeltme_islemleri)."""
    tg = targeting_rows or []
    st = search_term_rows or []

    # ---- 1) Faz -----------------------------------------------------
    faz = phases.assess(tg, st, campaign_rows or [],
                        target_acos_pct=target_acos_pct,
                        break_even_acos_pct=break_even_acos_pct)

    hedef_acos = (accepted_acos_pct or break_even_acos_pct
                  or target_acos_pct or 100.0)

    # ---- 2) Hesap teshisi -------------------------------------------
    bench = benchmarks.resolve(rows=tg, brand_name=brand_name) if tg else None
    acct = (bench or {}).get("account") or {}
    cvr = acct.get("cvr") or 0.05
    teshis = BD.diagnose(bulk, hedef_acos, cvr,
                         fallback_bid=acct.get("cpc") or 2.00)
    kullanim = BD.utilization(bulk, days=days)

    # ---- 3) Uretmeyen katmanlar -------------------------------------
    katmanlar = _katman_verimi(bulk)
    uretken = [k for k in katmanlar if k["sales"] > 0]
    en_iyi = max((k["sales_per_budget"] for k in uretken), default=0)
    olu_katman = [k for k in katmanlar
                  if k["sales"] == 0 and k["budget"] >= 20
                  and k["impressions"] >= 100 and en_iyi > 0]

    # ---- 4) Hasat: kanitlanmis kelimeler -----------------------------
    kazanan = listing_mod.winning_terms(st)
    prior = cvr
    pazar = (bench or {}).get("cpc", {}).get("exact") or acct.get("cpc") or 2.00
    hasat = []
    for k in kazanan:
        temiz, sebep = launch.sanitize_keyword(k["term"])
        if not temiz:
            continue
        hasat.append({
            "keyword": temiz, "orders": k["orders"], "clicks": k["clicks"],
            "sales": k["sales"], "roas": k["roas"],
            "bid": benchmarks.keyword_bid(k["orders"], k["clicks"], k["sales"],
                                          prior, 1.00, pazar),
        })
    hasat.sort(key=lambda x: -x["sales"])

    # ---- 5) Buyume plani ---------------------------------------------
    kamp = _kampanya_ozeti(bulk, days)
    plan = growth.plan(kamp, monthly_target, days=days,
                       accepted_acos_pct=hedef_acos)
    im = sum(k["impressions"] for k in kamp)
    cl = sum(k["clicks"] for k in kamp)
    o = sum(k["orders"] for k in kamp)
    sa = sum(k["sales"] for k in kamp)
    ay = max(days / 30.0, 0.01)
    kaldiraclar = growth.gap_levers(
        plan["gap_monthly"], cl / ay, (o / cl if cl else 0),
        (sa / o if o else 0), (cl / im if im else 0), im / ay)

    # ---- 6) Listing -------------------------------------------------
    lst = listing_mod.suggest(st, current_title, brand_name) if st else None

    # ---- 7) Aksiyonlar: arac YAPAR ----------------------------------
    islemler = list(teshis["actions"])
    dokunulan = {a["campaign_id"] for a in islemler}
    g = lambda r, key: BD._get(bulk, r, key)
    butce_of = {g(r, "Campaign ID"): _f(g(r, "Daily Budget"))
                for r in bulk["rows"] if g(r, "Entity") == "Campaign"}
    ad_of = {g(r, "Campaign ID"): str(g(r, "Campaign Name") or "")
             for r in bulk["rows"] if g(r, "Entity") == "Campaign"}
    for k in olu_katman:
        for cid in k["ids"]:
            if cid in dokunulan:
                continue
            islemler.append({
                "campaign_id": cid, "ad_group_id": None,
                "campaign": ad_of.get(cid, k["prefix"]), "action": "pause",
                # Serbest kalan butceyi DOGRU raporlamak icin gercek deger.
                "budget": butce_of.get(cid, 0.0), "new_budget": 0,
                "bid": None, "new_bid": None,
                "reason": (f"üretmeyen katman: {k['campaigns']} kampanya, "
                           f"${k['budget']:.0f}/gün bütçe, {k['impressions']:.0f} "
                           f"gösterim, 0 satış"),
                "severity": "kritik"})
            dokunulan.add(cid)

    yaptim = []
    kapat = [a for a in islemler if a.get("action") == "pause"]
    butce = [a for a in islemler if a.get("action") != "pause"
             and abs(_f(a.get("new_budget")) - _f(a.get("budget"))) > 0.5]
    teklif = [a for a in islemler if a.get("action") != "pause"
              and a.get("new_bid") and abs(_f(a["new_bid"]) - _f(a.get("bid"))) > 0.01]
    if kapat:
        yaptim.append({"is": f"{len(kapat)} kampanya kapatıldı",
                       "detay": f"${sum(_f(a['budget']) for a in kapat):.0f}/gün bütçe serbest kaldı",
                       "nasil": "düzeltme dosyasında"})
    if butce:
        yaptim.append({"is": f"{len(butce)} kampanyanın bütçesi düzeltildi",
                       "detay": "bütçe ≥ teklif × 5 kuralı uygulandı (ölü kampanya kalmadı)",
                       "nasil": "düzeltme dosyasında"})
    if teklif:
        yaptim.append({"is": f"{len(teklif)} kampanyanın teklifi ayarlandı",
                       "detay": "ekonomik tavan ve hedef ACOS'a göre",
                       "nasil": "düzeltme dosyasında"})
    if hasat:
        yaptim.append({"is": f"{len(hasat)} kanıtlanmış kelime hasat edildi",
                       "detay": (f"toplam ${sum(h['sales'] for h in hasat):.0f} satış "
                                 f"üretmiş terimler, kelime bazında teklifle"),
                       "nasil": "hasat kampanyaları düzeltme dosyasında"})

    # ---- 8) Aksiyonlar: yalnizca INSAN yapabilir ---------------------
    yapamam = []
    ctr = (cl / im) if im else 0
    if ctr and ctr < 0.008:
        yapamam.append({
            "is": "Kupon aç (%5-10)",
            "neden": (f"CTR %{ctr*100:.2f} — gösterimlerin %{100-ctr*100:.1f}'i "
                      f"tıklanmıyor. Yeşil kupon rozeti CTR'yi tipik %30-60 artırır."),
            "nerede": "Seller Central → Reklam → Kuponlar",
            "sure": "10 dakika", "etki": "yüksek",
            "neden_ben_yapamam": "Kupon oluşturma reklam API'sinde değil"})
    if lst and lst.get("missing_from_title"):
        kelimeler = ", ".join(t["theme"] for t in lst["missing_from_title"][:5])
        yapamam.append({
            "is": f"Başlığa ekle: {kelimeler}",
            "neden": ("Bu kelimeler senin reklamında SATIŞ üretti ama başlıkta yok. "
                      "Başlıkta olmaları hem CTR'yi hem organik sıralamayı yükseltir."),
            "nerede": "Seller Central → Envanter → Düzenle → Başlık",
            "sure": "15 dakika", "etki": "yüksek",
            "neden_ben_yapamam": "Listing düzenleme Ads API kapsamı dışında"})
    if lst and lst.get("backend_keywords", {}).get("keywords"):
        bk = lst["backend_keywords"]
        yapamam.append({
            "is": f"Arka plan arama terimlerini doldur ({bk['bytes']}/{bk['limit']} byte)",
            "neden": "Satış üretmiş ama başlıkta olmayan kelimeler burada değerlendirilir.",
            "nerede": "Seller Central → Envanter → Düzenle → Anahtar Kelimeler",
            "sure": "5 dakika", "etki": "orta",
            "kopyala": " ".join(bk["keywords"]),
            "neden_ben_yapamam": "Listing düzenleme Ads API kapsamı dışında"})
    aov = (sa / o) if o else 0
    if aov and aov < 40:
        yapamam.append({
            "is": f"Paket/çoklu adet aç (sepet ${aov:.0f})",
            "neden": (f"Sepet ${aov:.0f}, pazar CPC'si ${pazar:.2f}. Bu matematik "
                      f"reklamla düzelmez — sepet büyümeden ACOS hedefe inmez."),
            "nerede": "Seller Central → Envanter → Varyasyon/Paket ekle",
            "sure": "1-2 gün", "etki": "çok yüksek",
            "neden_ben_yapamam": "Yeni ürün/varyasyon oluşturma Ads API'sinde değil"})
    if lst and lst.get("competitor_brands"):
        yapamam.append({
            "is": "Rakip marka terimlerini SADECE reklamda kullan",
            "neden": lst.get("competitor_warning") or "",
            "nerede": "—", "sure": "—", "etki": "risk önleme",
            "detay": ", ".join(t["theme"] for t in lst["competitor_brands"]),
            "neden_ben_yapamam": "Bu bir uyarı — yapılmaması gereken şey"})

    return {
        "phase": faz,
        "checklist": phases.checklist(faz),
        "diagnosis": {"actions": len(islemler),
                      "critical": sum(1 for a in islemler
                                      if a.get("severity") == "kritik"),
                      "utilization": kullanim["utilization"],
                      "budget_limited": kullanim["budget_limited"],
                      "demand_limited": kullanim["demand_limited"]},
        "layers": katmanlar,
        "dead_layers": olu_katman,
        "harvest": hasat[:60],
        "growth": plan,
        "levers": kaldiraclar,
        "listing": lst,
        "did": yaptim,
        "todo": yapamam,
        "funnel": {"impressions": round(im), "clicks": round(cl),
                   "orders": round(o), "sales": round(sa, 2),
                   "ctr_pct": round(ctr * 100, 2),
                   "cvr_pct": round(o / cl * 100, 2) if cl else 0,
                   "aov": round(aov, 2)},
    }, islemler
