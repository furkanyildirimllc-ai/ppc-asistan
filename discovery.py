"""Kelime kesif motoru - surekli yeni kelime bulup test eder.

KAYNAKLAR (guvenilirlik sirasina gore)
  1. KENDI ARAMA TERIMI RAPORUN - hangi kelimenin DONUSTUGU yalnizca
     burada bellidir. Diger kaynaklar hacim gosterir, donusum gostermez.
  2. AMAZON AUTOCOMPLETE - Amazon'un kendi oneri motoru. Musterilerin
     gercekte yazdigi sorgular, arama hacmine gore sirali. Ucretsiz ve
     resmi uc.
  3. RAKIP LISTING'LERI - rakibin basligindaki kelimeler (uzanti ceker).
  4. TEMA GENISLETME - kendi kazanan temalarini autocomplete'e sokup
     komsu sorgulari bulmak.

TASARIM KARARI: bulunan kelime DOGRUDAN kampanyaya girmez.
Once puanlanir, elenir, mevcutlarla karsilastirilir. Ham liste dokmek
kullaniciyi bogar ve butceyi dagitir. Amac "cok kelime" degil,
"test etmeye deger kelime".
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import launch

AUTOCOMPLETE = "https://completion.amazon.com/api/2017/suggestions"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Autocomplete'e nazik davran: Amazon'un ucu resmi ama hiz siniri var.
ISTEK_ARASI_SN = 0.35
ZAMAN_ASIMI = 10

# Bu eklerle sorgu genisletilir - musterinin niyetini yakalar
GENISLETME_EKLERI = ["", " for ", " best ", " natural ", " organic ",
                     " men ", " women ", " kit ", " set "]

STOP = {"for", "the", "and", "with", "of", "to", "in", "a", "on", "my",
        "de", "para", "el", "la", "y", "que", "un", "una", "best"}

# GENEL kelimeler tek baslarina alaka KANITLAMAZ. "hair" gecen her sorgu
# sac urunu degildir: "hair clippers", "nose hair trimmer" gibi. Aday,
# urunun ne oldugunu belirten OZGUL bir kelime tasimalidir.
GENEL_KELIMELER = {"hair", "men", "mens", "women", "womens", "skin", "face",
                   "body", "natural", "organic", "kit", "set", "care",
                   "product", "products", "beauty", "cabello", "pelo"}

# Farkli URUN TIPI sinyalleri - bu kelimeler varsa aday baska bir urundur.
# Ayni kategoride gorunup alakasiz olan sorgulari eler.
FARKLI_URUN = {
    # alet / cihaz
    "clipper", "clippers", "trimmer", "trimmers", "razor", "shaver",
    "dryer", "straightener", "curler", "brush", "comb", "scissors",
    "machine", "device", "laser", "helmet", "cap", "roller", "derma",
    # farkli kategori
    "dye", "color", "colour", "bleach", "wig", "extension", "extensions",
    "gel", "wax", "pomade", "spray", "mousse", "perfume", "cologne",
    "supplement", "supplements", "vitamin", "vitamins", "pill", "pills",
    "gummies", "tablet", "diet", "food", "tea", "powder",
    "underwear", "shorts", "shoes", "socks", "shirt", "shirts", "wallet",
    "towel", "pillow", "book", "guide",
}


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def autocomplete(prefix, marketplace="ATVPDKIKX0DER", limit=11):
    """Amazon'un oneri motorundan sorgulari ceker.

    Hata durumunda BOS liste doner - kesif motoru bir kaynagin
    coktugu icin tamamen durmamali.
    """
    q = str(prefix or "").strip()
    if not q:
        return []
    url = AUTOCOMPLETE + "?" + urllib.parse.urlencode({
        "session-id": "000-0000000-0000000", "customer-id": "",
        "request-id": "X", "page-type": "Gateway", "lop": "en_US",
        "site-variant": "desktop", "client-info": "amazon-search-ui",
        "mid": marketplace, "alias": "aps", "b2b": "0", "fresh": "0",
        "ks": "71", "prefix": q, "event": "onKeyPress",
        "limit": str(limit), "fb": "1", "suggestion-type": "KEYWORD"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=ZAMAN_ASIMI) as r:
            d = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    out = []
    for s in d.get("suggestions") or []:
        v = str(s.get("value") or "").strip().lower()
        if v and v != q.lower():
            out.append(v)
    return out


def expand(seeds, max_queries=40, marketplace="ATVPDKIKX0DER"):
    """Cekirdek kelimeleri autocomplete ile genisletir.

    max_queries: kac istek atilacagi. Amazon'a nazik davranmak ve
    kullaniciyi bekletmemek icin sinirli tutulur.
    """
    gorulen, sonuc, sayac = set(), [], 0
    for seed in seeds or []:
        s = str(seed or "").strip().lower()
        if not s:
            continue
        for ek in GENISLETME_EKLERI:
            if sayac >= max_queries:
                return sonuc
            sorgu = (s + ek).strip()
            if sorgu in gorulen:
                continue
            gorulen.add(sorgu)
            for oneri in autocomplete(sorgu, marketplace):
                if oneri not in gorulen:
                    gorulen.add(oneri)
                    sonuc.append({"keyword": oneri, "source": "autocomplete",
                                  "seed": s})
            sayac += 1
            time.sleep(ISTEK_ARASI_SN)
    return sonuc


def _kelime_kumesi(metin):
    return {w for w in re.findall(r"[a-z0-9']+", str(metin or "").lower())
            if w not in STOP and len(w) > 2}


def seeds_from_winners(kazanan_terimler, kazanan_temalar,
                       kategori_kelimeleri=None, limit=8):
    """Cekirdek = KAVRAM OBEGI (2-4 kelime).

    Ne cok kisa ne cok uzun olmali:
      "mens"                              -> cok genel; autocomplete
                                             "mens underwear" dondurur
      "mens stem cell face cream for 40+"  -> cok dar; autocomplete
                                             genisletecek yer bulamaz
      "stem cell cream"                    -> DOGRU; komsu sorgulari acar

    Uretim: kazanan temalari kategori kelimeleriyle eslestir, ayrica
    kazanan sorgulardan 2-4 kelimelik olanlari al.
    """
    kategori = [str(w).lower() for w in (kategori_kelimeleri or [])]
    temalar = [t["theme"] for t in (kazanan_temalar or [])
               if str(t.get("theme")) not in STOP]
    out, gorulen = [], set()

    def ekle(x):
        x = " ".join(str(x).split()).strip().lower()
        if not x or x in gorulen or not (2 <= len(x.split()) <= 4):
            return
        # RAKIP MARKA CEKIRDEK OLMAZ. "strongville hair lotion" cekirdek
        # yapilirsa autocomplete o markanin urun agacini dondurur - senin
        # urununle ilgisi olmayan sorgular. Rakip marka reklamda HEDEF
        # olabilir ama kesif cekirdegi olamaz.
        if any(_looks_brand(w) for w in x.split()):
            return
        gorulen.add(x)
        out.append(x)

    # 1) Kazanan sorgulardan dogal kavram obekleri
    for t in (kazanan_terimler or []):
        kw = str(t.get("term") or "").strip().lower()
        if 2 <= len(kw.split()) <= 4:
            ekle(kw)
        elif len(kw.split()) > 4:
            # uzun sorgunun kategori kelimesi iceren 3'lu penceresi
            p = kw.split()
            for i in range(len(p) - 2):
                pencere = p[i:i + 3]
                if any(w in kategori for w in pencere):
                    ekle(" ".join(pencere))
                    break
        if len(out) >= limit:
            return out[:limit]

    # 2) Tema x kategori eslesmeleri - kavram tasiyan kisa obekler
    for tema in temalar[:6]:
        if tema in kategori:
            continue
        for k in kategori[:4]:
            ekle(f"{tema} {k}")
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


def score(adaylar, kazanan_temalar, mevcut_kelimeler, negatifler=None,
          urun_basligi="", kategori_kelimeleri=None, min_relevance=0.34):
    """Adaylari puanla ve ele.

    Puan bilesenleri:
      + kazanan temayla ortusme  (bu marka o temada SATIS yapmis)
      + urun basligiyla ortusme  (alaka)
      - zaten hedefliyorsan      (tekrar)
      - negatif listendeyse      (bilerek disladin)
      - rakip marka ise          (reklamda mesru ama ayri isaretlenir)
    """
    tema_agirlik = {t["theme"]: _f(t.get("roas")) for t in (kazanan_temalar or [])}
    mevcut = {str(k).strip().lower() for k in (mevcut_kelimeler or [])}
    neg = {str(k).strip().lower() for k in (negatifler or [])}
    baslik_kelimeleri = _kelime_kumesi(urun_basligi)
    # Kategori kelimeleri: urunun NE OLDUGUNU tanimlar (serum, sampuan,
    # krem...). Aday bunlardan en az birini tasimazsa alakasizdir.
    kategori = {str(w).lower() for w in (kategori_kelimeleri or [])}
    if not kategori:
        kategori = baslik_kelimeleri
    elenen_alakasiz = 0
    atlanan_mevcut = 0

    out = []
    for a in adaylar or []:
        kw = str(a.get("keyword") or "").strip().lower()
        temiz, sebep = launch.sanitize_keyword(kw)
        if not temiz:
            continue
        if temiz in mevcut:
            atlanan_mevcut += 1
            continue                      # zaten hedefliyorsun
        if temiz in neg:
            continue                      # bilerek dislamissin
        kelimeler = _kelime_kumesi(temiz)
        if not kelimeler:
            continue

        tema_puan = sum(tema_agirlik.get(w, 0) for w in kelimeler)
        alaka = (len(kelimeler & baslik_kelimeleri) / len(kelimeler)
                 if baslik_kelimeleri else 0)

        # ALAKA BIR KAPIDIR, PUAN BILESENI DEGIL.
        # "mens" temasi 33x ROAS diye "mens underwear" onerilmez.
        #
        # 1) Farkli urun tipi sinyali varsa dogrudan elenir.
        if kelimeler & FARKLI_URUN:
            elenen_alakasiz += 1
            continue
        # 2) Aday, kategoriden OZGUL bir kelime tasimali. Genel kelime
        #    ("hair", "men") tek basina yetmez - "hair clippers" da
        #    "hair" tasir ama sac bakim urunu degildir.
        ozgul_kategori = kategori - GENEL_KELIMELER
        if ozgul_kategori and not (kelimeler & ozgul_kategori):
            elenen_alakasiz += 1
            continue
        if alaka < min_relevance and baslik_kelimeleri:
            elenen_alakasiz += 1
            continue

        rakip = any(_looks_brand(w) for w in kelimeler)
        # CARPIMSAL: alakasiz aday yuksek tema puaniyla kurtulamaz.
        puan = (1.0 + tema_puan) * (0.2 + alaka)
        if rakip:
            puan *= 0.8       # degerli olabilir ama listeye giremez

        out.append({
            "keyword": temiz, "source": a.get("source"), "seed": a.get("seed"),
            "score": round(puan, 2),
            "theme_overlap": round(tema_puan, 2),
            "title_relevance": round(alaka, 2),
            "competitor_brand": rakip,
            "words": len(kelimeler),
        })
    out.sort(key=lambda x: -x["score"])
    # Sayac liste BOS olsa da kaybolmamali - "0 aday, 0 elendi" yaniltir.
    score.last_filtered = elenen_alakasiz
    score.last_skipped_existing = atlanan_mevcut
    return out


def _looks_brand(w):
    try:
        import listing
        return listing.looks_like_brand(w)
    except Exception:
        return False


def suggest_tests(scored, bid, max_new=25, min_score=0.0):
    """Test edilecek kelimeleri sec ve teklif ata.

    Yeni kelimenin gecmisi YOKTUR - CVR bilinmez. Bu yuzden teklif
    kanitlanmis kelimeninki gibi hesaplanmaz; olculmus pazar CPC'sinin
    bir miktar ALTINDA baslanir ve veri geldikce ayarlanir.
    Amac satis degil OLCUM: kelimenin donusup donusmedigini ogrenmek.
    """
    secili = [s for s in (scored or []) if s["score"] >= min_score][:max_new]
    test_bid = round(max(_f(bid) * 0.85, 0.20), 2)
    for s in secili:
        s["test_bid"] = test_bid
        s["note"] = ("yeni kelime - geçmişi yok, ölçüm için pazar CPC'sinin "
                     "%15 altında başlatılır")
    return secili
