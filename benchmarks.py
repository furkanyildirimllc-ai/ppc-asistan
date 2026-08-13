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
import re

# =====================================================================
# MARKA IZOLASYONU - KURAL
# Bir markanin olculmus verisi ASLA baska bir markanin planinda kullanilmaz.
# Farkli marka = farkli fiyat, farkli kitle, farkli donusum. Karistirmak
# sessizce yanlis bid uretir.
#
# Bu dosyada HICBIR markaya ait sayi sabit olarak tutulmaz. Asagidaki
# degerler yalnizca match type'lar arasindaki GORELI iliskidir (Amazon SP
# mekanigi geregi exact > phrase > broad); mutlak CVR/CPC degeri degildir
# ve tek basina kullanilmaz.
# =====================================================================

# Match type'lar arasi goreli CVR iliskisi (phrase = 1.00).
# Niyet genisligi mekaniktir: exact en dar niyet, broad/auto en genis.
RELATIVE_CVR = {"exact": 1.05, "phrase": 1.00, "broad": 0.38,
                "auto": 0.40, "pt": 0.55}
# Match type'lar arasi goreli CPC iliskisi (hesap ortalamasi = 1.00).
RELATIVE_CPC = {"exact": 1.15, "phrase": 1.20, "broad": 0.75,
                "auto": 0.80, "pt": 0.68}

MATCH_KEYS = ("exact", "phrase", "broad", "auto", "pt")

# Hicbir olcum yoksa kullanilan SON CARE varsayim. Bu deger hicbir markadan
# turetilmemistir; Amazon Sponsored Products genelinde yaygin olarak
# bildirilen ~%9 donusum orani baslangic noktasidir. Her zaman "VARSAYIM"
# olarak isaretlenir ve kullanicinin ustune yazmasi beklenir.
FALLBACK_CVR = 0.09

# Yeni listing olgun listing kadar donusturmez: yorum yok, organik sira yok,
# Amazon henuz alaka ogrenmemis. Ilk 2-4 haftada olgun CVR'in ~%65'i beklenir.
LAUNCH_RAMP = 0.65

# CPC ve CVR icin esikler AYRIDIR. Ikisini ayni saymak Faz 0'i bozuyordu:
# Faz 0 hedefi 20 tiklama, esik 100 olunca "olculmus CPC yok" deniyor ve
# kesif fazi bosa gidiyordu.
#
# Neden farkli:
#   CPC: her tiklama BIR OLCUMDUR (maliyeti dogrudan gorursun).
#        ~15 tik -> +-%10, ~20 tik -> +-%9 dogruluk. UCUZ.
#   CVR: her tiklama 0/1 bir denemedir; siparis nadir olaydir.
#        %10 CVR'da 20 tik -> +-%67 (ise yaramaz), 100 tik -> +-%30. PAHALI.
MIN_CLICKS_CPC = 15          # bu tiklamadan sonra olculmus CPC'ye guvenilir
MIN_CLICKS_CPC_BLEND = 6     # altinda kismen, bunun da altinda hic
MIN_CLICKS_CVR = 100         # CVR icin gercekten cok veri gerekir
MIN_CLICKS_CVR_BLEND = 30

# Geriye donuk uyum (eski cagrilar icin)
MIN_CLICKS_TRUST = MIN_CLICKS_CVR
MIN_CLICKS_BLEND = MIN_CLICKS_CVR_BLEND


def _q_tokens(s):
    return {t for t in re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split()
            if len(t) > 2}


