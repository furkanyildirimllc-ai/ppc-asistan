"""Brand Analytics verisinden ciro odakli reklam firsatlari uretir.

Reklam raporlari sadece SENIN harcamani gosterir. Brand Analytics ise PAZARIN
tamamini gosterir: bir arama teriminde toplam kac tiklama/satis var ve bunun
yuzde kaci sende. Iki veriyi kesistirince su soruyu cevaplayabiliyoruz:

    "Hangi kelimede para var ama ben orada yokum?"

Kovalar:
  WHITESPACE  - Pazar buyuk, senin payin ~0, hic reklam da vermemissin -> YENI KAMPANYA
  RETRY       - Payin ~0 ama daha once reklam vermissin ve tutmamis -> once sebebi coz
  SCALE       - Tiklama payin gosterim payindan buyuk (listing guclu, gorunurluk eksik) -> BID ARTIR
  LEAK        - Gosterim payin var ama satisa donmuyor (listing/fiyat sorunu) -> reklam degil listing isi
  DEFEND      - Her asamada lidersin -> bid koru, savun
"""
import math
import re

# Anlamsiz tokenlar - kategori sozlugune girmemeli
STOPWORDS = {
    "for", "and", "with", "the", "of", "a", "an", "in", "on", "to", "by",
    "or", "not", "no", "non", "best", "top", "new", "my", "your", "you",
    "it", "is", "are", "that", "this", "from", "at", "as", "all", "more",
    "oz", "fl", "ml", "pack", "size", "count", "ct", "pcs", "piece",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return [t for t in TOKEN_RE.findall(str(text or "").lower())
            if t not in STOPWORDS and len(t) > 2]


# Urun basliklarindaki pazarlama dolgusu. Bunlar alaka kaniti degildir -
# 'for men', 'long lasting', 'sulfate free' her kategoride geciyor.
TITLE_FILLER = {
    "men", "women", "unisex", "kids", "natural", "naturally", "free", "formula",
    "professional", "premium", "exclusive", "suitable", "types", "type", "use",
    "deep", "long", "lasting", "instant", "lightweight", "strong", "medium",
    "light", "extra", "super", "ultra", "daily", "care", "solution", "pack",
    "dual", "bundle", "set", "value", "quality", "made", "one", "two",
    "resistant", "proof", "waterproof", "water", "sweat", "greasy", "non",
    "finish", "look", "hold", "shade", "size", "large", "small", "new",
    "extract", "leaf", "based", "with", "and", "add", "adds",
    # Renk kelimeleri: urun basliginda 'One Shade for Black Brown & Grey Hair'
    # gibi gecer. Alaka kaniti degildir - 'black hair dye' bu yuzden yanlislikla
    # sac kapaticiya eslesiyordu.
    "black", "brown", "grey", "gray", "white", "blonde", "blond", "red",
    "green", "blue", "dark", "golden", "silver", "color", "colour", "shades",
}


# Baslikta olumsuzlanan ozellikleri yakalar: 'Non-Fiber', 'Sulfate-Free',
# 'SLS Free', 'no fiber', 'without parabens'.
NEG_RE = re.compile(
    r"\bnon[\s\-]+([a-z]+)|\bno[\s\-]+([a-z]+)|\bwithout\s+([a-z]+)|"
    r"\b([a-z]+)[\s\-]+free\b", re.IGNORECASE)


def negated_tokens(title):
    """Baslikta OLUMSUZLANAN kelimeler.

    Kritik: urun 'Non-Fiber Scalp Concealer' ise, 'fiber' bu urunun ozelligi
    DEGIL - tam tersi. Duz tokenlere ayirinca 'non' stopword'e takilip dusuyor
    ve geriye 'fiber' olumlu kelime gibi kaliyordu; boylece 'hair fibers'
    aramasi sac kapaticiya alakali sayiliyordu. Halbuki fiber isteyen musteri
    baska bir urun tipi ariyor.
    """
    out = set()
    for m in NEG_RE.finditer(str(title or "")):
        for g in m.groups():
            if g and len(g) > 2:
                out.add(g.lower())
    return out


def _is_filler(tok):
    """Dolgu kelime mi? Olcu/miktar iceren tokenlar ('500ml', '30ml', '3') da
    urun kimligi tasimaz."""
    return tok in TITLE_FILLER or any(ch.isdigit() for ch in tok)

# Bir tokenin markanin KENDI urunlerinin bu oranindan fazlasinda geciyorsa
# 'capa kelime'dir (orn 'hair'): kategoriyi isaret eder ama hangi urun
# oldugunu ayirt etmez. Tek basina alaka kaniti sayilmaz.
ANCHOR_RATIO = 0.5


def _stem_eq(a, b):
    """Cogul/yapim eki farklarini tolere eden token esitligi.

    'texture' ile 'texturizing', 'fiber' ile 'fibers' ayni kavramdir.
    Tam esitlik ararsak bu eslesmeleri kaciririz; serbest birakirsak
    'hair' ile 'hairline' karisir. Ortak on-ek >=5 harf makul denge.
    """
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5:
        return False
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 5


def _tok_in(tok, token_set):
    return any(_stem_eq(tok, t) for t in token_set)


def product_profiles(catalog, brand_toks=None):
    """Her ASIN icin baslikitan bir kelime profili cikarir.

    Amac: 'bu arama terimi HANGI urunume ait' sorusunu cevaplamak. Marka
    seviyesinde tek havuz sozluk kullanmak, 'hair dye' gibi hicbir urunune
    uymayan kelimeleri 'hair' ortakligi yuzunden alakali gosteriyordu.

    DIKKAT - marka adi kelimeleri BURADA ELENMEZ. Marka adi kategori kelimesi
    icerebilir ('BATCI HAIR ATELIER'); elenirse 'hair' gibi en onemli capa
    kelime kaybolur ve 'hair concealer' bile eslesmez. Bunun yerine capa
    mekanizmasi isi dogru yapiyor: kataloğun cogunda gecen kelime ('hair',
    'batci') zaten capa sayilip tek basina alaka kaniti olmaktan cikiyor.
    """
    prods = []
    for row in catalog or []:
        neg = negated_tokens(row.get("title"))
        toks = [t for t in _tokens(row.get("title"))
                if not _is_filler(t) and t not in neg]
        if not toks:
            continue
        prods.append({"asin": row.get("asin"), "title": row.get("title"),
                      "price": row.get("price"), "purchases": row.get("purchases") or 0,
                      "tokens": set(toks), "negated": neg})
    if not prods:
        return [], set()
    # Capa kelimeler: kataloğun cogunda gecenler ('hair'). Kategoriyi gosterir
    # ama urun ayirt etmez.
    df = {}
    for p in prods:
        for t in p["tokens"]:
            df[t] = df.get(t, 0) + 1
    anchors = {t for t, n in df.items() if n / len(prods) > ANCHOR_RATIO}
    for p in prods:
        p["distinctive"] = p["tokens"] - anchors
    # KATALOG GENELI OLUMSUZLAMA: bir kelime bir urunde olumsuzlaniyorsa
    # ('Non-Fiber') ve hicbir urunde olumlu gecmiyorsa, bu marka o seyi
    # SATMIYOR demektir. Sadece o urunde elemek yetmiyor - 'hair fibers'
    # aramasi, fiber'dan hic bahsetmeyen baska bir concealer listing'ine
    # 'thinning' uzerinden eslesip yine geciyordu.
    all_pos = set().union(*(p["tokens"] for p in prods)) if prods else set()
    all_neg = set().union(*(p.get("negated") or set() for p in prods)) if prods else set()
    global_neg = {t for t in all_neg if not _tok_in(t, all_pos)}
    for p in prods:
        p["negated"] = (p.get("negated") or set()) | global_neg
    return group_families(prods), anchors


# Iki urunun ayirt edici kelimelerinin bu oraninin ustunde ortusmesi, ayni
# urunun varyanti (farkli boy/paket/renk) oldugu anlamina gelir.
FAMILY_SIMILARITY = 0.6


def group_families(prods):
    """Ayni urunun varyantlarini tek 'aile'de birlestirir.

    Katalogda ayni urunun 6 ASIN'i olabilir (30ml, 50ml, ikili paket, farkli
    listing). Bunlari ayri urun saymak kelimeleri aralarinda boluyor: her biri
    az kelimeli, az butceli kampanya oluyor ve hangisinin calistigi anlasilmiyor.
    Aile olarak birlestirip reklami EN COK SATAN varyanta veriyoruz - reklam
    butcesi zaten donusen listing'e gitmeli.
    """
    fams = []
    for p in sorted(prods, key=lambda x: -x["purchases"]):
        placed = False
        for f in fams:
            a, b = p["distinctive"], f["distinctive"]
            if a and b:
                sim = len(a & b) / len(a | b)
                if sim >= FAMILY_SIMILARITY:
                    # Aile kelime havuzunu genislet, temsilci degismez
                    f["tokens"] |= p["tokens"]
                    f["distinctive"] |= p["distinctive"]
                    f["negated"] |= p.get("negated") or set()
                    f["variants"].append(p["asin"])
                    placed = True
                    break
        if not placed:
            fams.append({**p, "variants": [p["asin"]]})
    return fams


def match_product(query, profiles, anchors):
    """Arama terimini en uygun urune baglar. Uymuyorsa None.

    KURAL: en az 2 token ortusmeli VE bunlardan en az 1'i ayirt edici olmali.
    Bu tek kural kullanicinin sikayet ettigi vakalari cozer:
      'concealer'      -> 1 ayirt edici, 0 capa = 1 toplam  -> RED (makyaj kapatici)
      'hair concealer' -> concealer + hair       = 2 toplam -> KABUL
      'hair dye'       -> 0 ayirt edici          -> RED (hair dye satmiyoruz)
      'hair'           -> 0 ayirt edici          -> RED (cok genel)
      'sea salt spray' -> sea + salt ayirt edici -> KABUL (Sea Salt urunu)
    """
    qt = _tokens(query)
    if not qt:
        return None
    q_neg = negated_tokens(query)
    best = None
    for p in profiles:
        # Urunun OLUMSUZLADIGI ozelligi ARAYAN sorguyu eleme:
        # urun 'Non-Fiber' ise 'hair fibers' arayan musteri baska bir urun
        # tipi istiyor demektir. Sorgu da olumsuzluyorsa ('fiber free')
        # sorun yok - o zaman ayni seyi istiyorlar.
        if any(_tok_in(t, p.get("negated") or set()) and t not in q_neg for t in qt):
            continue
        dist = [t for t in qt if _tok_in(t, p["distinctive"])]
        anch = [t for t in qt if _tok_in(t, anchors)]
        if not dist or (len(dist) + len(anch)) < 2:
            continue
        # Skor: ayirt edici eslesmeler agir basar; sorgunun ne kadari kapsandi
        score = (len(dist) * 2 + len(anch)) / (len(qt) + 1)
        cand = {"asin": p["asin"], "title": p["title"], "price": p["price"],
                "purchases": p["purchases"], "score": round(score, 3),
                "matched": sorted(set(dist + anch))}
        # Esitlikte cok satan urunu sec - reklam butcesi oraya gitmeli
        if best is None or (cand["score"], cand["purchases"]) > (best["score"], best["purchases"]):
            best = cand
    return best


def _brand_tokens(brand_name, catalog):
    """Markanin kendi adindaki tokenlar. Bunlar kategori sozlugune girmemeli -
    yoksa 'batci' gecen her sey alakali sayilir, genel kelimeler kacar."""
    toks = set(_tokens(brand_name))
    for row in catalog or []:
        title = row.get("title") or ""
        # Baslik genelde 'MARKA Urun Adi ...' seklinde - ilk 2 kelime marka olabilir
        first = _tokens(title)[:2]
        for t in first:
            if t in toks:
                continue
    return toks


def build_vocabulary(queries, brand_name="", catalog=None):
    """Kategori sozlugunu VERIDEN ogrenir, elle liste yazmadan.

    Mantik: markanin gercekten SATIS yaptigi arama terimlerinin kelimeleri, o
    kategorinin dilidir. 'concealer', 'thinning', 'scalp' gibi. Bu sozluk daha
    sonra 'bu yeni kelime bana uygun mu' filtresi olarak kullanilir.

    Neden elle liste degil: her marka/kategori icin ayri liste yazmak gerekirdi
    ve yeni urun ekleyince bayatlardi. Veriden ogrenince otomatik guncellenir.
    """
    bt = _brand_tokens(brand_name, catalog)
    weights = {}
    for q in queries:
        sold = q.get("pur_brand") or 0
        if sold <= 0:
            continue
        for t in _tokens(q.get("query")):
            if t in bt:
                continue
            weights[t] = weights.get(t, 0) + sold
    # Katalog basliklarindaki kelimeler de kategori dilidir (satis olmasa bile)
    for row in catalog or []:
        for t in _tokens(row.get("title")):
            if t in bt:
                continue
            weights.setdefault(t, 0)
            weights[t] += 1
    return weights, bt


def find_foreign_brands(queries, vocab, brand_toks, min_volume=20000,
                        max_queries=6, known=None, not_brands=None,
                        catalog_tokens=None):
    """Rakip/yabanci marka adlarini VERIDEN tahmin eder.

    Ayirt edici sinyaller:
      1. Markanin sattigi hicbir terimde gecmiyor (vocab agirligi 0)
      2. Buna ragmen buyuk hacim topluyor
      3. Az sayida farkli sorguda geciyor - marka adlari dar kullanilir,
         jenerik kelimeler ('stick', 'powder') onlarca kombinasyonda gecer

    DIKKAT - BU TAHMIN GUVENILIR DEGIL, kesin bir ayrim yoktur. Olculen ornekler:

        accessories  309.485 hacim / 2 sorgu   -> JENERIK
        nizoral      600.261 hacim / 2 sorgu   -> MARKA
        balmain        8.944 hacim / 1 sorgu   -> MARKA
        base           8.519 hacim / 2 sorgu   -> JENERIK

    Yani hacim ve sorgu sayisi markayi jenerikten AYIRAMAZ. Esik bilerek
    hassasiyet lehine (yuksek) secildi: yanlis pozitif, mesru bir jenerik
    kelimeyi kucuk butceli 'rakip marka' kovasina hapseder - bu, birkac
    markayi kacirmaktan daha pahalidir. Kacanlar UI'daki listeden elle
    eklenir (`known`), yanlis yakalananlar `not_brands` ile cikarilir.
    """
    vol_by_token, nq_by_token = {}, {}
    for q in queries:
        v = q.get("volume") or 0
        for t in set(_tokens(q.get("query"))):
            vol_by_token[t] = vol_by_token.get(t, 0) + v
            nq_by_token[t] = nq_by_token.get(t, 0) + 1
    # Katalogdaki kelimeler ASLA rakip marka degildir - kendi urun dilin.
    # Bu filtre sayesinde hacim esigini cok dusurebiliyoruz ('loreal' 31K,
    # 'neutrogena' 1K hacimdeydi ve eski 50K esigine takilip kaciyordu).
    cat_toks = catalog_tokens or set()
    cand = {t: v for t, v in vol_by_token.items()
            if v >= min_volume and vocab.get(t, 0) <= 0
            and nq_by_token.get(t, 0) <= max_queries
            and t not in brand_toks and not _tok_in(t, cat_toks)}

    confirmed = {t.lower().strip() for t in (known or []) if t.strip()}
    denied = {t.lower().strip() for t in (not_brands or [])}

    # SINIFLANDIRMAYI SADECE KULLANICI ONAYI SURUKLER.
    #
    # Yuksek hacimli bandi otomatik uygulamayi denedik; o bantta bile liste
    # soyle cikti: nizoral, k18, takis (dogru) yaninda rosemary, ketoconazole,
    # clay, chalk, growth, human (hepsi jenerik). Yani ~%50 yanlis. Hacim ve
    # sorgu sayisi bir marka adini jenerik bir kelimeden ayirt etmiyor ve
    # baska sinyalimiz yok.
    #
    # Yanlis pozitifin bedeli somut: mesru bir jenerik kelime dusuk CVR
    # varsayimiyla kucuk butceli 'rakip marka' kovasina hapsolur ve gercek
    # ciro firsati kaybedilir. Bu yuzden tahmin ONERI olarak sunulur,
    # uygulanmaz. Kullanici tek tikla onaylar - o bilgi bizde yok, onda var.
    active = confirmed - denied - brand_toks
    suspect = sorted(((t, cand[t]) for t in cand
                      if t not in active and t not in denied),
                     key=lambda kv: -kv[1])
    return active, [{"token": t, "volume": v} for t, v in suspect[:30]]


def relevance(query, vocab, brand_toks):
    """0-1 arasi alaka skoru + kisa gerekce.

    Bir sorgunun kelimelerinin kaci kategori sozlugunde geciyor? Hicbiri
    gecmiyorsa bu buyuk ihtimalle baska bir kategori ya da rakip marka adi.
    """
    toks = _tokens(query)
    if not toks:
        return 0.0, "bos"
    if any(t in brand_toks for t in toks):
        return 1.0, "kendi markan"
    hits = [t for t in toks if vocab.get(t, 0) > 0]
    if not hits:
        return 0.0, "kategori disi / rakip marka"
    score = len(hits) / len(toks)
    # Sozlukte agir basan kelime varsa skoru yukselt (orn 'concealer')
    top = max(vocab.get(t, 0) for t in hits)
    if top >= max(vocab.values() or [1]) * 0.15:
        score = min(1.0, score + 0.25)
    return round(score, 2), f"eslesen: {', '.join(hits[:4])}"


def _norm_term(s):
    return " ".join(TOKEN_RE.findall(str(s or "").lower()))


def index_ad_history(search_terms):
    """ppc.db'deki search term raporlarini arama terimine gore ozetler.

    Bir kelimede marka payin %0 olabilir ama sebebi iki farkli sey olabilir:
      (a) hic reklam vermemissin        -> gercek firsat
      (b) reklam verdin, para harcadin, donmedi -> firsat degil, tuzak
    Bu ayrimi yapmadan oneri uretmek para yakar.
    """
    idx = {}
    for r in search_terms or []:
        term = _norm_term(r.get("term"))
        if not term:
            continue
        d = idx.setdefault(term, {"clicks": 0, "spend": 0.0, "sales": 0.0,
                                  "orders": 0, "impressions": 0})
        d["impressions"] += r.get("impressions") or 0
        d["clicks"] += r.get("clicks") or 0
        d["spend"] += r.get("spend") or 0
        d["sales"] += r.get("sales") or 0
        d["orders"] += r.get("orders") or 0
    for d in idx.values():
        d["acos"] = round(d["spend"] / d["sales"] * 100, 1) if d["sales"] else None
        d["cpc"] = round(d["spend"] / d["clicks"], 2) if d["clicks"] else None
    return idx


def economics(profit, fallback_price=0.0):
    """Marka ekonomisinden hedef ACOS ve break-even cikarir."""
    if profit and profit.get("break_even_acos_pct"):
        be = profit["break_even_acos_pct"] / 100.0
        target = (profit.get("recommended_target_acos_pct") or
                  profit["break_even_acos_pct"] * 0.7) / 100.0
        return {"break_even_acos": be, "target_acos": target,
                "price": fallback_price, "source": "marka ekonomisi"}
    # Ekonomi girilmemisse sektor varsayimi: %30 hedef ACOS
    return {"break_even_acos": 0.40, "target_acos": 0.30,
            "price": fallback_price, "source": "varsayilan (marka ekonomisi girilmemis)"}


# Yeni kampanya ilk aylarda pazar ortalamasinin altinda donusur (listing
# olgunlasmamis, review az, Amazon algoritmasi ogreniyor). Pazar CVR'ini
# oldugu gibi almak bid'i sisirir - bu carpanla temkinli davraniyoruz.
RAMP_FACTOR = 0.70
# Yeni bir kelimede gercekci olarak yakalanabilecek tiklama payi.
CAPTURE_RATE = 0.05
# Rakip marka aramasinda ('nizoral shampoo') musteri o markayi ariyordur.
# Senin urunun oradaki pazar CVR'ine hicbir zaman ulasmaz.
CONQUEST_CVR_FACTOR = 0.25
CONQUEST_CAPTURE = 0.01


def brand_proven_cvr(catalog):
    """Markanin KENDI kanitlanmis tiklama->satis oranı (%).

    Bu tavan olmadan projeksiyon fanteziye donuyor: 'nizoral anti-dandruff
    shampoo' teriminde pazar CVR'i %35, cunku o terimde satan urun Nizoral'in
    kendisi. Senin urunun orada %35 donmeyecegi bellidir. Kendi katalogunun
    gercek donusum orani, herhangi bir yeni kelimede beklenebilecek makul
    tavandir.
    """
    tot_c = sum(c.get("clicks") or 0 for c in catalog or [])
    tot_p = sum(c.get("purchases") or 0 for c in catalog or [])
    return (tot_p / tot_c * 100) if tot_c else 0.0


def bid_math(q, econ, ceiling_cvr=0.0, is_conquest=False, product_price=None):
    """Bir arama terimi icin karli max bid ve ciro projeksiyonu.

    max CPC = AOV x beklenen CVR x hedef ACOS
    Bu formul sektor standardidir: hedef ACOS'u tutturmak icin bir tiklamaya
    en fazla ne verebilecegini soyler. Girdilerin gercekci olmasi sarttir -
    sisirilmis CVR veya bozuk fiyat, dogrudan sisirilmis bid demektir.
    """
    # AOV: bu kelimenin baglandigi URUNUN fiyati en dogrusu - katalog $19.95 ile
    # $79.90 arasi degisiyor, marka ortalamasi kullanmak ucuz urune fazla,
    # pahali urune az bid verdirir.
    ref = product_price or econ.get("price") or 0
    aov = ref if (product_price or 0) > 0 else 0
    if aov <= 0:
        aov = q.get("brand_price") or q.get("brand_click_price") or 0
        # Rapordaki marka fiyati bazen bozuk gelir (bos/agregat hatasi);
        # makul araligin disindaysa kendi referans fiyatina don.
        if ref > 0 and not (ref * 0.3 <= aov <= ref * 3):
            aov = ref
    if aov <= 0:
        aov = q.get("market_price") or q.get("click_price") or 0

    market_cvr = (q.get("market_cvr") or 0)
    exp_cvr = market_cvr * (CONQUEST_CVR_FACTOR if is_conquest else RAMP_FACTOR)
    capped_by = None
    if ceiling_cvr > 0 and exp_cvr > ceiling_cvr:
        exp_cvr, capped_by = ceiling_cvr, "kendi kanitlanmis CVR'in"
    exp_cvr /= 100.0

    max_bid = aov * exp_cvr * econ["target_acos"]
    be_bid = aov * exp_cvr * econ["break_even_acos"]
    start_bid = max_bid * 0.75  # ogrenme fazinda temkinli basla

    capture = CONQUEST_CAPTURE if is_conquest else CAPTURE_RATE
    est_clicks = (q.get("clicks_total") or 0) * capture
    est_orders = est_clicks * exp_cvr
    est_revenue = est_orders * aov
    est_spend = est_clicks * start_bid
    return {
        "aov": round(aov, 2),
        "market_cvr_pct": round(market_cvr, 2),
        "expected_cvr_pct": round(exp_cvr * 100, 2),
        "cvr_capped_by": capped_by,
        "max_bid": round(max_bid, 2),
        "break_even_bid": round(be_bid, 2),
        "start_bid": round(start_bid, 2),
        "est_clicks": round(est_clicks),
        "est_orders": round(est_orders, 1),
        "est_revenue": round(est_revenue, 2),
        "est_spend": round(est_spend, 2),
        "est_acos_pct": round(est_spend / est_revenue * 100, 1) if est_revenue else None,
    }


def classify(q, hist, min_relevance):
    """Arama terimini kovaya atar. -> (bucket, gerekce) veya (None, sebep)"""
    imp_s = q.get("imp_share") or 0
    clk_s = q.get("click_share") or 0
    pur_s = q.get("pur_share") or 0

    if pur_s >= 40 and imp_s >= 25:
        return "DEFEND", f"Satin alma payin %{pur_s:.0f} - bu kelimede lidersin"
    if imp_s >= 10 and pur_s < imp_s * 0.5:
        return "LEAK", (f"Gosterim payin %{imp_s:.0f} ama satin alma payin "
                        f"%{pur_s:.0f}. Trafigi aliyorsun, satamiyorsun - "
                        f"listing/fiyat sorunu, bid degil")
    if clk_s > imp_s * 1.25 and imp_s < 40 and clk_s > 0:
        return "SCALE", (f"Tiklama payin (%{clk_s:.0f}) gosterim payindan "
                         f"(%{imp_s:.0f}) buyuk - listingin guclu ama yeterince "
                         f"gorunmuyorsun. Bid/butce artir")
    if pur_s < 1 and imp_s < 5:
        if hist and hist.get("clicks", 0) >= 10:
            acos = hist.get("acos")
            return "RETRY", (f"Pazarda payin yok ama daha once {hist['clicks']:.0f} "
                             f"tiklama x ${hist['spend']:.0f} harcamissin"
                             + (f", ACOS %{acos:.0f}" if acos else ", hic satis yok")
                             + ". Yeniden acmadan once sebebini coz")
        return "WHITESPACE", "Pazar aktif, sen bu kelimede hic yoksun"
    return None, "belirgin firsat yok"


def analyze(queries, search_terms=None, catalog=None, basket=None,
            brand_name="", profit=None, min_volume=200, min_relevance=0.34,
            limit_per_bucket=50, known_brands=None, not_brands=None):
    """Ana giris noktasi. -> kovalara ayrilmis, siralanmis firsat listesi."""
    if not queries:
        return {"error": "Brand Analytics arama terimi raporu yuklenmemis",
                "buckets": {}, "summary": {}}

    vocab, brand_toks = build_vocabulary(queries, brand_name, catalog)
    profiles, anchors = product_profiles(catalog)
    cat_toks = set().union(*(p["tokens"] for p in profiles)) if profiles else set()
    foreign, suspect_brands = find_foreign_brands(
        queries, vocab, brand_toks, known=known_brands, not_brands=not_brands,
        catalog_tokens=cat_toks)
    hist = index_ad_history(search_terms)

    # Medyan satis fiyati - ekonomi girilmemisse ve rapordaki fiyat bozuksa yedek
    prices = sorted(c.get("price") for c in (catalog or []) if (c.get("price") or 0) > 0)
    med_price = prices[len(prices) // 2] if prices else 0
    econ = economics(profit, med_price)
    ceiling = brand_proven_cvr(catalog)

    buckets = {"WHITESPACE": [], "CONQUEST": [], "RETRY": [],
               "SCALE": [], "LEAK": [], "DEFEND": []}
    skipped = {"dusuk_hacim": 0, "alakasiz": 0, "firsat_yok": 0, "asin": 0,
               "urun_eslesmedi": 0}
    rejected = []  # seffaflik: neyi neden eledigimizi kullaniciya gosterebilmek icin

    for q in queries:
        if q.get("is_asin"):
            skipped["asin"] += 1
            continue
        if (q.get("volume") or 0) < min_volume:
            skipped["dusuk_hacim"] += 1
            continue
        rel, rel_why = relevance(q.get("query"), vocab, brand_toks)
        h = hist.get(_norm_term(q.get("query")))
        bucket, why = classify(q, h, min_relevance)
        if bucket is None:
            skipped["firsat_yok"] += 1
            continue

        hit_brands = sorted(set(_tokens(q.get("query"))) & foreign)
        # Rakip marka aramasi ayri bir oyundur: bid mantigi, CVR beklentisi ve
        # yasal risk farkli. Jenerik whitespace ile ayni kovada gosterilmemeli.
        if hit_brands and bucket in ("WHITESPACE", "RETRY"):
            bucket = "CONQUEST"
            why = (f"Rakip marka aramasi ({', '.join(hit_brands)}). Musteri o "
                   f"markayi ariyor - dusuk CVR bekle, kucuk butceyle test et")

        # URUN ESLESMESI - yeni kampanya acilacak kovalarda ZORUNLU.
        # Reklam hep bir ASIN'e verilir; hangi urune reklam verecegimizi
        # bilmiyorsak o kelimeyi onermek anlamsizdir. Marka seviyesinde
        # kelime ortakligi yetmiyor: 'hair dye' de 'hair' iceriyor ama
        # sac boyasi satmiyoruz.
        prod = match_product(q.get("query"), profiles, anchors) if profiles else None
        if bucket in ("WHITESPACE", "RETRY", "CONQUEST"):
            if profiles and not prod:
                skipped["urun_eslesmedi"] += 1
                # Genis tutuyoruz: negatif keyword onerisi bu listeden uretiliyor
                # ve dusuk hacimli bir terimde de para yaniyor olabilir.
                if len(rejected) < 500:
                    rejected.append({"query": q.get("query"),
                                     "volume": q.get("volume"),
                                     "why": "Hicbir urununle eslesmedi"})
                continue
            if not profiles and rel < min_relevance:
                # Katalog raporu yoksa urun eslesmesi yapilamaz - eski
                # sozluk bazli filtreye dus (daha zayif ama hicten iyi).
                skipped["alakasiz"] += 1
                continue

        m = bid_math(q, econ, ceiling_cvr=ceiling,
                     is_conquest=bucket == "CONQUEST",
                     product_price=(prod or {}).get("price"))
        buckets[bucket].append({
            "query": q.get("query"),
            "volume": q.get("volume"),
            "relevance": rel,
            "relevance_why": rel_why,
            "reason": why,
            "competitor_brands": hit_brands,
            # Bu kelime hangi urune reklam verecek - bulksheet bunu kullanir
            "product_asin": (prod or {}).get("asin"),
            "product_title": (prod or {}).get("title"),
            "product_match": (prod or {}).get("matched"),
            "imp_share": round(q.get("imp_share") or 0, 1),
            "click_share": round(q.get("click_share") or 0, 1),
            "pur_share": round(q.get("pur_share") or 0, 1),
            "market_clicks": q.get("clicks_total"),
            "market_purchases": q.get("pur_total"),
            "market_cvr": q.get("market_cvr"),
            "market_price": q.get("market_price"),
            "brand_price": q.get("brand_price"),
            "price_gap": (round(q.get("brand_price") - q.get("market_price"), 2)
                          if q.get("brand_price") and q.get("market_price") else None),
            "ad_history": h,
            **m,
        })

    # Siralama: her kovada "en cok ciro getirecek" once
    for k in buckets:
        if k == "LEAK":
            # Kayip buyuklugune gore: cok gosterim alip satamadigin yerler
            buckets[k].sort(key=lambda x: -(x["market_clicks"] or 0) * (x["imp_share"] or 0))
        else:
            buckets[k].sort(key=lambda x: -(x["est_revenue"] or 0))
        buckets[k] = buckets[k][:limit_per_bucket]

    ws = buckets["WHITESPACE"]
    summary = {
        "analyzed_queries": len(queries),
        "vocabulary_size": len(vocab),
        "competitor_brands_detected": sorted(foreign)[:40],
        "competitor_brands_suspect": suspect_brands,
        "product_count": len(profiles),
        "product_matching": bool(profiles),
        "anchor_tokens": sorted(anchors),
        "brand_proven_cvr_pct": round(ceiling, 2),
        "economics": {**econ,
                      "target_acos_pct": round(econ["target_acos"] * 100, 1),
                      "break_even_acos_pct": round(econ["break_even_acos"] * 100, 1)},
        "counts": {k: len(v) for k, v in buckets.items()},
        "skipped": skipped,
        "whitespace_potential": {
            # DIKKAT: donem = yuklenen raporun donemi. Ceyreklik rapor
            # yuklendiyse bu rakamlar ceyreklik, aylik degil.
            "period": (queries[0].get("period") if queries else ""),
            "period_revenue": round(sum(x["est_revenue"] for x in ws), 2),
            "period_spend": round(sum(x["est_spend"] for x in ws), 2),
            "orders": round(sum(x["est_orders"] for x in ws), 1),
            "blended_acos_pct": (
                round(sum(x["est_spend"] for x in ws) /
                      sum(x["est_revenue"] for x in ws) * 100, 1)
                if sum(x["est_revenue"] for x in ws) else None),
        },
        "assumptions": {
            "ramp_factor": RAMP_FACTOR,
            "capture_rate": CAPTURE_RATE,
            "cvr_ceiling_pct": round(ceiling, 2),
            "note": ("Projeksiyon = pazar tiklamalarinin %{:.0f}'ini yakalarsin, "
                     "pazar CVR'inin %{:.0f}'i kadar donersin ve bu deger kendi "
                     "kanitlanmis CVR'ini (%{:.2f}) asamaz varsayimiyla. Donem, "
                     "raporun donemidir - ceyreklik rapor yuklediysen tahmin de "
                     "ceyrekliktir. Bunlar TAHMINDIR, garanti degildir."
                     .format(CAPTURE_RATE * 100, RAMP_FACTOR * 100, ceiling)),
        },
    }
    # Yonlendirme: her satira ozel uyarilar + kova basi plan + genel oncelik
    days = PERIOD_DAYS.get(str(queries[0].get("period") if queries else ""), 90)
    suspect_set = {x["token"] for x in suspect_brands}
    for k, items in buckets.items():
        for o in items:
            o["actions"] = row_actions(o, k, econ, ceiling, suspect_set)
    playbooks = {k: _playbook(k, v, econ, days) for k, v in buckets.items()}

    rejected.sort(key=lambda r: -(r.get("volume") or 0))
    negatives, neg_stats = negative_suggestions(rejected, hist)
    summary["negatives"] = neg_stats
    return {"buckets": buckets, "summary": summary,
            "rejected": rejected[:40],
            "negatives": negatives,
            "playbooks": {k: v for k, v in playbooks.items() if v},
            "action_plan": action_plan(buckets, econ, days),
            "basket": _basket_targets(basket, catalog)}


# Rapor donemi -> gunluk butceye cevirmek icin gun sayisi
PERIOD_DAYS = {"quarterly": 90, "monthly": 30}


def build_campaign_plan(opportunities, asin="", sku="", period="quarterly",
                        match="exact", tiers=3, min_daily_budget=10.0,
                        campaign_prefix="Firsat", negatives=None,
                        max_negatives=25):
    """Secilen firsatlari Amazon'a yuklenebilir kampanya planina cevirir.

    Neden bid katmanlari: launch.build_bulksheet her kampanyaya TEK bir default
    bid verir. Tum kelimeleri tek kampanyaya koyarsak $0.15'lik kelimeye de
    $0.50'lik kelimeye de ayni bid gider - biri bosa harcar, digeri hic
    gosterim almaz. Kelimeleri bid seviyesine gore ayirip her katmani ayri
    kampanya yapmak, tek bid kisitiyla dogru bid'i vermenin yoludur.
    """
    picked = [o for o in opportunities if (o.get("start_bid") or 0) > 0.02]
    if not picked:
        return None

    days = PERIOD_DAYS.get(str(period).lower(), 90)

    # ONCE URUNE GORE AYIR. Bir kampanya tek bir ASIN'e reklam verir; farkli
    # urunlerin kelimelerini ayni kampanyaya koymak, 'sea salt spray'i sac
    # kapaticiya reklam etmek demektir. Urun eslesmesi olmayanlar (katalog
    # raporu yoksa) tek grupta toplanir ve varsayilan ASIN'e gider.
    by_product = {}
    for o in picked:
        by_product.setdefault(o.get("product_asin") or asin or "", []).append(o)

    campaigns = []
    for p_asin, items in sorted(by_product.items(), key=lambda kv: -len(kv[1])):
        title = next((o.get("product_title") for o in items if o.get("product_title")), "")
        label = (title.split("-")[0].split("|")[0].strip()[:28] or p_asin or "Genel")
        items.sort(key=lambda o: o["start_bid"])
        n = max(1, min(tiers, len(items)))
        size = math.ceil(len(items) / n)
        groups = [items[i:i + size] for i in range(0, len(items), size)]
        for i, g in enumerate(groups, 1):
            bids = [o["start_bid"] for o in g]
            # Katman icinde medyan bid: tek bir uc deger katmani surukleyemesin
            bid = round(sorted(bids)[len(bids) // 2], 2)
            daily = max(min_daily_budget, round(sum(o["est_spend"] for o in g) / days, 2))
            lo, hi = min(bids), max(bids)
            # Negatifler: exact kampanyada gereksiz (sadece tam terim eslesir),
            # phrase/broad'da sart. Kampanyanin kelimeleriyle token paylasan
            # alakasiz terimleri sec - yakalanma riski olanlar bunlar.
            negs = []
            if match != "exact" and negatives:
                kw_toks = set()
                for o in g:
                    kw_toks |= set(_tokens(o["query"]))
                for nq in negatives:
                    if set(_tokens(nq)) & kw_toks:
                        negs.append(nq)
                    if len(negs) >= max_negatives:
                        break
            campaigns.append({
                "name": f"{campaign_prefix} | {label} | {match.upper()} | T{i}",
                "targeting_type": "Manual",
                "budget": daily,
                "default_bid": bid,
                "match": match,
                "keywords": [o["query"] for o in g],
                "negatives": negs,
                "auto_groups": False,
                # launch.build_bulksheet bunu okuyup Product Ad satirina yazar
                "asin": p_asin,
                "_meta": {
                    "product_asin": p_asin,
                    "product_title": title,
                    "keyword_count": len(g),
                    "bid_range": [round(lo, 2), round(hi, 2)],
                    "est_period_revenue": round(sum(o["est_revenue"] for o in g), 2),
                    "est_period_spend": round(sum(o["est_spend"] for o in g), 2),
                },
            })

    return {
        "product": {"asin": asin, "sku": sku or asin},
        "campaigns": campaigns,
        "products_used": sorted(by_product.keys()),
        "totals": {
            "campaigns": len(campaigns),
            "keywords": len(picked),
            "daily_budget": round(sum(c["budget"] for c in campaigns), 2),
            "est_period_revenue": round(sum(o["est_revenue"] for o in picked), 2),
            "est_period_spend": round(sum(o["est_spend"] for o in picked), 2),
            "period_days": days,
        },
        "notes": [
            f"{len(campaigns)} kampanya, {len(picked)} keyword, gunluk toplam "
            f"${sum(c['budget'] for c in campaigns):.2f} butce.",
            "Bid'ler hedef ACOS'a gore hesaplandi ve ogrenme fazi icin %25 "
            "dusuruldu. Ilk 2 hafta bid degistirme, veri toplansin.",
            "SKU girilmediyse Product Ad satirlarinda ASIN placeholder olarak "
            "kullanilir - Seller hesabinda GERCEK SKU ile degistir.",
            "Butce projeksiyonu tahmindir. Ilk hafta gercek CPC/CVR'a gore "
            "revize et.",
        ],
    }


# --------------------------------------------------------------- yonlendirme
# Bu bolum kullaniciya "simdi ne yapmaliyim" diye somut adim verir.
# TASARIM KURALI: hicbir metin markaya/urune sabitlenmez. Butun sayilar,
# urun adlari ve esikler o markanin KENDI verisinden gelir - yoksa ikinci
# bir markada anlamsiz tavsiye uretir.

def _pct_diff(a, b):
    return (a - b) / b * 100 if b else 0


def _n(v):
    """Sayiyi Turkce binlik ayracla bicimler: 127747 -> '127.747'.

    Cumlenin tamamina .replace(',', '.') uygulamak virgulleri de bozuyordu
    ('Exact ile basla, gunluk' -> 'Exact ile basla. gunluk'). Sayi bicimleme
    sadece sayida yapilir.
    """
    return f"{v:,.0f}".replace(",", ".")


def row_actions(o, bucket, econ, ceiling_cvr, suspect=None):
    """Tek bir arama terimi icin ona ozel uyari/aksiyon listesi."""
    acts = []
    # Olasi rakip marka: kovayi DEGISTIRMIYORUZ (tahmin guvenilir degil, yanlis
    # kova mesru kelimeyi kucuk butceye hapseder) ama kullanici karar verebilsin
    # diye tam satirin uzerinde uyariyoruz.
    hits = sorted(set(_tokens(o.get("query"))) & (suspect or set()))
    if hits and bucket in ("WHITESPACE", "RETRY"):
        acts.append({"level": "warn", "suspect_brands": hits, "text":
            f"\"{', '.join(hits)}\" rakip marka adi olabilir. Oyleyse dusuk CVR "
            f"bekle ve kucuk butceyle test et - asagidaki marka listesinden "
            f"onaylarsan Rakip Marka kovasina tasinir."})
    price_gap, mp, bp = o.get("price_gap"), o.get("market_price"), o.get("brand_price")
    if price_gap and mp and bp:
        d = _pct_diff(bp, mp)
        if d >= 15:
            acts.append({"level": "warn", "text":
                f"Pazar bu kelimede ${mp:.2f} medyan fiyattan satiyor, sen ${bp:.2f} "
                f"(%{d:.0f} pahali). Donusum dusuk gelirse sebebi bid degil fiyat "
                f"olabilir - ya listing'de fark yarat ya kucuk butceyle test et."})
        elif d <= -15:
            acts.append({"level": "good", "text":
                f"Pazardan %{abs(d):.0f} ucuzsun (${bp:.2f} vs ${mp:.2f}). Fiyat "
                f"avantajin var - bid'de biraz daha agresif olabilirsin."})

    mcvr, ecvr = o.get("market_cvr_pct") or 0, o.get("expected_cvr_pct") or 0
    if o.get("cvr_capped_by") and mcvr > ecvr * 2:
        acts.append({"level": "info", "text":
            f"Pazar bu kelimede %{mcvr:.1f} donuyor ama senin kanitlanmis oranin "
            f"%{ceiling_cvr:.1f}. Tahmini buna gore kistim. Gercek CVR daha yuksek "
            f"cikarsa bid'i artirabilirsin - ilk 2 hafta veriyi izle."})

    h = o.get("ad_history")
    if h and h.get("clicks", 0) >= 5:
        acos, be = h.get("acos"), econ["break_even_acos"] * 100
        if acos and acos > be:
            acts.append({"level": "bad", "text":
                f"Bu kelimede zaten {h['clicks']:.0f} tiklama x ${h['spend']:.0f} "
                f"harcamissin ve ACOS %{acos:.0f} - break-even'in %{be:.0f}. "
                f"Once neden zarar ettigini coz, sonra ac."})
        elif not h.get("sales"):
            acts.append({"level": "bad", "text":
                f"{h['clicks']:.0f} tiklama x ${h['spend']:.0f} harcanmis, HIC satis yok. "
                f"Tiklama geliyorsa sorun listing/fiyat tarafinda."})

    vol = o.get("volume") or 0
    if bucket == "WHITESPACE" and vol > 300000:
        acts.append({"level": "warn", "text":
            f"Cok yuksek hacim ({_n(vol)}). Broad/phrase acarsan butce bir gunde "
            f"biter. Exact ile basla, gunluk butceyi siki tut."})

    if bucket == "CONQUEST":
        acts.append({"level": "warn", "text":
            "Rakip marka terimi: reklam metninde karsilastirma/marka iddiasi kullanma. "
            "Kelime yerine rakip ASIN hedeflemesi genelde daha iyi calisir."})

    if bucket == "LEAK":
        acts.append({"level": "bad", "text":
            "Burada bid ARTIRMA. Trafik zaten geliyor, satisa donmuyor - "
            "ana gorsel, baslik, fiyat ve yorum sayisini kontrol et."})
    return acts


def _playbook(bucket, items, econ, period_days):
    """Kovaya ozel, gercek sayilarla doldurulmus adim adim plan."""
    if not items:
        return None
    n = len(items)
    spend = sum(i["est_spend"] for i in items)
    rev = sum(i["est_revenue"] for i in items)
    daily = spend / period_days if period_days else 0
    bids = sorted(i["start_bid"] for i in items)
    lo, hi = bids[0], bids[-1]
    tacos = econ["target_acos"] * 100
    be = econ["break_even_acos"] * 100
    # Ilk dalgada kac kelime: hepsini birden acmak butceyi ve ogrenmeyi bozar
    wave = min(n, 20)
    prods = sorted({i.get("product_title") for i in items if i.get("product_title")})

    if bucket == "WHITESPACE":
        return {
            "title": "Yeni kampanya acma plani",
            "why": (f"{n} kelimede pazar donuyor ama senin payin yok. Tahmini "
                    f"potansiyel: ${_n(rev)} ciro / ${_n(spend)} harcama."),
            "steps": [
                f"1) URUNE GORE AYIR. Bu kovada {len(prods)} farkli urunun kelimeleri var. "
                f"Ustteki urun filtresinden TEK urun sec, once onu ac. Karisik "
                f"kampanya hem butceyi boler hem hangi urunun calistigini gizler.",
                f"2) ILK DALGA {wave} KELIME. Hepsini birden acma - {n} kelimeyi tek "
                f"seferde acarsan gunluk ${_n(daily)} butce gerekir ve hicbirinden "
                f"anlamli veri toplayamazsin. Hacmi en yuksek {wave} taneyle basla.",
                f"3) EXACT match ile ac. Bid araligi ${lo:.2f}-${hi:.2f} (hedef ACOS "
                f"%{tacos:.0f}'a gore hesaplandi, ogrenme icin %25 dusuruldu).",
                f"4) NEGATIF EKLE. Kampanyayi acarken alakasiz varyasyonlari pesinen "
                f"negatif exact yap - ilk haftanin butcesini bu korur.",
                f"5) 14 GUN DOKUNMA. Amazon'un ogrenme fazi. Bid oynatirsan veri "
                f"kirlenir ve neyin ise yaradigini anlayamazsin.",
                f"6) GUN 14 KARAR: CTR < %0.3 ise ana gorsel/baslik sorunu (bid degil). "
                f"CVR dusukse fiyat/yorum sorunu. ACOS > %{be:.0f} (break-even) ise "
                f"bid'i %20 dusur. ACOS < %{tacos:.0f} ise bid +%20 ve butce artir.",
                f"7) KAZANANI BUYUT, kaybedeni durdur. 30 gunde 10+ tiklama alip 0 "
                f"siparis veren kelimeyi kapat.",
            ],
        }
    if bucket == "SCALE":
        return {
            "title": "Buyutme plani",
            "why": (f"{n} kelimede tiklama payin gosterim payindan buyuk. Yani "
                    f"listingin rakiplerden iyi calisiyor, sadece yeterince "
                    f"gorunmuyorsun. En dusuk riskli ciro artisi burada."),
            "steps": [
                "1) ONCE BUTCE KONTROL. Kampanya gun bitmeden butcesini tuketiyorsa "
                "sorun bid degil butcedir - once butceyi %30 artir, bid'e dokunma.",
                "2) BID'i kademeli artir: haftada max %20. Tek seferde 2 katina "
                "cikarmak CPC'yi zipllatir, ACOS patlar.",
                f"3) PLACEMENT: 'Top of search' oranini kontrol et. Donusum orani "
                f"yuksekse Top-of-search bid adjustment %25-50 ekle.",
                f"4) HEDEF: ACOS %{tacos:.0f} altinda kaldigi surece artirmaya devam. "
                f"%{be:.0f} break-even'i gecince dur.",
                "5) Bu kelimeleri ayri bir 'kazananlar' kampanyasina tasimak, "
                "butcenin dogru yere gitmesini garanti eder.",
            ],
        }
    if bucket == "LEAK":
        return {
            "title": "Kacak durdurma plani (reklam degil, listing isi)",
            "why": (f"{n} kelimede gosterim payin var ama satin alma payin cok dusuk. "
                    f"Para trafige gidiyor, satisa donmuyor. Bid artirmak bu "
                    f"kelimelerde zarari BUYUTUR."),
            "steps": [
                "1) FIYAT: Tablodaki 'Fiyat farki' sutununa bak. Pazardan belirgin "
                "pahaliysan once bunu coz - reklam fiyat sorununu kapatamaz.",
                "2) ANA GORSEL: Tiklama aliyorsun demek gorsel calisiyor; satis yoksa "
                "sorun detay sayfasinda. Galeri, A+ icerik, video ekle.",
                "3) YORUM: Bu kategoride rakiplerin yorum sayisina bak. Buyuk fark "
                "varsa CVR farkinin ana sebebi budur.",
                "4) BU ARADA bid'i dusur veya durdur. Listing duzelene kadar her "
                "tiklama zarar.",
                "5) Duzelttikten sonra 30 gun sonra tekrar olc.",
            ],
        }
    if bucket == "CONQUEST":
        return {
            "title": "Rakip marka plani",
            "why": (f"{n} rakip marka aramasi. Musteri o markayi ariyor - dusuk CVR "
                    f"normaldir. Bunu satis degil, marka bilinirligi yatirimi say."),
            "steps": [
                "1) KUCUK BUTCE. Gunluk $5-10 ile test et. Bu kova ciro degil "
                "gorunurluk icin.",
                "2) EXACT match. Broad acarsan rakip marka + alakasiz her sey gelir.",
                "3) ASIN HEDEFLEME DAHA IYI. Rakibin urun sayfasinda gorunmek, "
                "marka kelimesine reklam vermekten genelde daha ucuz ve donusumludur. "
                "Asagidaki sepet analizi bolumunde aday ASIN'ler var.",
                f"4) ACOS TOLERANSI yuksek tut. Burada %{be:.0f} break-even'i gecmek "
                f"ilk aylarda normal - ama 90 gunde donmuyorsa kapat.",
                "5) YASAL: reklam metninde rakip marka adi kullanma, karsilastirma "
                "iddiasi yapma.",
            ],
        }
    if bucket == "RETRY":
        return {
            "title": "Tekrar deneme plani (once teshis)",
            "why": (f"{n} kelimede pazarda payin yok AMA daha once reklam verip "
                    f"tutturamamissin. Ayni sekilde tekrar acmak ayni sonucu verir."),
            "steps": [
                "1) TESHIS: Tiklama geldi mi? Gelmediyse sorun bid/alaka. Geldi ama "
                "satis olmadiysa sorun listing/fiyat.",
                "2) Tabloda her kelimenin eski tiklama/harcama/ACOS'u yaziyor - "
                "hangisinin hangi sorun oldugunu oradan gor.",
                "3) SEBEBI DUZELTMEDEN ACMA. Ayni listing + ayni fiyat = ayni sonuc.",
                "4) Acacaksan onceki bid'in %70'i ile ve exact match ile ac.",
                "5) 21 gun ver, gene donmezse bu kelimeyi kalici negatif yap.",
            ],
        }
    if bucket == "DEFEND":
        return {
            "title": "Savunma plani",
            "why": (f"{n} kelimede lidersin. Buradaki isin ciro buyutmek degil, "
                    f"mevcut ciroyu kaptirmamak."),
            "steps": [
                "1) BUTCE KISMA. Bu kampanyalar gun icinde tukenmemeli.",
                "2) Top-of-search impression share'i haftalik izle. Dusuyorsa rakip "
                "bid artirmis demektir - karsilik ver.",
                "3) Kendi urun sayfalarinda kendi urununu hedefle (cross-sell) ki "
                "rakip senin sayfanda reklam veremesin.",
                f"4) ACOS burada %{tacos:.0f}'in uzerine cikabilir - liderligi korumak "
                f"uzun vadede daha degerli. Ama %{be:.0f} break-even'i surekli "
                f"gecmesine izin verme.",
            ],
        }
    return None


def action_plan(buckets, econ, period_days):
    """Kovalar arasi oncelikli 'once sunu yap' listesi."""
    def tot(k, f):
        return sum(i[f] for i in buckets.get(k, []))

    cand = []
    if buckets.get("SCALE"):
        cand.append({
            "rank": 1, "bucket": "SCALE", "effort": "Dusuk", "risk": "Dusuk",
            "title": "Once kazandigin kelimelerde bid/butce artir",
            "detail": (f"{len(buckets['SCALE'])} kelimede listingin zaten calisiyor, "
                       f"sadece gorunurlugun eksik. Yeni kampanya acmadan once burayi "
                       f"sikistir - en hizli ve en guvenli ciro artisi."),
        })
    if buckets.get("LEAK"):
        cand.append({
            "rank": 2, "bucket": "LEAK", "effort": "Orta", "risk": "—",
            "title": "Para kacagini durdur",
            "detail": (f"{len(buckets['LEAK'])} kelimede trafik alip satamiyorsun. "
                       f"Yeni kampanyaya butce koymadan once bu deligi kapat, yoksa "
                       f"yeni trafik de ayni yere akar."),
        })
    if buckets.get("WHITESPACE"):
        cand.append({
            "rank": 3, "bucket": "WHITESPACE", "effort": "Yuksek", "risk": "Orta",
            "title": "Yeni kampanyalari ac",
            "detail": (f"{len(buckets['WHITESPACE'])} bos kelime, tahmini "
                       f"${_n(tot('WHITESPACE','est_revenue'))} potansiyel. Urun "
                       f"filtresiyle tek urunden basla, ilk dalgada 20 kelime."),
        })
    if buckets.get("RETRY"):
        cand.append({
            "rank": 4, "bucket": "RETRY", "effort": "Orta", "risk": "Yuksek",
            "title": "Eski basarisizlari teshis et",
            "detail": (f"{len(buckets['RETRY'])} kelimede daha once para harcayip "
                       f"tutturamamissin. Sebebi cozmeden tekrar acma."),
        })
    if buckets.get("CONQUEST"):
        cand.append({
            "rank": 5, "bucket": "CONQUEST", "effort": "Dusuk", "risk": "Yuksek",
            "title": "Rakip marka testini en sona birak",
            "detail": (f"{len(buckets['CONQUEST'])} rakip marka aramasi. Kucuk butceli "
                       f"deney olarak dusun, ana ciro kaynagi degil."),
        })
    return cand


def negative_suggestions(rejected, hist, limit=60):
    """Hicbir urune uymayan terimlerden negatif keyword listesi uretir.

    Iki degeri var:
      1. ONLEYICI - phrase/broad kampanya acarsan bu terimler butceni yer.
         Kampanyayi acarken pesinen negatif eklemek ilk haftayi kurtarir.
      2. ACIL - reklam gecmisinde bu terime ZATEN para harcanmissa, bu su
         anda akan bir kanamadir. Alakasiz oldugu icin donmesi de beklenmez.
         Bunlari once goster; dogrudan tasarruf demektir.
    """
    out = []
    for r in rejected:
        term = _norm_term(r.get("query"))
        h = hist.get(term) if hist else None
        spent = (h or {}).get("spend") or 0
        sales = (h or {}).get("sales") or 0
        # Alakasiz gorunse de SATIS getirmisse negatif yapma - eslesme
        # heuristigi yanilmis olabilir, veri sozden ustundur.
        if sales > 0:
            continue
        out.append({
            "query": r.get("query"),
            "volume": r.get("volume"),
            "urgent": spent > 0,
            "wasted_spend": round(spent, 2),
            "wasted_clicks": (h or {}).get("clicks") or 0,
            "why": (f"Alakasiz ve zaten ${spent:.0f} harcanmis "
                    f"({(h or {}).get('clicks') or 0:.0f} tiklama, 0 satis) - hemen negatif yap"
                    if spent > 0 else
                    "Hicbir urununle eslesmiyor - phrase/broad acarsan butce yer"),
        })
    # Once para yakanlar, sonra hacme gore
    out.sort(key=lambda x: (-x["wasted_spend"], -(x["volume"] or 0)))
    # Israf toplami TUM listeden hesaplanir, gosterilen ilk N'den degil -
    # yoksa kullaniciya gercekte olandan az kayip bildiririz.
    total_waste = round(sum(x["wasted_spend"] for x in out), 2)
    urgent = sum(1 for x in out if x["urgent"])
    return out[:limit], {"total_waste": total_waste, "urgent_count": urgent,
                         "total_count": len(out)}


def _basket_targets(basket, catalog):
    """Sepet analizinden product targeting adaylari.

    Musteriler A ile B'yi birlikte aliyorsa, A'nin sayfasinda B'yi reklamla
    gostermek yuksek donusumlu bir hamledir.
    """
    own = {c.get("asin") for c in (catalog or [])}
    out = []
    for row in basket or []:
        for c in row.get("combos") or []:
            if (c.get("pct") or 0) < 5:
                continue
            out.append({
                "source_asin": row.get("asin"),
                "source_title": row.get("title"),
                "target_asin": c["asin"],
                "target_title": c["title"],
                "combination_pct": c["pct"],
                "is_own_product": c["asin"] in own,
                "play": ("Cross-sell: kendi urununu kendi sayfanda hedefle "
                         "(bundle/upsell)" if c["asin"] in own else
                         "Conquest: rakip ASIN'i hedefle"),
            })
    out.sort(key=lambda x: -x["combination_pct"])
    return out[:40]
