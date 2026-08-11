"""Gunluk is listesi motoru - "bugun ne yapmaliyim?" sorusunu cevaplar.

Uygulama artik 4 ayri motor calistiriyor (analysis, insights, market_intel,
launch) ve her biri kendi sekmesinde kendi listesini gosteriyor. Kullanicinin
kafasindaki soru ise tek: BUGUN NE YAPAYIM, EN COK NEREDE PARA VAR?

Bu modul hepsini okur, ayni birimde (dolar/ay) olcer, siralar ve tek liste
verir. Her madde su uce cevap verir:
    - Ne yapmaliyim (tek cumle, jargonsuz)
    - Neden (hangi veri bunu soyluyor)
    - Ne kazandirir / kurtarir (dolar)
"""

# Ceyreklik veriyi aylik etkiye cevirme carpani
Q2M = 1 / 3.0


def _money(v):
    return round(float(v or 0), 2)


def _from_negatives(opp):
    """Alakasiz kelimelere akan para - en net ve en kolay kazanc."""
    s = (opp.get("summary") or {}).get("negatives") or {}
    waste = _money(s.get("total_waste"))
    n = s.get("urgent_count") or 0
    if waste <= 0 or not n:
        return None
    monthly = waste * Q2M if (opp.get("period") == "quarterly") else waste
    return {
        "key": "negatives",
        "title": f"{n} alakasız kelimeye para akıyor — negatif ekle",
        "why": (f"Bu terimler hiçbir ürününle eşleşmiyor ve hiç satış getirmemiş, "
                f"ama toplam ${waste:,.0f} harcanmış."),
        "action": "Fırsat Radarı → Negatif keyword önerileri → 'Acil olanları kopyala'",
        "impact": round(monthly, 2),
        "impact_kind": "tasarruf",
        "effort": "5 dk",
        "confidence": "yüksek",
        "view": "opp",
    }


def _from_leak(opp):
    """Trafik alip satamayan kelimeler - listing sorunu."""
    leak = (opp.get("buckets") or {}).get("LEAK") or []
    if not leak:
        return None
    top = leak[:5]
    names = ", ".join(x["query"] for x in top[:3])
    return {
        "key": "leak",
        "title": f"{len(leak)} kelimede trafik alıp satamıyorsun",
        "why": (f"Gösterim payın var ama satın alma payın düşük ({names}). "
                f"Bu bir bid sorunu değil — fiyat, ana görsel veya yorum sayısı."),
        "action": "Fırsat Radarı → 🔴 Kaçak sekmesi → fiyat farkı sütununa bak",
        "impact": None,
        "impact_kind": "listing",
        "effort": "listing işi",
        "confidence": "orta",
        "view": "opp",
    }


def _from_scale(opp):
    """Zaten kazanan kelimelerde gorunurluk eksigi - en dusuk riskli buyume."""
    sc = (opp.get("buckets") or {}).get("SCALE") or []
    if not sc:
        return None
    rev = sum(x.get("est_revenue") or 0 for x in sc)
    monthly = rev * Q2M if (opp.get("period") == "quarterly") else rev
    return {
        "key": "scale",
        "title": f"{len(sc)} kelimede kazanıyorsun ama yeterince görünmüyorsun",
        "why": ("Tıklama payın gösterim payından yüksek — listingin rakiplerden iyi "
                "çalışıyor, sadece daha fazla gösterim alman gerekiyor."),
        "action": "Fırsat Radarı → 🔵 Büyüt sekmesi → önce bütçe, sonra bid +%20",
        "impact": round(monthly, 2),
        "impact_kind": "ciro",
        "effort": "15 dk",
        "confidence": "yüksek",
        "view": "opp",
    }


def _from_whitespace(opp):
    """Hic bulunmadigin kelimeler - en buyuk potansiyel, en yuksek efor."""
    ws = (opp.get("buckets") or {}).get("WHITESPACE") or []
    if not ws:
        return None
    pot = (opp.get("summary") or {}).get("whitespace_potential") or {}
    rev = pot.get("period_revenue") or 0
    monthly = rev * Q2M if (opp.get("period") == "quarterly") else rev
    return {
        "key": "whitespace",
        "title": f"{len(ws)} kelimede pazar dönüyor, sen hiç yoksun",
        "why": ("Bu terimlerde rakipler satış yapıyor ama senin hiç payın yok. "
                "En büyük büyüme alanı — ama yeni kampanya kurmak gerekiyor."),
        "action": "Fırsat Radarı → 🟢 Boşluk → tek üründen başla, ilk dalga 20 kelime",
        "impact": round(monthly, 2),
        "impact_kind": "ciro",
        "effort": "1 saat",
        "confidence": "orta",
        "view": "opp",
    }


