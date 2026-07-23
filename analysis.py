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
import re
import keepa_engine


def _f(x, nd=2):
    return round(float(x), nd)


def _aov(search_terms):
    """Ortalama sepet tutari (AOV) - tum satisli satirlardan."""
    sales = sum(s["sales"] for s in search_terms)
    orders = sum(s["orders"] for s in search_terms)
    return sales / orders if orders else 30.0


def run_all(brand, search_terms, targets, placements=None, campaigns=None):
    recs = []
    aov = _aov(search_terms) if search_terms else 30.0
    recs += anomalies(brand, targets, aov)
    recs += cannibalization(brand, targets)
    recs += expansion(brand, targets)
    recs += keepa_engine.get_keepa_recommendations(brand, targets)
    recs += harvest(brand, search_terms, targets)
    recs += negatives(brand, search_terms)
    recs += bids(brand, targets, aov)
    recs += placement_recs(brand, placements or [])
    if campaigns:
        recs += campaign_budgets(brand, campaigns)
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
        if a["orders"] < 1 or a["spend"] <= 0 or a["sales"] <= 0: # REVENUE FIRST: 1 siparis yeterli
            continue
        acos = a["spend"] / a["sales"]
        if acos > tacos * 1.2: # REVENUE FIRST: Hedefin %20 uzerine kadar tolere et
            continue
        if not a["is_asin"] and term in existing:
            continue
        # RPC x hedef ACOS = hedefe gore odenebilir maksimum tik maliyeti
        rpc = a["sales"] / a["clicks"] if a["clicks"] else 0
        cpc = a["spend"] / a["clicks"] if a["clicks"] else 0.5
        # REVENUE FIRST: Yeni kelimelerde pazar payi almak icin daha agresif bid (x1.5)
        bid = min(rpc * tacos, cpc * 1.50) if rpc else cpc * 1.50
        bid = max(0.15, _f(bid))
        label = "urun hedefleme (ASIN)" if a["is_asin"] else "exact keyword"
        # Confidence & Auto-Apply Logic for Harvest
        if acos <= tacos and a["orders"] >= 2:
            confidence = 98
            auto_apply = True
        else:
            confidence = 80
            auto_apply = False
            
        # 1. Harvest Onerisi (Exact/PT'ye ekleme)
        recs.append({
            "type": "harvest_pt" if a["is_asin"] else "harvest",
            "campaign": ", ".join(sorted(a["campaigns"])),
            "ad_group": "",
            "keyword": term,
            "match_type": "PRODUCT" if a["is_asin"] else "EXACT",
            "current_value": None,
            "suggested_value": bid,
            "reason": (f"{int(a['orders'])} siparis, ACOS %{_f(acos*100,1)} "
                       f"(hedef %{_f(tacos*100,0)}). Agresif (Ciro Odakli) test bid. "
                       f"Exact kampanyaya {label} olarak ekle."),
            "metrics": {"clicks": int(a["clicks"]), "spend": _f(a["spend"]),
                        "sales": _f(a["sales"]), "orders": int(a["orders"]),
                        "acos": _f(acos * 100, 1)},
            "confidence": confidence,
            "auto_apply": auto_apply
        })
        
        # 2. Auto-Sculpting Onerisi (Kaynak kampanyada negatifleme)
        for c in a["campaigns"]:
            recs.append({
                "type": "negative",
                "campaign": c,
                "ad_group": "",
                "keyword": term,
                "match_type": "NEGATIVE PRODUCT" if a["is_asin"] else "NEGATIVE EXACT",
                "current_value": None,
                "suggested_value": None,
                "reason": (f"✂️ AUTO-SCULPTING: Bu kelime EXACT/PT'ye harvest edildiği için, "
                           f"çift taraflı para yakmamak (cannibalization) adına kaynak kampanyada "
                           f"otomatik olarak NEGATİF eklendi."),
                "metrics": {"clicks": 0, "spend": 0, "sales": 0, "orders": 0, "acos": None},
                "confidence": 99,
                "auto_apply": True
            })
            
    recs.sort(key=lambda r: -r["metrics"]["sales"])
    return recs


