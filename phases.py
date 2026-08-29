"""Faz motoru - TEK KAYNAK.

NEDEN: faz mantigi uc ayri yerde (discovery-status, product-status, autofill)
farkli kurallarla hesaplaniyordu. Ayni marka bir ekranda "Faz 0", digerinde
"Faz 1" gorunuyordu. Faz artik yalnizca burada tanimlanir.

FAZLAR NEYE GORE AYRILIR
Her fazin sinirini ISTATISTIK belirler, takvim degil. "2 hafta gecti, faz
atlayalim" yanlistir; "CPC'yi olcecek kadar tiklama biriktim" dogrudur.

  Faz 0  KESIF        Tiklama basina ne odedigini BILMIYORSUN.
                      Cikis: >=15 tik (CPC +-%9 dogrulukla olculur)
  Faz 1  DOGRULAMA    CPC belli, hangi kelimenin DONUSTUGU belli degil.
                      Cikis: >=100 tik (CVR olculebilir) VE en az 1 kazanan
  Faz 2  HASAT        Kazananlar belli. Is: parayi onlara yigmak, israfi
                      kesmek. Cikis: ACOS hedefin altinda VE >=5 kazanan
  Faz 3  BUYUME       Karli ve istikrarli. Is: yeni kelime, yeni urun,
                      butce buyutme.

Her faz icin: neredesin, NEDEN oradasin, siradaki is ne, ilerlemek icin
ne gerekiyor.
"""
from collections import defaultdict

import benchmarks

# Istatistiksel esikler - benchmarks ile ayni kaynak
MIN_CLICKS_CPC = benchmarks.MIN_CLICKS_CPC      # 15  -> CPC olculebilir
MIN_CLICKS_CVR = benchmarks.MIN_CLICKS_CVR      # 100 -> CVR olculebilir
MIN_WINNERS_FAZ2 = 1                            # hasat baslamasi icin
MIN_WINNERS_FAZ3 = 5                            # buyumeye gecmek icin

FAZ = {
    0: {"ad": "Keşif", "renk": "amber",
        "amac": "Tıklama başına ne ödediğini ölçmek",
        "is": "Küçük bütçeli keşif kampanyası çalıştır, CPC'yi öğren"},
    1: {"ad": "Doğrulama", "renk": "blue",
        "amac": "Hangi kelimenin dönüştüğünü bulmak",
        "is": "Trafiği sürdür, arama terimi raporunu topla"},
    2: {"ad": "Hasat", "renk": "green",
        "amac": "Parayı kazananlara yığmak, israfı kesmek",
        "is": "Kazanan kelimeleri exact kampanyaya taşı, kaybedenleri kes"},
    3: {"ad": "Büyüme", "renk": "violet",
        "amac": "Kârlı yapıyı büyütmek",
        "is": "Bütçe artır, yeni kelime ve ürün ekle"},
}


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _kazananlar(search_terms, min_orders=1):
    """Satis ureten arama terimleri - hasat edilebilir kazananlar."""
    agg = defaultdict(lambda: {"clicks": 0.0, "spend": 0.0,
                               "orders": 0.0, "sales": 0.0})
    for r in search_terms or []:
        t = str(r.get("term") or "").strip().lower()
        if not t or r.get("is_asin"):
            continue
        g = agg[t]
        for k, f in (("clicks", "clicks"), ("spend", "spend"),
                     ("orders", "orders"), ("sales", "sales")):
            g[k] += _f(r.get(f))
    return [{"term": t, **g} for t, g in agg.items()
            if g["orders"] >= min_orders and g["sales"] > 0]


