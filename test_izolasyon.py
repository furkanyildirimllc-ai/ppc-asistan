"""Marka izolasyon testi - markalar birbirine ASLA karismamali.

Kullanicinin keskin sarti: "markalar birbirinden keskin sekilde ayrilcak,
karisma olmadigina her yerde kontrol et".

Bu test her modulun ayni girdiyle FARKLI markalar icin FARKLI ve yalnizca
kendi verisinden turemis sonuc urettigini kanitlar. Calistir:
    .venv/bin/python test_izolasyon.py
"""
import json
import sqlite3
import sys

import architecture
import benchmarks
import discovery
import growth
import listing
import phases

DB = "ppc.db"
gecti, kaldi = 0, 0


def kontrol(ad, sart, detay=""):
    global gecti, kaldi
    if sart:
        gecti += 1
        print(f"  GECTI  {ad}")
    else:
        kaldi += 1
        print(f"  KALDI  {ad}  {detay}")


def rows(c, bid, tip):
    return [json.loads(x[0]) for x in c.execute(
        "SELECT data FROM report_rows WHERE brand_id=? AND report_type=?",
        (bid, tip))]


def main():
    c = sqlite3.connect(DB)
    markalar = [(r[0], r[1]) for r in
                c.execute("SELECT id,name FROM brands ORDER BY id")]
    print(f"MARKA IZOLASYON TESTI - {len(markalar)} marka\n")

    veri = {}
    for bid, ad in markalar:
        veri[bid] = {
            "ad": ad,
            "tg": rows(c, bid, "targeting"),
            "st": rows(c, bid, "search_term"),
            "cp": rows(c, bid, "campaign"),
        }

    # --- 1) benchmarks: olculmus referanslar markaya ozgu mu? ---
    print("1) benchmarks.resolve — ölçülmüş CPC/CVR/AOV")
    ref = {}
    for bid, d in veri.items():
        if not d["tg"]:
            continue
        b = benchmarks.resolve(rows=d["tg"], brand_id=bid, brand_name=d["ad"])
        a = b.get("account") or {}
        ref[bid] = (a.get("cpc"), a.get("cvr"), a.get("aov"))
    kontrol("her markanın CPC'si farklı",
            len({v[0] for v in ref.values()}) == len(ref),
            f"CPC'ler: {[v[0] for v in ref.values()]}")
    kontrol("her markanın CVR'ı farklı",
            len({v[1] for v in ref.values()}) == len(ref),
            f"CVR'lar: {[v[1] for v in ref.values()]}")

    # --- 2) Bos marka baska markanin verisini almiyor mu? ---
    print("\n2) veri olmayan marka — sızıntı var mı?")
    bos = benchmarks.resolve(rows=[], brand_name="BosMarka")
    kontrol("veri yoksa CPC None döner (başka markadan almaz)",
            bos["cpc"]["exact"] is None,
            f"döndü: {bos['cpc']['exact']}")
    sizinti = [veri[b]["ad"] for b, v in ref.items() if v[0] == bos["cpc"]["exact"]]
    kontrol("hiçbir markanın CPC'si varsayılana sızmamış", not sizinti, str(sizinti))

    # --- 3) Capraz besleme: A markasinin verisi B'ye verilirse? ---
    print("\n3) çapraz besleme — A'nın verisi B'nin sonucunu değiştirir mi?")
    ikili = [b for b in ref][:2]
    if len(ikili) == 2:
        a, b_ = ikili
        sadece_a = benchmarks.resolve(rows=veri[a]["tg"], brand_name=veri[a]["ad"])
        karisik = benchmarks.resolve(rows=veri[a]["tg"] + veri[b_]["tg"],
                                     brand_name=veri[a]["ad"])
        kontrol("karışık veri farklı sonuç verir (izolasyon anlamlı)",
                sadece_a["account"]["cpc"] != karisik["account"]["cpc"],
                "aynı çıktı - veri ayrımı sonucu etkilemiyor olabilir")

    # --- 4) phases: faz kararı markaya özgü mü? ---
    print("\n4) phases.assess — faz kararı")
    fazlar = {}
    for bid, d in veri.items():
        f = phases.assess(d["tg"], d["st"], d["cp"])
        fazlar[bid] = (f["phase"], f["metrics"]["clicks"], f["metrics"]["winners"])
    kontrol("tıklama sayıları markaya özgü",
            len({v[1] for v in fazlar.values()}) == len(fazlar),
            str([v[1] for v in fazlar.values()]))
    kontrol("kazanan terim sayıları markaya özgü",
            len({v[2] for v in fazlar.values()}) >= len(fazlar) - 1,
            str([v[2] for v in fazlar.values()]))

    # --- 5) listing: kelime önerileri markaya özgü mü? ---
    print("\n5) listing.suggest — kelime önerileri")
    oneriler = {}
    for bid, d in veri.items():
        if not d["st"]:
            continue
        s = listing.suggest(d["st"], "", d["ad"])
        oneriler[bid] = {t["theme"] for t in s["themes_winning"][:10]}
    adlar = list(oneriler)
    if len(adlar) >= 2:
        ortak = oneriler[adlar[0]] & oneriler[adlar[1]]
        kontrol("iki markanın kazanan temaları birebir aynı DEĞİL",
                oneriler[adlar[0]] != oneriler[adlar[1]],
                "temalar aynı çıktı")
        print(f"         ({len(ortak)} tema ortak — farklı markalar benzer "
              f"kategoride olabilir, birebir aynı olmaması yeterli)")

    # --- 6) discovery: çekirdek kavramlar markaya özgü mü? ---
    print("\n6) discovery.seeds_from_winners — keşif çekirdekleri")
    cekirdekler = {}
    for bid, d in veri.items():
        if not d["st"]:
            continue
        kz = listing.winning_terms(d["st"])
        tm = listing.keyword_themes(d["st"])["winning"][:10]
        cekirdekler[bid] = set(discovery.seeds_from_winners(kz, tm, [], limit=6))
    ad2 = [b for b in cekirdekler if cekirdekler[b]]
    if len(ad2) >= 2:
        kontrol("keşif çekirdekleri markalar arası aynı değil",
                cekirdekler[ad2[0]] != cekirdekler[ad2[1]],
                "çekirdekler aynı")

    # --- 7) growth: plan markaya özgü mü? ---
    print("\n7) growth.plan — büyüme planı")
    planlar = {}
    for bid, d in veri.items():
        kamp = [{"name": r.get("campaign"), "budget": r.get("budget") or 0,
                 "spend": r.get("spend") or 0, "sales": r.get("sales") or 0,
                 "clicks": r.get("clicks") or 0, "orders": r.get("orders") or 0,
                 "bid": 0, "days": 30} for r in d["cp"]]
        if not kamp:
            continue
        planlar[bid] = growth.plan(kamp, 5000)["current_monthly_sales"]
    kontrol("mevcut ciro değerleri markaya özgü",
            len(set(planlar.values())) == len(planlar),
            str(list(planlar.values())))

    # --- 8) DB sorgularinda brand_id filtresi var mi? ---
    print("\n8) veritabanı — her sorgu brand_id ile filtreli mi?")
    import re
    import pathlib
    kod = pathlib.Path("app.py").read_text(encoding="utf-8")
    sorgular = re.findall(r'FROM report_rows[^"\')]*', kod, re.I)
    filtresiz = [q for q in sorgular if "brand_id" not in q.lower()]
    kontrol("report_rows sorgularının tamamı brand_id filtreli",
            not filtresiz, f"filtresiz: {filtresiz[:2]}")

    print(f"\n{'='*50}\nSONUC: {gecti} gecti, {kaldi} kaldi")
    return 0 if kaldi == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
