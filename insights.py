"""Insights motoru - dashboard icin sayilar + kartlar + oncelikler uretir.

Cikti dashboard() fonksiyonundan gelir; UI direkt tuketir.
"""
from collections import defaultdict


def _acos(spend, sales):
    return (spend / sales) if sales > 0 else None


def wasted_spend(search_terms):
    """0 siparis getiren tum arama terimlerinin toplam harcamasi."""
    agg = defaultdict(lambda: {"clicks": 0, "spend": 0, "orders": 0,
                               "campaigns": set()})
    for st in search_terms:
        key = st["term"]
        a = agg[key]
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["orders"] += st["orders"]
        a["campaigns"].add(st["campaign"])
    dead = [{"term": k, "clicks": int(v["clicks"]), "spend": round(v["spend"], 2),
             "campaigns": len(v["campaigns"])}
            for k, v in agg.items()
            if v["orders"] == 0 and v["spend"] > 0]
    dead.sort(key=lambda r: -r["spend"])
    total = round(sum(r["spend"] for r in dead), 2)
    return {"total": total, "count": len(dead), "top": dead[:10]}


def opportunities(search_terms, targets, brand):
    """Harvest edilecek + bid artirilacak firsatlarin toplam beklenen katkisi."""
    tacos = brand["target_acos"]
    # Harvest firsatlari - satis getiren, exact'te olmayan terimler
    existing_exact = {t["targeting"].lower()
                      for t in targets if t["match_type"] == "EXACT"}
    agg = defaultdict(lambda: {"clicks": 0, "spend": 0, "sales": 0, "orders": 0})
    for st in search_terms:
        if st["match_type"] not in ("BROAD", "PHRASE", "-"):
            continue
        a = agg[st["term"]]
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["sales"] += st["sales"]
        a["orders"] += st["orders"]
    harvest_ready = []
    for term, v in agg.items():
        if v["orders"] < 1 or v["sales"] <= 0:
            continue
        acos = v["spend"] / v["sales"]
        if acos > tacos or term in existing_exact:
            continue
        harvest_ready.append({"term": term, "orders": int(v["orders"]),
                              "sales": round(v["sales"], 2),
                              "acos": round(acos * 100, 1)})
    harvest_ready.sort(key=lambda r: -r["sales"])
    # Bid up firsatlari
    bid_up = []
    for t in targets:
        if t["clicks"] < 5 or t["sales"] <= 0:
            continue
        acos = t["spend"] / t["sales"]
        if acos < tacos * 0.8 and t["orders"] >= 1:
            bid_up.append({"term": t["targeting"], "acos": round(acos * 100, 1),
                           "orders": int(t["orders"]),
                           "sales": round(t["sales"], 2)})
    bid_up.sort(key=lambda r: -r["sales"])
    est_sales = round(sum(r["sales"] for r in harvest_ready[:20]) * 0.3, 2)
    return {
        "harvest_count": len(harvest_ready),
        "harvest_top": harvest_ready[:5],
        "bidup_count": len(bid_up),
        "bidup_top": bid_up[:5],
        "estimated_monthly_upside_usd": est_sales,
    }


def lost_impressions(targets, brand):
    """TOS impression share dusuk ama satis getiren kelimeler."""
    tacos = brand["target_acos"]
    losing = []
    for t in targets:
        if t["sales"] <= 0 or t["orders"] < 1:
            continue
        acos = t["spend"] / t["sales"]
        if acos > tacos:
            continue
        tos_is = t.get("tos_is", 0) or 0
        if tos_is > 0 and tos_is < 0.5:
            losing.append({"term": t["targeting"], "campaign": t["campaign"],
                           "tos_is_pct": round(tos_is * 100, 1),
                           "acos_pct": round(acos * 100, 1),
                           "sales": round(t["sales"], 2),
                           "cpc": round(t["cpc"], 2),
                           "suggested_bid": round(t["cpc"] * 1.25, 2)})
    losing.sort(key=lambda r: (r["tos_is_pct"], -r["sales"]))
    return {"count": len(losing), "top": losing[:8]}


def dead_keywords(targets):
    """Hic impression'i olmayan veya cok az olan kelimeler - pause aday."""
    dead = []
    for t in targets:
        imp = t.get("impressions", 0)
        if imp < 100 and t["spend"] < 1:
            dead.append({"term": t["targeting"], "campaign": t["campaign"],
                         "impressions": int(imp), "match_type": t["match_type"]})
    return {"count": len(dead), "top": dead[:8]}