def assess(targeting_rows=None, search_term_rows=None, campaign_rows=None,
           target_acos_pct=None, break_even_acos_pct=None,
           target_is_default=False):
    """Markanin fazini ve siradaki isini belirler.

    Doner: {phase, name, why, next_action, exit_criteria, progress, metrics}
    """
    tg = targeting_rows or []
    st = search_term_rows or []
    cp = campaign_rows or []

    tik = sum(_f(r.get("clicks")) for r in tg) or sum(_f(r.get("clicks")) for r in cp)
    harcama = sum(_f(r.get("spend")) for r in tg) or sum(_f(r.get("spend")) for r in cp)
    satis = sum(_f(r.get("sales")) for r in tg) or sum(_f(r.get("sales")) for r in cp)
    siparis = sum(_f(r.get("orders")) for r in tg) or sum(_f(r.get("orders")) for r in cp)
    acos = (harcama / satis * 100) if satis > 0 else None
    cpc = (harcama / tik) if tik > 0 else None
    cvr = (siparis / tik) if tik > 0 else None

    kazanan = _kazananlar(st)
    n_kazanan = len(kazanan)
    kazanan_satis = sum(k["sales"] for k in kazanan)
    kazanan_harcama = sum(k["spend"] for k in kazanan)

    # Hedef ACOS onceligi: break-even (kendi ekonominden hesaplanir) >
    # markanin kayitli hedefi. Ikisi de yoksa faz kararinda ACOS kullanilmaz.
    hedef = break_even_acos_pct or target_acos_pct
    hedef_kaynak = ("kendi ekonominden (break-even)" if break_even_acos_pct
                    else "markanın kayıtlı hedefi")
    uyarilar = []
    if not break_even_acos_pct:
        uyarilar.append(
            "Marka ayarlarında satış fiyatı ve ürün maliyeti boş. Hedef ACOS "
            f"%{hedef:.0f} varsayılan değer — kendi ekonomin değil. Fiyat/maliyet "
            "girersen break-even ACOS hesaplanır ve faz çıkış kriteri gerçekçi olur."
            if hedef else
            "Hedef ACOS belirlenemedi — marka ayarlarında fiyat/maliyet gir.")

    # ---- Faz karari (asagidan yukari; her esik bir oncekini kapsar) ----
    if tik < MIN_CLICKS_CPC:
        faz = 0
        neden = (f"{tik:.0f} tıklama var. CPC'yi güvenilir ölçmek için en az "
                 f"{MIN_CLICKS_CPC} tıklama gerekir — altında ölçüm ±%25 sapar.")
        cikis = f"{MIN_CLICKS_CPC} tıklamaya ulaş"
        ilerleme = tik / MIN_CLICKS_CPC
    elif tik < MIN_CLICKS_CVR or n_kazanan < MIN_WINNERS_FAZ2:
        faz = 1
        eksik = []
        if tik < MIN_CLICKS_CVR:
            eksik.append(f"{tik:.0f}/{MIN_CLICKS_CVR} tıklama")
        if n_kazanan < MIN_WINNERS_FAZ2:
            eksik.append("henüz satış üreten arama terimi yok")
        neden = (f"CPC ölçüldü (${cpc:.2f}). Ama dönüşümü bilmek için daha çok "
                 f"veri lazım: {', '.join(eksik)}.")
        cikis = f"{MIN_CLICKS_CVR} tıklama + en az {MIN_WINNERS_FAZ2} kazanan terim"
        ilerleme = min(tik / MIN_CLICKS_CVR,
                       (n_kazanan / MIN_WINNERS_FAZ2) if MIN_WINNERS_FAZ2 else 1)
    # Faz 3'e gecmek KARLILIK iddiasidir; hedef ACOS bilinmeden bu iddia
    # edilemez. Hedef yoksa en fazla Faz 2'de kalinir - "bilmiyoruz" demek,
    # "karliyiz" demekten dogrudur.
    elif (not hedef) or (acos and acos > hedef) or n_kazanan < MIN_WINNERS_FAZ3:
        faz = 2
        parca = []
        if not hedef:
            parca.append("hedef ACOS tanımlı değil - kârlılık doğrulanamıyor")
        elif acos and acos > hedef:
            parca.append(f"ACOS %{acos:.0f}, hedef %{hedef:.0f}")
        if n_kazanan < MIN_WINNERS_FAZ3:
            parca.append(f"{n_kazanan}/{MIN_WINNERS_FAZ3} kazanan terim")
        neden = (f"{n_kazanan} kazanan terim bulundu (${kazanan_satis:.0f} satış, "
                 f"${kazanan_harcama:.0f} harcama). Şimdi iş bunları büyütüp "
                 f"gerisini kesmek. " + " · ".join(parca))
        cikis = ((f"ACOS ≤ %{hedef:.0f}" if hedef
                  else "marka ayarlarına fiyat/maliyet gir (hedef ACOS için)") +
                 f" ve ≥{MIN_WINNERS_FAZ3} kazanan terim")
        ilerleme = min(n_kazanan / MIN_WINNERS_FAZ3,
                       (hedef / acos) if (hedef and acos) else 1)
    else:
        faz = 3
        neden = (f"ACOS %{acos:.0f} hedefin ({hedef:.0f}) altında ve "
                 f"{n_kazanan} kazanan terim var. Yapı kârlı ve istikrarlı.")
        cikis = "—"
        ilerleme = 1.0

    bilgi = FAZ[faz]
    return {
        "phase": faz,
        "target_source": hedef_kaynak,
        "warnings": uyarilar,
        "name": bilgi["ad"],
        "color": bilgi["renk"],
        "goal": bilgi["amac"],
        "next_action": bilgi["is"],
        "why": neden,
        "exit_criteria": cikis,
        "progress": round(min(max(ilerleme, 0), 1), 3),
        "metrics": {
            "clicks": round(tik), "spend": round(harcama, 2),
            "sales": round(satis, 2), "orders": round(siparis),
            "cpc": round(cpc, 2) if cpc else None,
            "cvr_pct": round(cvr * 100, 2) if cvr else None,
            "acos_pct": round(acos, 1) if acos else None,
            "target_acos_pct": round(hedef, 1) if hedef else None,
            "winners": n_kazanan,
            "winner_sales": round(kazanan_satis, 2),
            "winner_spend": round(kazanan_harcama, 2),
            "winner_roas": (round(kazanan_satis / kazanan_harcama, 1)
                            if kazanan_harcama else None),
        },
        "thresholds": {
            "clicks_for_cpc": MIN_CLICKS_CPC,
            "clicks_for_cvr": MIN_CLICKS_CVR,
            "winners_for_harvest": MIN_WINNERS_FAZ2,
            "winners_for_growth": MIN_WINNERS_FAZ3,
        },
    }


