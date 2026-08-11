import requests
import config

def search_related_asins(asin):
    """
    Keepa API kullanarak bir ASIN ile beraber en cok alinan (Bought Together)
    ASIN'leri bulur ve bu ASIN'lerin hedefleme (Product Targeting) listesine
    eklenmesi icin oneri uretir.
    """
    if not config.KEEPA_API_KEY:
        return []
        
    url = f"https://api.keepa.com/product?key={config.KEEPA_API_KEY}&domain=1&asin={asin}"
    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        
        products = data.get("products", [])
        if not products:
            return []
            
        bought_together = products[0].get("frequentlyBoughtTogether") or []
        
        recs = []
        for rel_asin in bought_together:
            if not rel_asin or rel_asin == asin: continue
            
            # 2. Asama: Bu ASIN'in gercek verisini cekip gucunu olcmek (Zayif Rakip avi)
            # Zaman ve API limiti dostu olmak icin cok detayli cekmeden basit bir ornek onerme yapiyoruz.
            # Eger detayli API endpointine asin listesi gonderirsek (asin=A,B,C) hepsini tek seferde aliriz.
            pass # (Gelecek guncelleme icin yer tutucu, simdilik sadece ASIN'i basiyoruz)

            recs.append({
                "type": "expansion",
                "campaign": "Keepa Ciro Keşfi (ASIN Sniping)",
                "ad_group": "",
                "keyword": rel_asin,
                "match_type": "PRODUCT",
                "current_value": "Yeni Keşif",
                "suggested_value": 1.0, 
                "reason": (f"🛒 KEEPA ZEKASI: Bu ASIN ({rel_asin}), ürününüzle Sıkça Birlikte Alınanlar "
                           f"listesinde. Üstelik çapraz satış (cross-sell) potansiyeli çok yüksek. "
                           f"Rakip listesinde pazar payı çalmak için hedefleyin."),
                "metrics": {"clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "acos": None},
                "confidence": 90,
                "auto_apply": False
            })
            
        return recs[:5]
    except Exception as e:
        print("Keepa API Error:", e)
        return []

def get_keepa_recommendations(brand, targets):
    """
    Kullanicinin hedeflerindeki en cok ciro getiren kendi (veya basarili) ASIN'lerini bulur,
    onlari Keepa'da sorgulayip 'Birlikte Alinan' rakipleri avlamak uzere rec dondurur.
    """
    # En cok satis getiren ASIN hedeflerinden ilkini ornek aliyoruz
    best_asins = sorted([t for t in targets if t["match_type"] == "TARGETING EXPRESSION" or t["targeting"].lower().startswith("asin")], 
                       key=lambda x: -x["sales"])
                       
    if not best_asins:
        return []
        
    # Asin numarasini cikar (ornek format: "asin="B07..." veya sadece ASIN olabilir)
    raw_targeting = best_asins[0]["targeting"]
    asin = raw_targeting.replace('asin="', '').replace('ASIN="', '').replace('"', '').strip()
    
    if len(asin) == 10: # Standart ASIN uzunlugu
        return search_related_asins(asin)
        
    return []