def bid_conflicts(targets):
    """Ayni kelime birden fazla kampanyada aktif."""
    by_term = defaultdict(list)
    for t in targets:
        if t["clicks"] < 1:
            continue
        by_term[t["targeting"].lower()].append({
            "campaign": t["campaign"], "match_type": t["match_type"],
            "cpc": round(t["cpc"], 2), "sales": round(t["sales"], 2),
            "orders": int(t["orders"]),
        })
    conflicts = [{"term": k, "instances": v}
                 for k, v in by_term.items() if len(v) > 1]
    conflicts.sort(key=lambda c: -sum(i["sales"] for i in c["instances"]))
    return {"count": len(conflicts), "top": conflicts[:8]}


def health_score(brand, search_terms, targets, wasted, oppo, lost_is):
    """0-100 saglik skoru. 4 boyut: verim, negatif kalitesi, firsat kaciran, kayip IS."""
    tacos = brand["target_acos"]
    total_spend = sum(t["spend"] for t in targets) or 1
    total_sales = sum(t["sales"] for t in targets)
    acos = total_spend / total_sales if total_sales > 0 else 2.0
    # 1. Verim (ACOS/hedef) - 40 puan
    ratio = acos / tacos if tacos else 1
    eff = max(0, min(40, 40 * (1.5 - ratio)))
    # 2. Wasted spend orani - 25 puan (dusukse iyi)
    waste_ratio = wasted["total"] / total_spend if total_spend > 0 else 0
    waste_score = max(0, 25 * (1 - waste_ratio * 3))
    # 3. Firsat kacirma - 20 puan (harvest bekleyen kelime az olmali)
    harv = oppo["harvest_count"]
    oppo_score = max(0, 20 - harv * 1.5)
    # 4. Kayip impression share - 15 puan
    is_score = max(0, 15 - lost_is["count"] * 1.5)
    total = round(eff + waste_score + oppo_score + is_score)
    # Renk
    if total >= 75:
        color, label = "green", "Saglikli"
    elif total >= 50:
        color, label = "orange", "Gelistirilmeli"
    else:
        color, label = "red", "Acil mudahale"
    return {
        "score": max(0, min(100, total)),
        "color": color, "label": label,
        "breakdown": {
            "verim": round(eff), "israf_kontrolu": round(waste_score),
            "firsat_yakalama": round(oppo_score), "gorunurluk": round(is_score),
        },
        "acos_pct": round(acos * 100, 1) if total_sales > 0 else None,
        "target_acos_pct": round(tacos * 100, 1),
    }


def priorities(brand, wasted, oppo, lost_is, dead, conflicts, det_recs):
    """Bugun yapman gereken 5 sey - siraya dizilmis."""
    tacos = brand["target_acos"]
    items = []
    # 1. Wasted spend kritikse en ust
    if wasted["total"] > 50:
        items.append({
            "priority": "critical",
            "icon": "🩸",
            "title": f"${wasted['total']} kanama durdurulmali",
            "detail": f"{wasted['count']} arama terimi 0 siparis getirdi. "
                      f"Negatifler sekmesinden onayla.",
            "action": "negatifleri-onayla",
        })
    # 2. Yuksek gelirli harvest
    if oppo["harvest_top"]:
        top = oppo["harvest_top"][0]
        items.append({
            "priority": "high", "icon": "🌱",
            "title": f"'{top['term']}' exact'e tasi (${top['sales']} satis)",
            "detail": f"ACOS %{top['acos']} - hedefin altinda. "
                      f"Toplam {oppo['harvest_count']} harvest bekliyor.",
            "action": "kelime-avcisi",
        })
    # 3. Impression kaybi
    if lost_is["top"]:
        top = lost_is["top"][0]
        items.append({
            "priority": "high", "icon": "👀",
            "title": f"'{top['term']}' TOS'ta %{top['tos_is_pct']} gorunurluk",
            "detail": f"Satis getiriyor (${top['sales']}) ama ekranin ustunde "
                      f"kaybediyor. Bid ${top['cpc']} -> ${top['suggested_bid']}.",
            "action": "bid-artir",
        })
    # 4. Bid catismasi
    if conflicts["count"] > 0:
        items.append({
            "priority": "medium", "icon": "⚔️",
            "title": f"{conflicts['count']} kelime birden fazla kampanyada",
            "detail": "Kampanyalarin birbiriyle acik artirmaya girmesi. "
                      "Kazanani sec, digerine negatif ekle.",
            "action": "bid-catismasi",
        })
    # 5. Olu kelimeler
    if dead["count"] > 20:
        items.append({
            "priority": "medium", "icon": "💀",
            "title": f"{dead['count']} kelime hic gorunmuyor",
            "detail": "Impression yok / cok az - alaka skoru dusuk olabilir. "
                      "Duraklat veya bid dusur.",
            "action": "olu-kelimeler",
        })
    # 6. AI'yi cagir
    if len(items) < 5:
        items.append({
            "priority": "info", "icon": "🤖",
            "title": "AI stratejisi henuz uretilmedi (veya eski)",
            "detail": "Kampanya buyume plani icin AI'yi cagir.",
            "action": "ai-strateji",
        })
    return items[:5]