def checklist(durum):
    """Bu fazda YAPILACAKLAR - sirali, somut.

    Her madde ya tamamlanmis ya bekliyor; kullanici ne yapacagini
    tahmin etmek zorunda kalmaz.
    """
    f = durum["phase"]
    m = durum["metrics"]
    t = durum["thresholds"]
    if f == 0:
        return [
            {"is": "Keşif kampanyası kur (küçük bütçe, geniş hedefleme)",
             "tamam": m["clicks"] > 0,
             "not": "Amaç satış değil, CPC ölçmek"},
            {"is": f"{t['clicks_for_cpc']} tıklama biriktir",
             "tamam": m["clicks"] >= t["clicks_for_cpc"],
             "not": f"şu an {m['clicks']}"},
            {"is": "Targeting raporunu yükle",
             "tamam": m["clicks"] > 0,
             "not": "CPC buradan okunur"},
        ]
    if f == 1:
        return [
            {"is": "Teklifleri ölçülen CPC'ye göre ayarla",
             "tamam": m["cpc"] is not None,
             "not": f"ölçülen CPC ${m['cpc']}" if m["cpc"] else "—"},
            {"is": f"{t['clicks_for_cvr']} tıklamaya ulaş",
             "tamam": m["clicks"] >= t["clicks_for_cvr"],
             "not": f"şu an {m['clicks']} — dönüşüm bundan önce ölçülemez"},
            {"is": "Arama terimi raporunu yükle",
             "tamam": m["winners"] > 0,
             "not": f"{m['winners']} kazanan terim bulundu"},
            {"is": "Ölü bütçeleri düzelt (bütçe ≥ teklif × 5)",
             "tamam": None, "not": "Kampanya Doktoru → Tara"},
        ]
    if f == 2:
        return [
            {"is": f"{m['winners']} kazanan terimi exact kampanyaya taşı",
             "tamam": None,
             "not": (f"ROAS {m['winner_roas']}x — hasat dosyası üret"
                     if m["winner_roas"] else "Listing Planı → hasat")},
            {"is": "Satış üretmeyen terimlerde teklifi düşür",
             "tamam": None, "not": "Kampanya Doktoru → düzeltme dosyası"},
            {"is": "Ekonomik tavanı aşan teklifleri kes",
             "tamam": None, "not": "Rekabet Gücü panelinde gör"},
            {"is": f"ACOS'u %{m['target_acos_pct'] or '—'} altına indir",
             "tamam": (m["acos_pct"] is not None and m["target_acos_pct"] is not None
                       and m["acos_pct"] <= m["target_acos_pct"]),
             "not": f"şu an %{m['acos_pct']}" if m["acos_pct"] else "—"},
            {"is": f"En az {t['winners_for_growth']} kazanan terim biriktir",
             "tamam": m["winners"] >= t["winners_for_growth"],
             "not": f"şu an {m['winners']}"},
        ]
    return [
        {"is": "Kazanan kampanyaların bütçesini artır",
         "tamam": None, "not": "Büyüme Planı → bütçe kısıtlı olanlar"},
        {"is": "Yeni kelime keşfi için auto kampanya çalıştır",
         "tamam": None, "not": "Keşif durmamalı — kazanan havuzu böyle büyür"},
        {"is": "Yeni ürünleri Faz 0'dan başlat",
         "tamam": None, "not": "Lansman → Yeni Ürün"},
        {"is": "Listing optimizasyonu (CTR/CVR)",
         "tamam": None, "not": "Reklam bütçesi gerektirmeyen kaldıraç"},
    ]
