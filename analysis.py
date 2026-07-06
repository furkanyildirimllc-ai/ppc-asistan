"""Oneri motorlari: kelime avcisi, negatif kelime, bid optimizasyonu, placement.

Kullanilan endustri formulleri (AdLabs / AdBadger metodolojisi):
1. Yuksek ACOS  : yeni bid = RPC (satis/tiklama) x hedef ACOS
2. Harcayan-satmayan: yeni bid = (AOV / tiklama) x hedef ACOS
   tetik: harcama > hedef CPA (= hedef ACOS x AOV) ve 0 siparis
3. Dusuk ACOS   : ACOS < hedefin %80'i ve >=1 siparis -> bid +5..10%
4. Negatif esik : varsayilan 15+ tiklama ve 0 siparis (istatistiksel anlam),
   veya harcama > hedef CPA x 1.5 ve 0 siparis
5. Kesif->Exact tasima: 2-3+ siparis, ACOS <= hedef -> exact'e tasi + kaynakta negatifle
"""

# Auto kampanya hedefleme tipleri (search term raporundaki Targeting kolonu)
AUTO_TARGETS = {"loose-match", "close-match", "substitutes", "complements", "*"}

# Bu match tiplerindeki search termler kesif kaynagi sayilir
DISCOVERY_MATCH = {"BROAD", "PHRASE", "-"}


def _f(x, nd=2):
    return round(float(x), nd)


def _aov(search_terms):
    """Ortalama sepet tutari (AOV) - tum satisli satirlardan."""
    sales = sum(s["sales"] for s in search_terms)
    orders = sum(s["orders"] for s in search_terms)
    return sales / orders if orders else 30.0


def run_all(brand, search_terms, targets, placements=None):
    recs = []
    recs += harvest(brand, search_terms, targets)
    recs += negatives(brand, search_terms)
    recs += bids(brand, targets, _aov(search_terms) if search_terms else 30.0)
    recs += placement_recs(brand, placements or [])
    return recs


def _existing_exact_keywords(targets):
    return {t["targeting"].lower() for t in targets if t["match_type"] == "EXACT"}


def harvest(brand, search_terms, targets):
    """Kural 5: kesif kampanyalarindan kazanan termleri exact'e tasi."""
    tacos = brand["target_acos"]
    min_orders = brand["min_orders_harvest"]
    existing = _existing_exact_keywords(targets)
    agg = {}
    for st in search_terms:
        src_auto = st["targeting"].lower() in AUTO_TARGETS
        src_disc = st["match_type"] in DISCOVERY_MATCH
        if not (src_auto or src_disc):
            continue
        a = agg.setdefault(st["term"], {
            "clicks": 0, "spend": 0, "sales": 0, "orders": 0,
            "campaigns": set(), "is_asin": st.get("is_asin", False)})
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["sales"] += st["sales"]
        a["orders"] += st["orders"]
        a["campaigns"].add(st["campaign"])
    recs = []
    for term, a in agg.items():
        if a["orders"] < min_orders or a["spend"] <= 0 or a["sales"] <= 0:
            continue
        acos = a["spend"] / a["sales"]
        if acos > tacos:
            continue
        if not a["is_asin"] and term in existing:
            continue
        # RPC x hedef ACOS = hedefe gore odenebilir maksimum tik maliyeti
        rpc = a["sales"] / a["clicks"] if a["clicks"] else 0
        cpc = a["spend"] / a["clicks"] if a["clicks"] else 0.5
        bid = min(rpc * tacos, cpc * 1.25) if rpc else cpc
        bid = max(0.15, _f(bid))
        label = "urun hedefleme (ASIN)" if a["is_asin"] else "exact keyword"
        recs.append({
            "type": "harvest_pt" if a["is_asin"] else "harvest",
            "campaign": ", ".join(sorted(a["campaigns"])),
            "ad_group": "",
            "keyword": term,
            "match_type": "PRODUCT" if a["is_asin"] else "EXACT",
            "current_value": None,
            "suggested_value": bid,
            "reason": (f"{int(a['orders'])} siparis, ACOS %{_f(acos*100,1)} "
                       f"(hedef %{_f(tacos*100,0)}). Bid = RPC ${_f(rpc)} x hedef ACOS. "
                       f"Exact kampanyaya {label} olarak ekle, SONRA kaynak "
                       f"kampanyada NEGATIF EXACT olarak ekle (cift harcama onlenir)."),
            "metrics": {"clicks": int(a["clicks"]), "spend": _f(a["spend"]),
                        "sales": _f(a["sales"]), "orders": int(a["orders"]),
                        "acos": _f(acos * 100, 1)},
        })
    recs.sort(key=lambda r: -r["metrics"]["sales"])
    return recs