def campaign_spend_distribution(campaigns, limit=10):
    """Kampanya bazli harcama pastasi."""
    sorted_c = sorted(campaigns, key=lambda c: -c["spend"])[:limit]
    total = sum(c["spend"] for c in campaigns) or 1
    return [{
        "campaign": c["campaign"],
        "spend": round(c["spend"], 2),
        "share_pct": round(c["spend"] / total * 100, 1),
        "acos_pct": round(c["spend"] / c["sales"] * 100, 1) if c["sales"] > 0 else None,
        "orders": int(c["orders"]),
    } for c in sorted_c]


def match_type_distribution(search_terms):
    """Match type bazli spend/sales."""
    agg = defaultdict(lambda: {"spend": 0, "sales": 0, "orders": 0})
    for st in search_terms:
        mt = st["match_type"] or "UNKNOWN"
        a = agg[mt]
        a["spend"] += st["spend"]
        a["sales"] += st["sales"]
        a["orders"] += st["orders"]
    return [{"match_type": k, "spend": round(v["spend"], 2),
             "sales": round(v["sales"], 2), "orders": int(v["orders"])}
            for k, v in agg.items()]


def upload_trend(uploads):
    """Yukleme geciminden trend. Zamansiz yaklasik grafik."""
    return [{"date": u["uploaded_at"][:10], "filename": u["filename"],
             "type": u["report_type"], "rows": u["row_count"]}
            for u in uploads[::-1]]


def skag_candidates(targets, brand):
    """Yuksek hacimli kazanan exact kelimeler - SKAG'a tasinabilir."""
    tacos = brand["target_acos"]
    out = []
    for t in targets:
        if t["match_type"] != "EXACT":
            continue
        if t["orders"] < 5 or t["sales"] <= 0:
            continue
        acos = t["spend"] / t["sales"]
        if acos > tacos * 0.9:
            continue
        out.append({
            "keyword": t["targeting"], "campaign": t["campaign"],
            "orders": int(t["orders"]), "sales": round(t["sales"], 2),
            "acos_pct": round(acos * 100, 1),
            "cpc": round(t["cpc"], 2),
        })
    out.sort(key=lambda r: -r["sales"])
    return {"count": len(out), "top": out[:5]}


def tos_multiplier_opportunities(placements, brand):
    """TOS'ta iyi cevriliyor ama carpan yok -> multiplier oner."""
    tacos = brand["target_acos"]
    out = []
    for p in placements:
        if "Top of Search" not in p.get("placement", ""):
            continue
        if p["orders"] < 3 or p["sales"] <= 0:
            continue
        acos = p["spend"] / p["sales"]
        if acos > tacos * 0.7:
            continue
        # TOS ACOS hedefin %70 altinda + 3+ siparis = multiplier fırsatı
        multiplier_pct = 25 if acos > tacos * 0.5 else 50
        out.append({
            "campaign": p["campaign"],
            "tos_acos_pct": round(acos * 100, 1),
            "orders": int(p["orders"]),
            "sales": round(p["sales"], 2),
            "suggested_multiplier_pct": multiplier_pct,
        })
    out.sort(key=lambda r: -r["sales"])
    return {"count": len(out), "top": out[:5]}