def query_stats(ba_rows):
    """Brand Analytics 'Search Query Performance' -> kelime bazinda PAZAR verisi.

    Bu veri REKLAM ACMADAN elde edilir; yeni urun lansmaninda elimizdeki tek
    gercek donusum kaynagidir. Her sorgu icin:
      cvr    = satin alma / tiklama  (pazarin tamami, tum saticilar)
      volume = arama hacmi           (talep buyuklugu)
      price  = tiklanan urunlerin ortalama fiyati (fiyat konumlandirmasi)
    """
    agg = {}
    for r in ba_rows or []:
        q = str(r.get("query") or "").strip().lower()
        if not q:
            continue
        a = agg.setdefault(q, dict(clicks=0.0, purchases=0.0, volume=0.0,
                                   price_num=0.0, price_w=0.0))
        cl = float(r.get("clicks_total") or 0)
        pu = float(r.get("pur_total") or 0)
        a["clicks"] += cl
        a["purchases"] += pu
        a["volume"] += float(r.get("volume") or 0)
        mp = float(r.get("market_price") or 0)
        if mp > 0 and cl > 0:
            a["price_num"] += mp * cl
            a["price_w"] += cl
    out = {}
    for q, a in agg.items():
        if a["clicks"] <= 0:
            continue
        out[q] = {
            "cvr": a["purchases"] / a["clicks"],
            "clicks": a["clicks"],
            "volume": a["volume"],
            "market_price": (a["price_num"] / a["price_w"]) if a["price_w"] else None,
        }
    return out


def category_cvr(qstats, seed_tokens=None):
    """Kategori geneli pazar CVR'i (hacimle agirlikli).
    seed_tokens verilirse sadece o kategoriye ait sorgular sayilir."""
    cl = pu = 0.0
    for q, d in (qstats or {}).items():
        if seed_tokens and not (_q_tokens(q) & seed_tokens):
            continue
        cl += d["clicks"]
        pu += d["cvr"] * d["clicks"]
    return (pu / cl) if cl > 0 else None


def lookup_query(qstats, keyword, min_clicks=30, require_tokens=None):
    """Bir keyword icin pazar verisi. Once tam eslesme, sonra token ortusmesi.

    Doner: (stats, match_kind) - match_kind: exact | partial | None
    """
    if not qstats or not keyword:
        return None, None
    k = str(keyword).strip().lower()
    d = qstats.get(k)
    if d and d["clicks"] >= min_clicks:
        return d, "exact"

    kt = _q_tokens(k)
    if not kt:
        return None, None
    best, best_score, best_q = None, 0.0, None
    for q, d in qstats.items():
        if d["clicks"] < min_clicks:
            continue
        qt = _q_tokens(q)
        if not qt:
            continue
        inter = kt & qt
        if not inter:
            continue
        # Urun tipini belirleyen kok kelime (ornek "shampoo") ESLESMEK ZORUNDA.
        # Yoksa "shampoo for thinning hair women" -> "hair fibers for thinning
        # hair for women" gibi BASKA BIR URUNUN sorgusuna baglaniyor ve yanlis
        # CVR atiyordu. Yanlis veri, veri yoklugundan kotudur.
        if require_tokens and not (require_tokens & qt):
            continue
        # Jaccard: tek yonlu kapsama, dar keyword'u cok daha genis sorguya
        # baglayip yanlis hacim/CVR veriyordu.
        score = len(inter) / len(kt | qt)
        if score > best_score or (score == best_score and best and d["clicks"] > best["clicks"]):
            best, best_score, best_q = d, score, q
    if best is not None and best_score >= 0.6:
        out = dict(best)
        out["matched_query"] = best_q
        out["match_score"] = round(best_score, 2)
        return out, "partial"
    return None, None