def negatives(brand, search_terms):
    """Kural 4: Ciro Odakli - Negatiflemede daha esnek ol (Sert azaltimlardan kacin)."""
    min_clicks = brand["min_clicks_neg"] * 1.5 # Daha esnek (1.5x click)
    tacos = brand["target_acos"]
    aov = _aov(search_terms)
    # REVENUE FIRST: Israf toleransini artir (1.5 yerine 2.5 kati)
    spend_cap = tacos * aov * 2.5  
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
        # Confidence & Auto-Apply Logic for Negatives
        if by_spend and a["spend"] >= spend_cap * 1.5:
            confidence = 99
            auto_apply = True
        elif by_clicks and a["clicks"] >= min_clicks * 1.5:
            confidence = 95
            auto_apply = True
        else:
            confidence = 85
            auto_apply = False

        trigger = (f"{int(a['clicks'])} tik (esnek esik: {int(min_clicks)})" if by_clicks
                   else f"${_f(a['spend'])} harcama > tolerans limiti (${_f(spend_cap)})")
        recs.append({
            "type": "negative",
            "campaign": campaign,
            "ad_group": "",
            "keyword": term,
            "match_type": "NEGATIVE PRODUCT" if a["is_asin"] else "NEGATIVE EXACT",
            "current_value": None,
            "suggested_value": None,
            "reason": (f"{trigger}, 0 siparis. "
                       f"Kampanyada Negative targeting bolumune "
                       f"{'ASIN olarak' if a['is_asin'] else 'negatif exact olarak'} ekle."),
            "metrics": {"clicks": int(a["clicks"]), "spend": _f(a["spend"]),
                        "sales": 0, "orders": 0, "acos": None},
            "confidence": confidence,
            "auto_apply": auto_apply
        })
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def anomalies(brand, targets, aov):
    """Uzman Seviyesi: Anomaly (Outlier) Detection - Velocity Spike Koruması."""
    tacos = brand["target_acos"]
    target_cpa = tacos * aov
    recs = []
    
    for t in targets:
        spend = t["spend"]
        sales = t["sales"]
        orders = t["orders"]
        acos = spend / sales if sales > 0 else None
        
        # Anomaly 1: Korkunc İsraf (Hedef CPA'nin 4 katisindan fazla harcamis ve 0 siparis)
        # Sadece bid kismak yetmez, bunu tamamen durdurmak lazim. (Velocity Spike)
        if orders == 0 and spend >= target_cpa * 4.0:
            recs.append({
                "type": "anomaly_pause",
                "campaign": t["campaign"],
                "ad_group": t["ad_group"],
                "keyword": t["targeting"],
                "match_type": t["match_type"],
                "current_value": "Aktif",
                "suggested_value": "DURAKLAT (PAUSE)",
                "reason": (f"🚨 ANOMALİ TESPİTİ: Bu kelime/hedef hiçbir sipariş getirmeden "
                           f"hedef EBM'nizin (CPA) tam 4 katı (${_f(spend)}) harcamış! "
                           f"Bot tıklaması veya yanlış trend olabilir. Acilen DURAKLATIN."),
                "metrics": {"clicks": int(t["clicks"]), "spend": _f(spend),
                            "sales": _f(sales), "orders": int(orders), "acos": None},
                "confidence": 99,
                "auto_apply": True
            })
        
        # Anomaly 2: Karadelik (Satis var ama ACOS inanilmaz derecede yuksek, %300+)
        elif acos is not None and acos > tacos * 4.0 and spend > 50:
            recs.append({
                "type": "anomaly_pause",
                "campaign": t["campaign"],
                "ad_group": t["ad_group"],
                "keyword": t["targeting"],
                "match_type": t["match_type"],
                "current_value": "Aktif",
                "suggested_value": "DURAKLAT (PAUSE)",
                "reason": (f"🚨 KARADELİK TESPİTİ: ACOS %{_f(acos*100,0)} gibi yıkıcı bir "
                           f"seviyeye ulaşmış (Hedefin 4 katı!). Bid kısmak bu "
                           f"israfı düzeltmeye yetmez, acilen DURAKLATIN."),
                "metrics": {"clicks": int(t["clicks"]), "spend": _f(spend),
                            "sales": _f(sales), "orders": int(orders),
                            "acos": _f(acos * 100, 1)},
                "confidence": 98,
                "auto_apply": True
            })
            
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def cannibalization(brand, targets):
    """Uzman Seviyesi: Yamyamlık Tespiti (Keyword Cannibalization).
    Aynı kelimenin birden fazla kampanyada hedeflenip hedeflenmediğini bulur ve zayıf olanı duraklatır."""
    recs = []
    
    # Kelime -> [Satirlar] haritasi cikar
    target_map = {}
    for t in targets:
        # Status filter is important but we don't have exact 'status' always in target rows.
        # So we just group them.
        k = (t["targeting"].lower(), t["match_type"])
        if k[0] == "*" or not k[0]: continue
        target_map.setdefault(k, []).append(t)
        
    for (kw, match_type), rows in target_map.items():
        if len(rows) > 1:
            # Ayni kelime ayni eslesme turuyle 1'den fazla yerde geciyor!
            # En iyi olani sec (satis > 0 ise ACOS en dusuk olan, degilse spend en dusuk olan)
            valid_rows = [r for r in rows if r["clicks"] > 0] # Sadece aktif/harcayanlari al
            if len(valid_rows) <= 1:
                continue
                
            # Performansa gore sirala (once en iyi)
            valid_rows.sort(key=lambda x: (x["spend"]/x["sales"] if x["sales"] > 0 else 9999, x["spend"]))
            
            # 1. siradaki HARIC digerlerini DURAKLAT
            best = valid_rows[0]
            for bad in valid_rows[1:]:
                # Eger kotu olan hic para harcamamissa dokunma (zaten olu)
                if bad["spend"] < 5: continue
                
                bad_acos = bad["spend"] / bad["sales"] if bad["sales"] > 0 else None
                best_acos = best["spend"] / best["sales"] if best["sales"] > 0 else None
                
                recs.append({
                    "type": "anomaly_pause", # Ayni menude goster
                    "campaign": bad["campaign"],
                    "ad_group": bad["ad_group"],
                    "keyword": bad["targeting"],
                    "match_type": bad["match_type"],
                    "current_value": "Aktif",
                    "suggested_value": "DURAKLAT (PAUSE)",
                    "reason": (f"⚔️ YAMYAMLIK (Cannibalization): Bu kelimeyi zaten "
                               f"'{best['campaign']}' kampanyasında kullanıyorsunuz "
                               f"(ve orada ACOS daha iyi: %{_f(best_acos*100,1) if best_acos is not None else 'Yok'}). "
                               f"Kendi kendinizle rekabet edip CPC'yi şişirmemek için buradaki zayıf kopyayı duraklatın!"),
                    "metrics": {"clicks": int(bad["clicks"]), "spend": _f(bad["spend"]),
                                "sales": _f(bad["sales"]), "orders": int(bad["orders"]),
                                "acos": _f(bad_acos * 100, 1) if bad_acos is not None else None},
                    "confidence": 99,
                    "auto_apply": True
                })
                
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def expansion(brand, targets):
    """Uzman Seviyesi: Ciro Büyütme (Broad Expansion & Defensive)."""
    tacos = brand["target_acos"]
    recs = []
    
    # Mevcut Broad/Phrase kelimeleri topla (ayni kelimeyi tekrar onermemek icin)
    broad_phrase_kws = {t["targeting"].lower() for t in targets if t["match_type"] in ("BROAD", "PHRASE")}
    
    for t in targets:
        # Sadece EXACT match veya Product Targeting (ASIN) kazananlarindan genisleme arariz
        if t["match_type"] not in ("EXACT", "PRODUCT", "TARGETING EXPRESSION"):
            continue
            
        spend = t["spend"]
        sales = t["sales"]
        orders = t["orders"]
        cpc = t["cpc"]
        acos = spend / sales if sales > 0 else None
        
        # 1. BROAD KAMPANYASI FIRSATI (Net Casting)
        if t["match_type"] == "EXACT" and acos is not None and acos <= tacos * 0.8 and orders >= 3:
            kw = t["targeting"].lower()
            if kw not in broad_phrase_kws:
                # Bu kelime EXACT'te cok iyi ama BROAD versiyonu yok!
                recs.append({
                    "type": "expansion",
                    "campaign": t["campaign"],
                    "ad_group": t["ad_group"],
                    "keyword": t["targeting"],
                    "match_type": "BROAD",
                    "current_value": "Sadece Exact'te",
                    "suggested_value": _f(cpc * 0.7), 
                    "reason": (f"📈 CİRO BÜYÜTME (Broad Expansion): Bu kelime EXACT eşleşmede {int(orders)} "
                               f"sipariş (ACOS %{_f(acos*100,1)}) getirmiş. Uzun kuyruklu (long-tail) yeni "
                               f"aramalar yakalamak için yeni bir Discovery kampanyasında BROAD olarak açın!"),
                    "metrics": {"clicks": int(t["clicks"]), "spend": _f(spend),
                                "sales": _f(sales), "orders": int(orders),
                                "acos": _f(acos * 100, 1)},
                    "confidence": 95,
                    "auto_apply": False 
                })
                broad_phrase_kws.add(kw) 

        # 2. SPONSORED BRANDS (VIDEO) & DISPLAY EXPANSION (Mega Kazanclar)
        if sales >= 500 or orders >= 10:
            if t["match_type"] == "EXACT" or t["match_type"] == "PHRASE":
                recs.append({
                    "type": "expansion",
                    "campaign": t["campaign"],
                    "ad_group": "",
                    "keyword": t["targeting"],
                    "match_type": "SPONSORED BRANDS (VIDEO)",
                    "current_value": "Yeni Ad Type",
                    "suggested_value": _f(cpc * 1.2), 
                    "reason": (f"🎥 VİDEO REKLAMI (SBV): Bu kelime Sponsored Products'ta "
                               f"mükemmel ciro (${_f(sales)}) getiriyor. Bu kelimeyi alıp "
                               f"Sponsored Brands Video (SBV) kampanyası açın. Arama sayfasının "
                               f"koca bir bölümünü kaplayarak rakipleri silin!"),
                    "metrics": {"clicks": int(t["clicks"]), "spend": _f(spend),
                                "sales": _f(sales), "orders": int(orders),
                                "acos": _f(acos * 100, 1) if acos is not None else None},
                    "confidence": 99,
                    "auto_apply": False 
                })
            elif "asin" in t["targeting"].lower() or t["match_type"] == "PRODUCT":
                recs.append({
                    "type": "expansion",
                    "campaign": t["campaign"],
                    "ad_group": "",
                    "keyword": t["targeting"],
                    "match_type": "SPONSORED DISPLAY",
                    "current_value": "Retargeting/Cross-sell",
                    "suggested_value": _f(cpc * 1.5), 
                    "reason": (f"🎯 DISPLAY RETARGETING: Bu ASIN hedefi çok kârlı (${_f(sales)} Ciro). "
                               f"Bu ASIN'i Sponsored Display 'Views Remarketing' veya "
                               f"'Product Targeting' ile hedefleyip rakibin sayfasında logonuzu/markanızı gösterin!"),
                    "metrics": {"clicks": int(t["clicks"]), "spend": _f(spend),
                                "sales": _f(sales), "orders": int(orders),
                                "acos": _f(acos * 100, 1) if acos is not None else None},
                    "confidence": 99,
                    "auto_apply": False 
                })
                
    recs.sort(key=lambda r: -r["metrics"]["sales"])
    return recs