def brand_defense_check(search_terms, campaigns):
    """Kendi ASIN'inin kendi urun sayfasinda gorunup gorunmedigi (proksil)."""
    # Kampanya adlarindan "brand defense" veya "defense" iceren var mi?
    has_defense = any("defense" in c.get("campaign", "").lower() or
                      "brand" in c.get("targeting_type", "").lower()
                      for c in campaigns)
    return {
        "has_brand_defense_campaign": has_defense,
        "recommendation": None if has_defense else
            "Brand Defense kampanyan yok. Rakip senin urun sayfanda reklam yapiyor "
            "olabilir. SP + SD ile kendi ASIN'ini kendi ASIN'inle target eden bir "
            "kampanya kur."
    }


def campaign_momentum(campaigns, brand):
    """Yuksek harcama + kotu ACOS = mudahale ihtiyaci. Dusuk harcama + iyi ACOS = buyume firsati."""
    tacos = brand["target_acos"]
    scale_up, scale_down = [], []
    for c in campaigns:
        if c.get("status", "").lower() == "paused":
            continue
        if c["clicks"] < 20:
            continue
        if c["sales"] <= 0:
            if c["spend"] > 30:
                scale_down.append({
                    "campaign": c["campaign"], "spend": round(c["spend"], 2),
                    "reason": "harcama var, 0 satis",
                })
            continue
        acos = c["spend"] / c["sales"]
        # Iyi performans + gunluk butcenin buyugu = buyut
        if acos < tacos * 0.7 and c.get("budget", 0) > 0:
            budget_utilization = c["spend"] / (c["budget"] * 30) if c["budget"] > 0 else 0
            if budget_utilization > 0.6:
                scale_up.append({
                    "campaign": c["campaign"], "acos_pct": round(acos * 100, 1),
                    "spend": round(c["spend"], 2), "sales": round(c["sales"], 2),
                    "current_budget": round(c["budget"], 2),
                    "suggested_budget": round(c["budget"] * 1.5, 2),
                    "reason": f"ACOS %{acos*100:.1f} hedefin altinda, butce dolduruluyor",
                })
        elif acos > tacos * 1.5:
            scale_down.append({
                "campaign": c["campaign"], "acos_pct": round(acos * 100, 1),
                "spend": round(c["spend"], 2),
                "reason": f"ACOS %{acos*100:.1f} hedefin 1.5 kati",
            })
    scale_up.sort(key=lambda r: -r["sales"])
    scale_down.sort(key=lambda r: -r["spend"])
    return {"scale_up": scale_up[:5], "scale_down": scale_down[:5]}


def kpi_ribbon(search_terms, targets, campaigns):
    """Ust duzey 8 metrik: harcama, satis, ACOS, RoAS, siparis, tik, CTR, CVR."""
    src = campaigns if campaigns else (targets if targets else search_terms)
    impressions = sum(r.get("impressions", 0) for r in src)
    clicks = sum(r.get("clicks", 0) for r in src)
    spend = sum(r.get("spend", 0) for r in src)
    sales = sum(r.get("sales", 0) for r in src)
    orders = sum(r.get("orders", 0) for r in src)
    ctr = (clicks / impressions * 100) if impressions else 0
    cvr = (orders / clicks * 100) if clicks else 0
    acos = (spend / sales * 100) if sales else None
    roas = (sales / spend) if spend else 0
    return {
        "spend": round(spend, 2),
        "sales": round(sales, 2),
        "orders": int(orders),
        "clicks": int(clicks),
        "impressions": int(impressions),
        "ctr_pct": round(ctr, 2),
        "cvr_pct": round(cvr, 2),
        "acos_pct": round(acos, 1) if acos is not None else None,
        "roas": round(roas, 2),
        "avg_cpc": round(spend / clicks, 2) if clicks else 0,
        "avg_order_value": round(sales / orders, 2) if orders else 0,
        "cost_per_order": round(spend / orders, 2) if orders else 0,
    }