def diagnose_discovery(rows, probe_bid=None):
    """FAZ 0 sonucunu teshis eder: ne oldu, simdi ne yapmali?

    Kesif fazi 'veri gelmedi' diye biterse kullanici ne yapacagini bilmeli.
    Her sonucun tek bir net eylemi vardir.
    """
    imp = sum((r.get("impressions") or 0) for r in (rows or []))
    clicks = sum((r.get("clicks") or 0) for r in (rows or []))
    spend = sum((r.get("spend") or 0.0) for r in (rows or []))
    orders = sum((r.get("orders") or 0) for r in (rows or []))
    cpc = (spend / clicks) if clicks else None

    d = {"impressions": imp, "clicks": clicks, "spend": round(spend, 2),
         "orders": orders, "measured_cpc": round(cpc, 2) if cpc else None}

    if imp == 0:
        d.update(status="gosterim_yok", headline="Hiç gösterim gelmedi.",
                 cause="Reklam yayınlanmadı — bu bir bid sorunu değil, uygunluk sorunu.",
                 actions=[
                     "Kampanya gerçekten 'enabled' mı, bütçe bitmiş mi kontrol et.",
                     "Ürün Buy Box'a sahip mi? Buy Box yoksa reklam yayınlanmaz.",
                     "Stok var mı? Stoksuz ürün reklam alamaz.",
                     "Listing yeni ise Amazon'un indekslemesi 24-48 saat sürebilir.",
                     "Kısıtlı kelime olabilir (sağlık iddiası vb.) — reddedilen "
                     "keyword var mı bak.",
                 ])
    elif clicks == 0:
        ctr = 0.0
        d.update(status="tiklama_yok", ctr_pct=0.0,
                 headline=f"{imp:,.0f} gösterim geldi ama hiç tıklama yok.",
                 cause="Reklam yayınlanıyor; sorun listing çekiciliğinde.",
                 actions=[
                     "Ana görseli gözden geçir — tıklamayı belirleyen ilk şey odur.",
                     "Fiyatın rakiplerin çok üstünde mi? Arama sonucunda fiyat görünür.",
                     "Yıldız/yorum yokluğu tıklamayı düşürür; ilk yorumları hızlandır.",
                     "Başlık arama sonucunda kesiliyor olabilir; ilk 60 karakteri güçlendir.",
                 ])
    elif clicks < MIN_CLICKS_CPC:
        need = MIN_CLICKS_CPC - clicks
        d.update(status="veri_az", headline=f"Sadece {clicks} tıklama — CPC ölçümü için yetersiz.",
                 cause=f"Güvenilir CPC için en az {MIN_CLICKS_CPC} tıklama gerekir.",
                 actions=[
                     f"Keşfi {need} tıklama daha sürdür (2-3 gün yeter).",
                     "Gösterim azsa teklifi %30 artır; bütçeyi değil.",
                     "Bütçe her gün bitiyorsa bütçeyi artır; teklifi değil.",
                 ])
    else:
        err = 40.0 / (clicks ** 0.5)
        note = (f"CPC ölçüldü: ${cpc:.2f} (±%{err:.0f}, {clicks} tıklama). "
                f"Artık bid hesabı varsayıma değil ölçüme dayanıyor.")
        acts = ["Raporu bu markaya yükle, Faz 1 planını üret."]
        if orders == 0:
            acts.append(f"Sipariş gelmemesi bu fazda normaldir — {clicks} tıklama "
                        f"CVR ölçmeye yetmez (~{MIN_CLICKS_CVR} gerekir).")
        d.update(status="basarili", headline=note, cause="", actions=acts)
    return d


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