def negatives(brand, search_terms):
    """Kural 4: tiklama esigi VEYA harcama esigi asilip 0 siparis -> negatifle."""
    min_clicks = brand["min_clicks_neg"]
    tacos = brand["target_acos"]
    aov = _aov(search_terms)
    spend_cap = tacos * aov * 1.5  # hedef CPA'nin 1.5 kati harcama = kesin israf
    agg = {}
    for st in search_terms:
        key = (st["campaign"], st["term"])
        a = agg.setdefault(key, {"clicks": 0, "spend": 0, "orders": 0,
                                 "is_asin": st.get("is_asin", False)})
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["orders"] += st["orders"]
    recs = []
    for (campaign, term), a in agg.items():
        if a["orders"] > 0:
            continue
        by_clicks = a["clicks"] >= min_clicks
        by_spend = a["spend"] >= spend_cap
        if not (by_clicks or by_spend):
            continue
        trigger = (f"{int(a['clicks'])} tiklama (esik: {min_clicks})" if by_clicks
                   else f"${_f(a['spend'])} harcama > hedef CPA x1.5 (${_f(spend_cap)})")
        recs.append({
            "type": "negative",
            "campaign": campaign,
            "ad_group": "",
            "keyword": term,
            "match_type": "NEGATIVE PRODUCT" if a["is_asin"] else "NEGATIVE EXACT",
            "current_value": None,
            "suggested_value": None,
            "reason": (f"{trigger}, 0 siparis, ${_f(a['spend'])} israf. "
                       f"Kampanyada Negative targeting bolumune "
                       f"{'ASIN olarak' if a['is_asin'] else 'negatif exact olarak'} ekle."),
            "metrics": {"clicks": int(a["clicks"]), "spend": _f(a["spend"]),
                        "sales": 0, "orders": 0, "acos": None},
        })
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def bids(brand, targets, aov):
    """Kural 1-3: RPC bazli bid onerileri (targeting raporundan)."""
    tacos = brand["target_acos"]
    cap = brand.get("bid_change_cap", 0.25)
    target_cpa = tacos * aov
    recs = []
    for t in targets:
        if t["match_type"] not in ("EXACT", "PHRASE", "BROAD") \
                and not t["targeting"].lower().startswith("asin"):
            continue
        clicks, spend, sales, orders, cpc = (
            t["clicks"], t["spend"], t["sales"], t["orders"], t["cpc"])
        if clicks < 5 or cpc <= 0:
            continue
        acos = spend / sales if sales > 0 else None
        rpc = sales / clicks if clicks else 0
        if orders == 0 and spend >= target_cpa:
            # Kural 2: harcayan-satmayan -> bid = (AOV / tiklama) x hedef ACOS
            new_bid = max(0.15, _f((aov / clicks) * tacos))
            rtype = "bid_down"
            reason = (f"${_f(spend)} harcama (hedef CPA ${_f(target_cpa)} asildi), "
                      f"0 siparis. Formul: (AOV ${_f(aov)} / {int(clicks)} tik) x "
                      f"%{_f(tacos*100,0)}. Dusmeye devam ederse duraklat.")
        elif acos is not None and acos > tacos * 1.15:
            # Kural 1: yuksek ACOS -> bid = RPC x hedef ACOS
            ideal = rpc * tacos
            new_bid = max(0.15, _f(max(ideal, cpc * (1 - cap))))
            rtype = "bid_down"
            reason = (f"ACOS %{_f(acos*100,1)} > hedef %{_f(tacos*100,0)}. "
                      f"Formul: RPC ${_f(rpc)} x hedef ACOS = ${_f(ideal)}"
                      + (f" (tek seferde max -%{int(cap*100)} sinirlandi)"
                         if ideal < cpc * (1 - cap) else "") + ".")
        elif acos is not None and acos < tacos * 0.80 and orders >= 1:
            # Kural 3: dusuk ACOS (%20 tampon) -> +5..10%
            pct = 0.10 if acos < tacos * 0.5 else 0.05
            new_bid = _f(cpc * (1 + pct))
            rtype = "bid_up"
            reason = (f"ACOS %{_f(acos*100,1)} hedefin %20+ altinda, "
                      f"{int(orders)} siparis. Bid +%{int(pct*100)} artir, "
                      f"1 hafta izle, hala dusukse tekrar artir.")
        else:
            continue
        if abs(new_bid - cpc) < 0.03:
            continue
        recs.append({
            "type": rtype,
            "campaign": t["campaign"],
            "ad_group": t["ad_group"],
            "keyword": t["targeting"],
            "match_type": t["match_type"],
            "current_value": _f(cpc),
            "suggested_value": new_bid,
            "reason": reason,
            "metrics": {"clicks": int(clicks), "spend": _f(spend),
                        "sales": _f(sales), "orders": int(orders),
                        "acos": _f(acos * 100, 1) if acos is not None else None},
        })
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