def portfolio_stats(targets, campaigns):
    """Portfolyo yapisi metrikleri - kampanya/kelime sayilari, match dagilimi."""
    match_counts = defaultdict(int)
    match_spend = defaultdict(float)
    for t in targets:
        mt = t.get("match_type") or "OTHER"
        match_counts[mt] += 1
        match_spend[mt] += t.get("spend", 0)
    # Kampanya yapisi
    active = sum(1 for c in campaigns if c.get("status", "").lower() in ("enabled", "aktif"))
    paused = sum(1 for c in campaigns if c.get("status", "").lower() == "paused")
    total_budget = sum(c.get("budget", 0) for c in campaigns)
    types = defaultdict(int)
    for c in campaigns:
        tt = (c.get("targeting_type") or "Bilinmiyor").lower()
        types[tt] += 1
    return {
        "total_campaigns": len(campaigns),
        "active_campaigns": active,
        "paused_campaigns": paused,
        "total_daily_budget": round(total_budget, 2),
        "avg_daily_budget": round(total_budget / len(campaigns), 2) if campaigns else 0,
        "campaign_targeting_types": dict(types),
        "total_targets": len(targets),
        "match_distribution": {
            k: {"count": v, "spend": round(match_spend[k], 2)}
            for k, v in match_counts.items()
        },
    }


def best_worst(campaigns, brand):
    """En verimli / en verimsiz kampanyalar."""
    tacos = brand["target_acos"]
    scored = []
    for c in campaigns:
        if c["clicks"] < 10:
            continue
        if c["sales"] <= 0:
            scored.append((999, c, "0 satis"))
            continue
        acos = c["spend"] / c["sales"]
        scored.append((acos, c, f"ACOS %{acos*100:.1f}"))
    scored.sort(key=lambda x: x[0])
    def _pack(entry):
        acos_ratio, c, label = entry
        return {
            "campaign": c["campaign"], "spend": round(c["spend"], 2),
            "sales": round(c["sales"], 2), "orders": int(c["orders"]),
            "acos_pct": round(acos_ratio * 100, 1) if acos_ratio < 999 else None,
            "label": label,
            "vs_target": round((acos_ratio / tacos - 1) * 100, 1) if acos_ratio < 999 else None,
        }
    return {
        "best": [_pack(x) for x in scored[:3]],
        "worst": [_pack(x) for x in scored[-3:][::-1]],
    }


def placement_split(placements):
    """Yer bazli spend/sales dagilimi + en iyi CVR yer."""
    if not placements:
        return None
    agg = defaultdict(lambda: {"spend": 0, "sales": 0, "orders": 0, "clicks": 0})
    for p in placements:
        pl = p.get("placement", "Bilinmiyor")
        key = ("Top of Search" if "Top of Search" in pl
               else "Product Pages" if "Detail" in pl or "Product" in pl
               else "Rest of Search")
        a = agg[key]
        a["spend"] += p.get("spend", 0)
        a["sales"] += p.get("sales", 0)
        a["orders"] += p.get("orders", 0)
        a["clicks"] += p.get("clicks", 0)
    total_spend = sum(a["spend"] for a in agg.values()) or 1
    out = []
    for k, v in agg.items():
        out.append({
            "placement": k,
            "spend": round(v["spend"], 2),
            "share_pct": round(v["spend"] / total_spend * 100, 1),
            "sales": round(v["sales"], 2),
            "acos_pct": round(v["spend"] / v["sales"] * 100, 1) if v["sales"] > 0 else None,
            "cvr_pct": round(v["orders"] / v["clicks"] * 100, 2) if v["clicks"] > 0 else 0,
        })
    out.sort(key=lambda r: -r["spend"])
    return out


def top_search_terms(search_terms, limit=5):
    """En cok satan arama terimleri (kelime aramasi degil, gercek muster ne yazdi)."""
    agg = defaultdict(lambda: {"clicks": 0, "spend": 0, "sales": 0, "orders": 0})
    for st in search_terms:
        a = agg[st["term"]]
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["sales"] += st["sales"]
        a["orders"] += st["orders"]
    ranked = sorted(agg.items(), key=lambda x: -x[1]["sales"])[:limit]
    return [{
        "term": t, "sales": round(v["sales"], 2),
        "orders": int(v["orders"]), "spend": round(v["spend"], 2),
        "acos_pct": round(v["spend"] / v["sales"] * 100, 1) if v["sales"] > 0 else None,
    } for t, v in ranked if v["sales"] > 0]