def resolve(rows=None, ba_rows=None, brand_id=None, brand_name=None,
            category_tokens=None, ramp=LAUNCH_RAMP, override_cpc=None,
            assumed_cvr=None):
    """Lansman referanslarini belirler. MARKA IZOLASYONU ZORUNLUDUR.

    rows / ba_rows YALNIZCA plani yapilan markaya ait olmalidir; cagiran taraf
    bunu brand_id ile filtreleyerek getirir. Bu fonksiyon baska bir markanin
    verisine ASLA basvurmaz ve veri yoksa uydurmaz - "veri yok" der.

    Kaynak onceligi:
      CVR: markanin kendi reklam olcumu > kendi Brand Analytics pazar verisi
           > kullanicinin girdigi varsayim > (hicbiri yoksa) VARSAYIM YOK
      CPC: kullanici girdisi > markanin kendi olculmus CPC'si
           > (hicbiri yoksa) OLCUM YOK - pazar capali stratejiler kapatilir
    """
    m = measure(rows) if rows else {}
    acct = m.get("_account") or {}
    qs = query_stats(ba_rows) if ba_rows else {}

    warnings = []
    scope = {"brand_id": brand_id, "brand_name": brand_name,
             "ad_rows": len(rows or []), "ba_rows": len(ba_rows or [])}

    # ---------------- CVR temeli ----------------
    base_cvr, cvr_basis = None, None
    if acct.get("clicks", 0) >= MIN_CLICKS_CVR and acct.get("cvr"):
        base_cvr = acct["cvr"]
        cvr_basis = (f"{brand_name or 'marka'} kendi reklam verisi "
                     f"(%{base_cvr*100:.2f}, {acct['clicks']:.0f} tik)")
    elif qs:
        cat = category_cvr(qs, set(category_tokens or []) or None)
        if cat:
            base_cvr = cat
            cvr_basis = (f"{brand_name or 'marka'} Brand Analytics pazar CVR'i "
                         f"(%{cat*100:.2f})")
    if base_cvr is None and assumed_cvr:
        base_cvr = float(assumed_cvr)
        cvr_basis = f"kullanici varsayimi (%{base_cvr*100:.2f})"
    if base_cvr is None:
        base_cvr = FALLBACK_CVR
        cvr_basis = f"⚠ VARSAYIM (%{FALLBACK_CVR*100:.0f}) - bu marka icin olcum yok"
        warnings.append(
            f"Bu marka icin OLCULMUS CVR yok; %{FALLBACK_CVR*100:.0f} varsayimi "
            f"kullanildi. Bu sayi hicbir markadan turetilmedi, sadece bir "
            f"baslangic noktasidir. Markanin reklam raporunu ya da Brand "
            f"Analytics verisini yukle, veya beklenen CVR'i elle gir.")

    # ---------------- CPC temeli ----------------
    base_cpc, cpc_basis = None, None
    if override_cpc:
        base_cpc = float(override_cpc)
        cpc_basis = f"kullanici girdi (${base_cpc:.2f})"
    elif acct.get("clicks", 0) >= MIN_CLICKS_CPC and acct.get("cpc"):
        base_cpc = acct["cpc"]
        n = acct["clicks"]
        # +-hata payi: tiklama sayisi arttikca daralir (~%40 degisim katsayisi)
        err = 40.0 / (n ** 0.5)
        cpc_basis = (f"{brand_name or 'marka'} kendi olculmus CPC'si "
                     f"(${base_cpc:.2f}, {n:.0f} tik, ±%{err:.0f})")
        if n < MIN_CLICKS_CVR:
            warnings.append(
                f"CPC {n:.0f} tiklamayla olculdu (±%{err:.0f}) - bid hesabi icin "
                f"yeterli. Ama CVR bu veriyle guvenilir degil; onun icin "
                f"~{MIN_CLICKS_CVR} tiklama gerekir.")
    else:
        warnings.append("Bu marka icin OLCULMUS CPC yok. Reklam acilmadan CPC "
                        "olculemez; pazar capali stratejiler (Dengeli/Pazar "
                        "Payi) guvenilir degildir. Ilk 2-3 gunun gercek CPC'si "
                        "olcup yeniden hesapla.")
        cpc_basis = "veri yok"

    # ---------------- match type dagilimi ----------------
    cvr, cpc, src = {}, {}, {}
    for key in MATCH_KEYS:
        got = m.get(key) or {}
        if got.get("clicks", 0) >= MIN_CLICKS_CVR and got.get("cvr") is not None:
            v = got["cvr"]
            src[key] = "olculdu (bu marka)"
        elif base_cvr is not None:
            v = base_cvr * RELATIVE_CVR[key]
            src[key] = cvr_basis
        else:
            v = None
            src[key] = "veri yok"
        cvr[key] = round(max(0.005, v * ramp), 4) if v is not None else None

        if got.get("clicks", 0) >= MIN_CLICKS_CPC and got.get("cpc"):
            cpc[key] = round(got["cpc"], 2)
        elif base_cpc is not None:
            cpc[key] = round(base_cpc * RELATIVE_CPC[key], 2)
        else:
            cpc[key] = None

    return {
        "cvr": cvr, "cpc": cpc, "cvr_source": src,
        "cvr_basis": cvr_basis, "cpc_source": cpc_basis,
        "ramp": ramp, "account": acct or None,
        "query_stats": qs, "scope": scope, "warnings": warnings,
        "has_cvr": base_cvr is not None or any(v for v in cvr.values()),
        "has_cpc": base_cpc is not None or any(v for v in cpc.values()),
        "calibration_note": ("Tum sayilar YALNIZCA bu markanin verisinden; "
                            "baska marka verisi kullanilmaz."),
    }