PLACEMENT_LABELS = {
    "Top of Search on-Amazon": "Top of search (ilk sayfa ustu)",
    "Detail Page on-Amazon": "Urun sayfalari",
    "Product pages on Amazon": "Urun sayfalari",
    "Other on-Amazon": "Rest of search",
}


def placement_recs(brand, placements):
    """Placement raporundan: TOS cok iyi calisiyorsa carpan artir, kotuyse dusur."""
    tacos = brand["target_acos"]
    recs = []
    by_camp = {}
    for p in placements:
        by_camp.setdefault(p["campaign"], []).append(p)
    for campaign, rows in by_camp.items():
        for p in rows:
            if p["clicks"] < 10 or p["spend"] <= 0:
                continue
            acos = p["spend"] / p["sales"] if p["sales"] > 0 else None
            label = PLACEMENT_LABELS.get(p["placement"], p["placement"])
            is_tos = "Top of Search" in p["placement"]
            if acos is not None and acos < tacos * 0.7 and p["orders"] >= 2 and is_tos:
                recs.append(_prec(campaign, label, "+%25-50 carpan",
                    f"TOS ACOS %{_f(acos*100,1)} hedefin cok altinda, {int(p['orders'])} "
                    f"siparis. Kampanya ayarlari > Adjust bids by placement > Top of "
                    f"search carpanini kademeli artir (once +%25).", p, acos))
            elif acos is not None and acos > tacos * 1.5:
                recs.append(_prec(campaign, label, "carpani sifirla / bid dusur",
                    f"{label} ACOS %{_f(acos*100,1)} hedefin 1.5 kati. Bu placement "
                    f"carpani varsa sifirla; yoksa kampanya bidlerini gozden gecir.",
                    p, acos))
            elif acos is None and p["spend"] >= tacos * 30 * 1.5:
                recs.append(_prec(campaign, label, "carpani sifirla",
                    f"{label}: ${_f(p['spend'])} harcama, 0 satis. Bu placement icin "
                    f"carpan varsa kaldir.", p, None))
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def _prec(campaign, label, action, reason, p, acos):
    return {
        "type": "placement",
        "campaign": campaign,
        "ad_group": "",
        "keyword": label,
        "match_type": "PLACEMENT",
        "current_value": None,
        "suggested_value": None,
        "reason": f"[{action}] {reason}",
        "metrics": {"clicks": int(p["clicks"]), "spend": _f(p["spend"]),
                    "sales": _f(p["sales"]), "orders": int(p["orders"]),
                    "acos": _f(acos * 100, 1) if acos is not None else None},
    }