def campaign_advisor(brand, search_terms, targets, placements, campaigns,
                     top_n=8):
    """Her aktif kampanya icin spesifik aksiyon listesi uretir.
    Yuksek harcamali ve/veya acil sorunlu kampanyalar oncelikli.
    """
    tacos = brand["target_acos"]
    aov_default = 30.0
    total_sales = sum(t.get("sales", 0) for t in search_terms)
    total_orders = sum(t.get("orders", 0) for t in search_terms)
    aov = (total_sales / total_orders) if total_orders else aov_default

    # Kannibalizm haritasi - hangi kelime hangi kampanyalarda
    kw_map = defaultdict(list)
    for t in targets:
        if t["clicks"] < 3:
            continue
        kw_map[t["targeting"].lower()].append(t)

    # Kampanya bazli agregasyon
    campaign_data = {}
    for st in search_terms:
        camp = st["campaign"]
        if not camp:
            continue
        cd = campaign_data.setdefault(camp, {
            "spend": 0, "sales": 0, "orders": 0, "clicks": 0,
            "wasted_terms": [], "harvest_terms": [], "total_term_count": 0,
        })
        cd["spend"] += st["spend"]
        cd["sales"] += st["sales"]
        cd["orders"] += st["orders"]
        cd["clicks"] += st["clicks"]

    # Wasted terms per campaign
    term_agg = defaultdict(lambda: defaultdict(lambda: {"clicks": 0, "spend": 0, "orders": 0, "sales": 0, "is_asin": False}))
    for st in search_terms:
        camp = st["campaign"]
        if not camp:
            continue
        a = term_agg[camp][st["term"]]
        a["clicks"] += st["clicks"]
        a["spend"] += st["spend"]
        a["orders"] += st["orders"]
        a["sales"] += st["sales"]
        a["is_asin"] = st.get("is_asin", False)

    existing_exact = {t["targeting"].lower() for t in targets if t["match_type"] == "EXACT"}

    for camp, terms in term_agg.items():
        if camp not in campaign_data:
            continue
        cd = campaign_data[camp]
        cd["total_term_count"] = len(terms)
        for term, m in terms.items():
            if m["orders"] == 0 and (m["clicks"] >= 8 or m["spend"] >= tacos * aov * 1.5):
                cd["wasted_terms"].append({
                    "term": term, "clicks": int(m["clicks"]),
                    "spend": round(m["spend"], 2),
                    "is_asin": m["is_asin"],
                })
            elif m["orders"] >= 2 and m["sales"] > 0:
                acos = m["spend"] / m["sales"]
                if acos <= tacos and term not in existing_exact:
                    rpc = m["sales"] / m["clicks"] if m["clicks"] else 0
                    bid = max(0.15, round(rpc * tacos, 2))
                    cd["harvest_terms"].append({
                        "term": term, "orders": int(m["orders"]),
                        "sales": round(m["sales"], 2),
                        "acos_pct": round(acos * 100, 1),
                        "suggested_bid": bid,
                        "is_asin": m["is_asin"],
                    })

    # Targeting kampanya bazli bid onerileri
    targeting_by_camp = defaultdict(list)
    for t in targets:
        if t["campaign"]:
            targeting_by_camp[t["campaign"]].append(t)

    # TOS placement per campaign
    tos_by_camp = {}
    for p in placements or []:
        if "Top of Search" in p.get("placement", ""):
            tos_by_camp[p["campaign"]] = p

    # Kampanya bazli aksiyon uretimi
    results = []
    for camp_row in campaigns:
        camp = camp_row["campaign"]
        if not camp:
            continue
        agg = campaign_data.get(camp) or {"spend": camp_row.get("spend", 0),
                                          "sales": camp_row.get("sales", 0),
                                          "orders": camp_row.get("orders", 0),
                                          "clicks": camp_row.get("clicks", 0),
                                          "wasted_terms": [], "harvest_terms": [],
                                          "total_term_count": 0}
        spend = agg["spend"] or camp_row.get("spend", 0)
        sales = agg["sales"] or camp_row.get("sales", 0)
        orders = agg["orders"] or camp_row.get("orders", 0)
        clicks = agg["clicks"] or camp_row.get("clicks", 0)
        if clicks < 5:
            continue
        acos = (spend / sales) if sales > 0 else None
        actions = []

        # 1. Wasted spend - negatifle
        if agg["wasted_terms"]:
            waste_total = sum(w["spend"] for w in agg["wasted_terms"])
            top_wasted = sorted(agg["wasted_terms"], key=lambda w: -w["spend"])[:3]
            actions.append({
                "severity": "critical",
                "icon": "🚫",
                "action": f"{len(agg['wasted_terms'])} arama terimi negatifle "
                          f"(${waste_total:.0f} israf)",
                "detail": ", ".join(f"'{w['term']}' (${w['spend']:.0f})"
                                    for w in top_wasted),
                "amazon_step": "Bu kampanya → Negative targeting → Add → "
                               "her biri Negative Exact",
                "copy_list": [w["term"] for w in agg["wasted_terms"][:20]],
            })

        # 2. Harvest - exact'e tasi
        if agg["harvest_terms"]:
            top_h = sorted(agg["harvest_terms"], key=lambda h: -h["sales"])[:3]
            harvest_sales = sum(h["sales"] for h in agg["harvest_terms"])
            actions.append({
                "severity": "high",
                "icon": "🌱",
                "action": f"{len(agg['harvest_terms'])} kelime exact kampanyaya "
                          f"tasi (${harvest_sales:.0f} kazanan)",
                "detail": " · ".join(f"'{h['term']}' ({h['orders']} sip, "
                                     f"bid ${h['suggested_bid']})" for h in top_h),
                "amazon_step": "Exact kampanyana ekle + BURADA negative exact yap "
                               "(traffic sculpting)",
                "copy_list": [f"{h['term']}\t{h['suggested_bid']}"
                              for h in agg["harvest_terms"][:20]],
            })

        # 3. Bid down/up onerileri bu kampanya icin
        bid_down = []
        bid_up = []
        for t in targeting_by_camp.get(camp, []):
            if t["clicks"] < 5:
                continue
            if t["match_type"] not in ("EXACT", "PHRASE", "BROAD") and \
               not t["targeting"].lower().startswith("asin"):
                continue
            if t["sales"] <= 0 and t["spend"] > tacos * aov:
                bid_down.append(t)
            elif t["sales"] > 0:
                ac = t["spend"] / t["sales"]
                if ac > tacos * 1.15:
                    bid_down.append(t)
                elif ac < tacos * 0.7 and t["orders"] >= 1:
                    bid_up.append(t)
        if len(bid_down) >= 3:
            top_bd = sorted(bid_down, key=lambda t: -t["spend"])[:3]
            actions.append({
                "severity": "high",
                "icon": "📉",
                "action": f"{len(bid_down)} kelimede bid dusur "
                          f"(ACOS hedef ustunde)",
                "detail": " · ".join(f"'{t['targeting']}' CPC ${t['cpc']:.2f}"
                                     for t in top_bd),
                "amazon_step": "Bu kampanya → Targeting → kelimeye tikla → bid guncelle",
            })
        if len(bid_up) >= 2:
            top_bu = sorted(bid_up, key=lambda t: -t["sales"])[:3]
            actions.append({
                "severity": "medium",
                "icon": "📈",
                "action": f"{len(bid_up)} kelimede bid artir "
                          f"(ACOS cok dusuk, olcek firsati)",
                "detail": " · ".join(f"'{t['targeting']}' "
                                     f"ACOS %{t['spend']/t['sales']*100:.0f}"
                                     for t in top_bu),
                "amazon_step": "Targeting → bid +%5-10 · 1 hafta bekle · gerekirse tekrar",
            })

        # 4. TOS placement multiplier fırsati
        tos = tos_by_camp.get(camp)
        if tos and tos["orders"] >= 2 and tos["sales"] > 0:
            tos_acos = tos["spend"] / tos["sales"]
            if tos_acos < tacos * 0.7:
                mult = 50 if tos_acos < tacos * 0.5 else 25
                actions.append({
                    "severity": "high",
                    "icon": "⬆",
                    "action": f"TOS placement +%{mult} çarpan ekle",
                    "detail": f"TOS ACOS %{tos_acos*100:.1f} hedefin cok altinda "
                              f"({int(tos['orders'])} siparis) - kaldirac firsati",
                    "amazon_step": "Kampanya → Settings → Adjust bids by "
                                   f"placement → Top of search: +{mult}%",
                })

        # 5. Kannibalizm tespiti
        cannibals = []
        for t in targeting_by_camp.get(camp, []):
            kw = t["targeting"].lower()
            others = [o for o in kw_map.get(kw, [])
                      if o["campaign"] != camp and o["clicks"] >= 3]
            if not others:
                continue
            # Ayni kelimenin baska kampanyada varlığı - hangisi kazaniyor?
            my_acos = (t["spend"] / t["sales"]) if t["sales"] > 0 else 999
            for o in others:
                o_acos = (o["spend"] / o["sales"]) if o["sales"] > 0 else 999
                if o_acos < my_acos:  # digeri daha iyi
                    cannibals.append({
                        "term": t["targeting"],
                        "winner_camp": o["campaign"],
                        "my_cpc": round(t["cpc"], 2),
                        "winner_cpc": round(o["cpc"], 2),
                    })
                    break
        if cannibals:
            top_c = cannibals[:3]
            actions.append({
                "severity": "medium",
                "icon": "⚔️",
                "action": f"{len(cannibals)} kelime baska kampanyayla "
                          f"kannibalizm - burada negatifle",
                "detail": " · ".join(f"'{c['term']}' → '{c['winner_camp']}' kazaniyor"
                                     for c in top_c),
                "amazon_step": "Bu kampanya → Negative → Negative exact "
                               "(kelimeler asagida kopyalanabilir)",
                "copy_list": [c["term"] for c in cannibals[:20]],
            })

        # Urgency skoru - harcama × sorun sayisi × (acos delta)
        acos_penalty = 1.0
        if acos is not None:
            acos_penalty = max(0.5, min(3.0, acos / tacos))
        urgency = spend * (1 + len(actions) * 0.3) * acos_penalty
        if not actions:
            urgency *= 0.2  # sorunsuz kampanyalar sona

        results.append({
            "campaign": camp,
            "targeting_type": camp_row.get("targeting_type", ""),
            "spend": round(spend, 2),
            "sales": round(sales, 2),
            "orders": int(orders),
            "clicks": int(clicks),
            "acos_pct": round(acos * 100, 1) if acos is not None else None,
            "acos_status": "over" if acos is not None and acos > tacos else
                           ("under" if acos is not None else "no_sales"),
            "term_count": agg["total_term_count"],
            "actions": actions,
            "action_count": len(actions),
            "urgency_score": round(urgency, 1),
        })

    results.sort(key=lambda r: -r["urgency_score"])
    return results[:top_n]