def _from_recs(recs, brand):
    """Bekleyen bid/negatif/hasat onerileri."""
    if not recs:
        return None
    by = {}
    for r in recs:
        by.setdefault(r.get("type") or "?", []).append(r)
    parts = []
    LBL = {"bid_down": "bid düşür", "bid_up": "bid artır", "negative": "negatif",
           "harvest": "kazanan kelimeyi taşı", "budget": "bütçe",
           "pause": "durdur", "placement": "yerleşim"}
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))[:4]:
        parts.append(f"{len(v)} {LBL.get(k, k)}")
    # Bid dusurme onerilerindeki tasarruf tahmini
    save = 0.0
    for r in recs:
        m = r.get("metrics") or {}
        if r.get("type") == "bid_down" and (m.get("spend") or 0) > 0:
            cur, sug = r.get("current_value") or 0, r.get("suggested_value") or 0
            if cur > 0 and sug < cur:
                save += (m.get("spend") or 0) * (1 - sug / cur)
    return {
        "key": "recs",
        "title": f"{len(recs)} öneri onayını bekliyor",
        "why": "Reklam raporlarından çıkan otomatik düzeltmeler: " + ", ".join(parts) + ".",
        "action": "Öneriler sekmesi → incele → onayla → Amazon'a Yükle",
        "impact": round(save, 2) if save > 1 else None,
        "impact_kind": "tasarruf",
        "effort": "20 dk",
        "confidence": "yüksek",
        "view": "recs",
    }


def _missing_data(has):
    """Eksik rapor uyarilari - veri yoksa motor kor calisir."""
    out = []
    if not has.get("ba_query"):
        out.append({
            "key": "need_ba",
            "title": "Fırsat Radarı kapalı — Brand Analytics raporu eksik",
            "why": ("Reklam raporları sadece senin harcamanı gösterir. Pazarın "
                    "tamamını (rakipler hangi kelimede ne satıyor) görmek için "
                    "Brand Analytics gerekir."),
            "action": ("Seller Central › Marka › Marka Analizi › Arama Terimi "
                       "Performansı (Marka Görünümü) → indir → buraya sürükle"),
            "impact": None, "impact_kind": "veri", "effort": "5 dk",
            "confidence": "yüksek", "view": "home",
        })
    elif not has.get("ba_catalog"):
        out.append({
            "key": "need_catalog",
            "title": "Ürün eşleştirme kapalı — Katalog raporu eksik",
            "why": ("Hangi kelimenin hangi ürününe ait olduğunu bilemiyoruz; "
                    "alakasız kelime önerme riski yüksek ve bulksheet tüm "
                    "kelimeleri tek ASIN'e bağlar."),
            "action": "Marka Analizi › Arama Katalog Performansı → indir → sürükle",
            "impact": None, "impact_kind": "veri", "effort": "5 dk",
            "confidence": "yüksek", "view": "home",
        })
    if not has.get("economics"):
        out.append({
            "key": "need_econ",
            "title": "Kâr bilgisi girilmemiş — bid'ler varsayılan hesaplanıyor",
            "why": ("Satış fiyatı ve maliyet olmadan break-even ACOS bilinemez; "
                    "şu an %30 sektör varsayımı kullanılıyor. Gerçek marjınla "
                    "bid'ler ve hedef ACOS çok daha isabetli olur."),
            "action": "Üstteki ⚙ Ayarlar → satış fiyatı, ürün maliyeti, FBA ücreti",
            "impact": None, "impact_kind": "veri", "effort": "3 dk",
            "confidence": "yüksek", "view": "home",
        })
    return out


# Siralama: once veri eksikleri (yoksa gerisi kor), sonra para yakanlar,
# sonra dusuk riskli buyume, en sona buyuk efor isteyenler.
ORDER = ["need_ba", "need_catalog", "need_econ", "negatives", "recs",
         "scale", "leak", "whitespace"]


def today(recs=None, opp=None, brand=None, has=None):
    """-> {"items": [...], "summary": {...}}"""
    items = list(_missing_data(has or {}))
    if opp and not opp.get("empty"):
        for f in (_from_negatives, _from_scale, _from_leak, _from_whitespace):
            it = f(opp)
            if it:
                items.append(it)
    r = _from_recs(recs or [], brand or {})
    if r:
        items.append(r)

    items.sort(key=lambda x: ORDER.index(x["key"]) if x["key"] in ORDER else 99)
    for i, it in enumerate(items, 1):
        it["rank"] = i

    gain = sum(i["impact"] for i in items
               if i.get("impact") and i["impact_kind"] == "ciro")
    save = sum(i["impact"] for i in items
               if i.get("impact") and i["impact_kind"] == "tasarruf")
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "monthly_gain": round(gain, 2),
            "monthly_save": round(save, 2),
            "blocked_by_data": [i["key"] for i in items if i["impact_kind"] == "veri"],
        },
    }