def bids(brand, targets, aov):
    """Kural 1-3: Ciro Odakli RPC bazli bid onerileri."""
    tacos = brand["target_acos"]
    # REVENUE FIRST: Asagi yonlu kesintileri limitli tut (%10), agresif dususlerden kacin.
    cap = brand.get("bid_change_cap", 0.10)
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
        cvr = orders / clicks if clicks else 0  # Conversion Rate (Donusum Orani)
        
        # 🚀 UZMAN STRATEJISI: ORGANIC RANKING PUSH (Sira Yukseltme)
        # Eger donusum orani (CVR) %15'in uzerindeyse, bu kelime tam bu urune gore!
        # Amazon algoritmasi bu kelimede urunu seviyor. ACOS limite yakin olsa bile fiyati artir, organik siralamaya oyna.
        if cvr >= 0.15 and orders >= 3 and t["match_type"] == "EXACT":
            # Organik siralama kazanmak icin agresif fiyat artisi
            pct = 0.40 if acos is not None and acos <= tacos else 0.20
            new_bid = _f(cpc * (1 + pct))
            if abs(new_bid - cpc) >= 0.03:
                recs.append({
                    "type": "expansion", # Buyume sekmesinde goster
                    "campaign": t["campaign"],
                    "ad_group": t["ad_group"],
                    "keyword": t["targeting"],
                    "match_type": "RANKING MODE",
                    "current_value": _f(cpc),
                    "suggested_value": new_bid,
                    "reason": (f"🔥 ORGANIC RANK PUSH: Bu kelimenin dönüşüm oranı (CVR) muazzam "
                               f"(%{_f(cvr*100,1)}). Amazon algoritması sizi bu kelimede çok "
                               f"başarılı buluyor! Hedef ACOS'u bir süreliğine unutun, bid'i "
                               f"+%{int(pct*100)} artırıp organik 1. sayfaya yerleşin. (Organik ciro bedavadır!)"),
                    "metrics": {"clicks": int(clicks), "spend": _f(spend),
                                "sales": _f(sales), "orders": int(orders),
                                "acos": _f(acos * 100, 1) if acos is not None else None},
                    "confidence": 99,
                    "auto_apply": False
                })
                continue # Ranking onerdiysek standart bid onermeyelim

        if orders == 0 and spend >= target_cpa * 1.5:
            # REVENUE FIRST: Toleransi artirdik (target_cpa * 1.5).
            new_bid = max(0.15, _f((aov / clicks) * tacos))
            rtype = "bid_down"
            reason = (f"${_f(spend)} harcama (hedef CPA asildi), "
                      f"0 siparis. Formul: (AOV ${_f(aov)} / {int(clicks)} tik) x "
                      f"%{_f(tacos*100,0)}.")
            confidence = 90 if spend >= target_cpa * 2.0 else 75
            auto_apply = (confidence >= 90)
        elif acos is not None and acos > tacos * 1.30:
            # REVENUE FIRST: ACOS %30 uzerine cikana kadar dokunma (ciro icin).
            ideal = rpc * tacos
            new_bid = max(0.15, _f(max(ideal, cpc * (1 - cap))))
            rtype = "bid_down"
            reason = (f"ACOS %{_f(acos*100,1)} limit disi (> %{_f(tacos*130,0)}). "
                      f"Formul: RPC ${_f(rpc)} x hedef ACOS = ${_f(ideal)}"
                      + (f" (tek seferde max -%{int(cap*100)} sinirlandi)"
                         if ideal < cpc * (1 - cap) else "") + ".")
            confidence = 85 if acos > tacos * 1.8 else 60
            auto_apply = (confidence >= 85)
        elif acos is not None and acos <= tacos * 0.60 and orders >= 5:
            # 🚀 UZMAN STRATEJISI: MARKET DOMINATION (Pazar Payi Isgali)
            # ACOS cok dusuk ve hacim varsa, rakipleri ezmek icin fiyati cok agresif artir.
            pct = 0.35 # +35% birden artis
            new_bid = _f(cpc * (1 + pct))
            rtype = "bid_up"
            reason = (f"🚀 MARKET DOMINATION: ACOS %{_f(acos*100,1)} inanılmaz düşük ve "
                      f"{int(orders)} satış var! Rakipleri ezmek ve tüm pazar payını "
                      f"toplamak için teklifi tek seferde +%35 agresif artır.")
            confidence = 99
            auto_apply = True
        elif acos is not None and acos <= tacos * 1.10 and orders >= 1:
            # REVENUE FIRST: ACOS hedefin hafif uzerinde (%10) veya altinda olsa bile CIRO icin BID ARTIR!
            pct = 0.15 if acos < tacos * 0.8 else 0.05
            new_bid = _f(cpc * (1 + pct))
            rtype = "bid_up"
            reason = (f"ACOS %{_f(acos*100,1)} kârlılık sınırlarında. "
                      f"Ciro odakli strateji: Bid +%{int(pct*100)} artir, "
                      f"gosterim payini (Impression Share) ele gecir.")
            confidence = 90 if (acos < tacos * 0.8 and orders >= 3) else 70
            auto_apply = (confidence >= 90)
        else:
            continue
        # Bid artislarina da cap uygula (guveni cok yuksek MARKET DOMINATION haric)
        if rtype == "bid_up" and confidence < 99:
            max_increase = cpc * (1 + cap)
            if new_bid > max_increase:
                new_bid = _f(max_increase)
                reason += f" (tek seferde max +%{int(cap*100)} sınırlandı)"
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
            "confidence": confidence,
            "auto_apply": auto_apply
        })
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