def dashboard(brand, search_terms, targets, placements, campaigns,
              det_recs, uploads):
    """Tum insights'lari toplu dondurur."""
    wasted = wasted_spend(search_terms)
    oppo = opportunities(search_terms, targets, brand)
    lost_is = lost_impressions(targets, brand)
    dead = dead_keywords(targets)
    conflicts = bid_conflicts(targets)
    health = health_score(brand, search_terms, targets, wasted, oppo, lost_is)
    prio = priorities(brand, wasted, oppo, lost_is, dead, conflicts, det_recs)
    # Grupla: bu hafta yap vs 1 hafta bekleyebilir
    urgent = [x for x in prio if x["priority"] in ("critical", "high")]
    later = [x for x in prio if x["priority"] not in ("critical", "high")]
    prio_grouped = {"urgent": urgent, "later": later,
                    "urgent_count": len(urgent), "later_count": len(later)}
    # Pro insights
    skag = skag_candidates(targets, brand)
    tos_mult = tos_multiplier_opportunities(placements, brand)
    defense = brand_defense_check(search_terms, campaigns)
    momentum = campaign_momentum(campaigns, brand)
    return {
        "kpi": kpi_ribbon(search_terms, targets, campaigns),
        "portfolio": portfolio_stats(targets, campaigns),
        "best_worst": best_worst(campaigns, brand),
        "placement_split": placement_split(placements),
        "top_search_terms": top_search_terms(search_terms),
        "health": health,
        "wasted_spend": wasted,
        "opportunities": oppo,
        "lost_impressions": lost_is,
        "dead_keywords": dead,
        "bid_conflicts": conflicts,
        "priorities": prio,
        "priorities_grouped": prio_grouped,
        "campaign_advisor": campaign_advisor(brand, search_terms, targets,
                                             placements, campaigns),
        "pro_insights": {
            "skag_candidates": skag,
            "tos_multiplier": tos_mult,
            "brand_defense": defense,
            "campaign_momentum": momentum,
        },
        "campaign_distribution": campaign_spend_distribution(campaigns),
        "match_type_distribution": match_type_distribution(search_terms),
        "upload_trend": upload_trend(uploads),
    }