# Performans raporundaki placement metnini Amazon Bulk'un resmi enum degerine
# esler (siralama onemli - once en spesifik desen kontrol edilir).
PLACEMENT_API_MAP = [
    ("top of search", "Placement Top", "Top of search (ilk sayfa ustu)"),
    ("product page", "Placement Product Page", "Urun sayfalari"),
    ("detail page", "Placement Product Page", "Urun sayfalari"),
    ("rest of search", "Placement Rest Of Search", "Rest of search"),
    ("other on", "Placement Rest Of Search", "Rest of search"),
]


def _placement_api(raw):
    """-> (amazon_enum, turkce_etiket) ya da (None, raw) eslesme yoksa
    (ornegin 'Off Amazon' - Sponsored Products bid ayarlamasiyla ilgisiz)."""
    low = (raw or "").lower()
    for needle, api_name, label in PLACEMENT_API_MAP:
        if needle in low:
            return api_name, label
    return None, raw


def placement_recs(brand, placements):
    """Uzman Seviyesi: Traffic Sculpting (Bid Down, Multiplier Up).
    TOS cok iyi ama ROS (Rest of Search) cok kotuyse, taban teklifleri dusurup
    TOS carpanini agresif sekilde artirir."""
    tacos = brand["target_acos"]
    recs = []
    by_camp = {}
    for p in placements:
        by_camp.setdefault(p["campaign"], []).append(p)
        
    for campaign, rows in by_camp.items():
        tos_row = None
        ros_row = None
        for p in rows:
            api_name, _ = _placement_api(p["placement"])
            if api_name == "Placement Top":
                tos_row = p
            elif api_name == "Placement Rest Of Search":
                ros_row = p
                
        # Expert Traffic Sculpting Check
        if tos_row and ros_row:
            tos_acos = tos_row["spend"] / tos_row["sales"] if tos_row["sales"] > 0 else None
            ros_acos = ros_row["spend"] / ros_row["sales"] if ros_row["sales"] > 0 else None
            
            tos_good = tos_acos is not None and tos_acos <= tacos * 1.0 and tos_row["orders"] >= 2
            ros_bad = (ros_acos is not None and ros_acos > tacos * 1.5) or (ros_row["spend"] > tacos*30 and ros_row["orders"] == 0)
            
            if tos_good and ros_bad:
                # Muazzam bir firsat! Rest of Search para yakiyor, TOS inanilmaz iyi.
                recs.append(_prec(campaign, "Top of search", "Placement Top", "up", 50,
                    f"🏆 TRAFFIC SCULPTING FIRSATI: Top of Search ACOS %{_f(tos_acos*100,1)} (Harika), "
                    f"ama Rest of Search ACOS %{_f(ros_acos*100,1) if ros_acos is not None else 'ZARAR'} (Kötü). "
                    f"Taktik: Kampanyadaki tüm keyword bidlerini %20-30 DÜŞÜR, ama buradaki TOS çarpanını "
                    f"+%50 ARTIR. Böylece sadece kazandığın yerde reklam gösterirsin.", 
                    tos_row, tos_acos, 98, False))
                continue # Zaten kampanya bazli isledik
                
        # Standart row-by-row logic (yukaridaki sarta uymayanlar)
        for p in rows:
            if p["clicks"] < 10 or p["spend"] <= 0:
                continue
            api_name, label = _placement_api(p["placement"])
            if api_name is None:
                continue
            acos = p["spend"] / p["sales"] if p["sales"] > 0 else None
            is_tos = api_name == "Placement Top"
            if acos is not None and acos < tacos * 0.7 and p["orders"] >= 2 and is_tos:
                conf = 90 if (acos < tacos * 0.5 and p["orders"] >= 5) else 60
                recs.append(_prec(campaign, label, api_name, "up", 25,
                    f"TOS ACOS %{_f(acos*100,1)} hedefin cok altinda, {int(p['orders'])} "
                    f"siparis. Carpani +%25 artir (kademeli).", p, acos, conf, conf >= 90))
            elif acos is not None and acos > tacos * 1.5:
                conf = 95 if acos > tacos * 2.0 else 80
                recs.append(_prec(campaign, label, api_name, "zero", None,
                    f"{label} ACOS %{_f(acos*100,1)} hedefin 1.5 kati. Carpani %0'a "
                    f"cek (asiri harcamayi durdur).", p, acos, conf, conf >= 95))
            elif acos is None and p["spend"] >= tacos * 30 * 1.5:
                recs.append(_prec(campaign, label, api_name, "zero", None,
                    f"{label}: ${_f(p['spend'])} harcama, 0 satis. Carpani %0'a cek.",
                    p, None, 95, True))
                    
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def campaign_budgets(brand, campaigns):
    """Ciro Odakli: Kazanan kampanyalara aninda butce takviyesi."""
    tacos = brand["target_acos"]
    recs = []
    for c in campaigns:
        spend = c.get("spend", 0)
        sales = c.get("sales", 0)
        clicks = c.get("clicks", 0)
        orders = c.get("orders", 0)
        acos = spend / sales if sales > 0 else None
        
        if spend < 10:
            continue
            
        rtype = None
        new_budget_pct = 0
        reason = ""
        confidence = 0
        
        if acos is not None and acos <= tacos * 1.15 and orders >= 3:
            # REVENUE FIRST: Karlilik limitlerinde veya harika gidiyorsa butce ARTIR
            rtype = "budget"
            new_budget_pct = 0.50 if acos < tacos * 0.8 else 0.20
            reason = (f"Kampanya ACOS %{_f(acos*100,1)} kârlılık sınırlarında "
                      f"ve {int(orders)} sipariş var. "
                      f"Günlük bütçeyi +%{int(new_budget_pct*100)} artırarak ölçekle.")
            confidence = 98 if acos < tacos else 85
        elif acos is not None and acos > tacos * 2.0:
            # Sadece inanilmaz zarar edenlerin butcesini kis
            rtype = "budget"
            new_budget_pct = -0.30
            reason = (f"Kampanya ACOS %{_f(acos*100,1)} hedefinizin çok üstünde. "
                      f"Zararı durdurmak için günlük bütçeyi %30 kıs.")
            confidence = 90
        elif acos is None and spend > target_cpa * 3:
            # Sifir satis, inanilmaz yuksek harcama
            rtype = "budget"
            new_budget_pct = -0.50
            reason = (f"${_f(spend)} harcama var ama 0 sipariş. "
                      f"Hemen bütçeyi yarıya düşür.")
            confidence = 95
            
        if rtype:
            recs.append({
                "type": rtype,
                "campaign": c["campaign"],
                "ad_group": "",
                "keyword": "Günlük Bütçe (Campaign Budget)",
                "match_type": "BUDGET",
                "current_value": None,
                "suggested_value": new_budget_pct,
                "reason": reason,
                "metrics": {"clicks": int(clicks), "spend": _f(spend),
                            "sales": _f(sales), "orders": int(orders),
                            "acos": _f(acos * 100, 1) if acos is not None else None},
                "confidence": confidence,
                "auto_apply": (confidence >= 95)
            })
            
    recs.sort(key=lambda r: -r["metrics"]["spend"])
    return recs


def _prec(campaign, label, api_name, direction, step_pct, reason, p, acos, confidence, auto_apply):
    # NOT: recommendations tablosunda ayri kolon yok, bu yuzden yapisal
    # placement alanlari (placement_api/direction/step_pct) metrics JSON'una
    # gomulur - mevcut sema deseni (metrics zaten esnek JSON alani) korunur.
    return {
        "type": "placement",
        "campaign": campaign,
        "ad_group": "",
        "keyword": label,
        "match_type": "PLACEMENT",
        "current_value": None,
        "suggested_value": None,
        "reason": f"[{'carpani artir' if direction=='up' else 'carpani sifirla'}] {reason}",
        "metrics": {"clicks": int(p["clicks"]), "spend": _f(p["spend"]),
                    "sales": _f(p["sales"]), "orders": int(p["orders"]),
                    "acos": _f(acos * 100, 1) if acos is not None else None,
                    "placement_api": api_name, "direction": direction,
                    "step_pct": step_pct},
        "confidence": confidence,
        "auto_apply": auto_apply
    }
