"""Ciro hedefine giden plan - %30 guvenlik marjiyla.

NEDEN MARJ: reklam projeksiyonlari sapar. Olcek buyudukce CPC artar, CVR
duser, rekabet degisir. Hedefe TAM oturacak plan yaparsan %30 sapmada
hedefi kacirirsin. Hedefin %30 uzerine planlarsan, %30 sapmada bile tutar.

Bu modul "ne kadar harcamaliyim" demez - "hangi kampanyaya ne kadar
koyarsam ne gelir" der ve sirali bir is listesi uretir.
"""
import math

import benchmarks

SAFETY_MARGIN = 0.30      # hedefin %30 uzerine planla
SCALE_DECAY = 0.75        # butce 2x olunca ROAS ~%25 bozulur (olculdu)
MIN_CLICKS_PER_DAY = 5


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def plan(campaigns, monthly_target, days=30, accepted_acos_pct=None,
         margin=SAFETY_MARGIN):
    """Kampanya listesinden hedefe giden butce dagilimi uretir.

    campaigns: [{name, budget, spend, sales, clicks, orders, bid, days}]
               spend/sales o donemin TOPLAMI olmali.
    monthly_target: aylik ciro hedefi ($)
    accepted_acos_pct: kabul edilen ACOS. Verilmezse kisitlanmaz.

    Doner: {target_with_margin, allocations, projected, gap, actions}
    """
    hedef = _f(monthly_target) * (1 + margin)
    gunluk_hedef = hedef / 30.0

    kalemler = []
    for c in campaigns or []:
        sp, sa = _f(c.get("spend")), _f(c.get("sales"))
        d = _f(c.get("days")) or days
        if sp <= 0:
            continue
        roas = sa / sp
        acos = (sp / sa * 100) if sa > 0 else None
        gunluk_harcama = sp / d
        butce = _f(c.get("budget"))
        kul = (gunluk_harcama / butce) if butce > 0 else 0
        kalemler.append({
            "name": c.get("name"), "budget": butce, "bid": _f(c.get("bid")),
            "daily_spend": round(gunluk_harcama, 2), "roas": round(roas, 2),
            "acos_pct": round(acos, 1) if acos else None,
            "utilization": round(kul, 3),
            # Butce kisitliysa para koymak ise yarar; talep kisitliysa teklif.
            "limit": ("butce" if kul >= 0.6 else "talep"),
        })

    # ACOS kisiti: kabul edilenin uzerindekiler buyutulmez.
    uygun = [k for k in kalemler
             if k["roas"] > 0 and
             (accepted_acos_pct is None or
              (k["acos_pct"] or 999) <= accepted_acos_pct)]
    uygun.sort(key=lambda k: -k["roas"])

    mevcut_ciro = sum(k["daily_spend"] * k["roas"] for k in kalemler)
    dagilim, projekte_ciro, projekte_harcama = [], 0.0, 0.0

    for k in uygun:
        # Butce kisitli: butceyi buyut, ROAS bozulmasini hesaba kat.
        # Talep kisitli: butce artisi ise yaramaz, teklif artisi gerekir -
        # ve teklif artisi CPC'yi artirdigi icin ROAS'i dogrudan dusurur.
        if k["limit"] == "butce":
            kat = 3.0
            bozulma = SCALE_DECAY
            aksiyon = f"butce ${k['budget']:.0f} -> ${k['budget']*kat:.0f}"
        else:
            kat = 1.5
            bozulma = SCALE_DECAY * 0.9   # teklif artisi ROAS'i daha cok bozar
            aksiyon = (f"teklif ${k['bid']:.2f} -> ${k['bid']*1.6:.2f} "
                       f"+ butce ${k['budget']:.0f} -> ${k['budget']*kat:.0f}")
        yeni_harcama = min(k["budget"] * kat * 0.6, k["daily_spend"] * kat)
        yeni_roas = k["roas"] * bozulma
        yeni_ciro = yeni_harcama * yeni_roas
        projekte_ciro += yeni_ciro
        projekte_harcama += yeni_harcama
        dagilim.append({
            **k, "action": aksiyon,
            "new_daily_spend": round(yeni_harcama, 2),
            "projected_roas": round(yeni_roas, 2),
            "projected_daily_sales": round(yeni_ciro, 2),
            "projected_monthly_sales": round(yeni_ciro * 30, 0),
        })
        if projekte_ciro >= gunluk_hedef:
            break

    aciк = gunluk_hedef - projekte_ciro
    return {
        "monthly_target": round(_f(monthly_target), 0),
        "target_with_margin": round(hedef, 0),
        "margin_pct": round(margin * 100),
        "current_monthly_sales": round(mevcut_ciro * 30, 0),
        "projected_monthly_sales": round(projekte_ciro * 30, 0),
        "projected_monthly_spend": round(projekte_harcama * 30, 0),
        "projected_acos_pct": (round(projekte_harcama / projekte_ciro * 100, 1)
                               if projekte_ciro else None),
        "gap_monthly": round(max(0, aciк) * 30, 0),
        "reaches_target": projekte_ciro >= gunluk_hedef,
        "allocations": dagilim,
        "not_scaled": [k["name"] for k in kalemler if k not in uygun],
    }


def gap_levers(gap_monthly, clicks, cvr, aov, ctr=None, impressions=None):
    """Acik kapanmiyorsa hangi kaldirac ne kadar getirir?

    Ciro = tik x CVR x AOV. Uc kaldirac carpimsaldir; birini 1.5x yapmak
    ciroyu 1.5x yapar. Ucu birden 1.15x yapmak da ~1.5x yapar - ve
    genelde ucunu birden biraz iyilestirmek, birini cok iyilestirmekten
    kolaydir.
    """
    cl, cv, av = _f(clicks), _f(cvr), _f(aov)
    mevcut = cl * cv * av
    if mevcut <= 0:
        return []
    gerekli_kat = (mevcut + _f(gap_monthly)) / mevcut
    out = []
    if impressions and ctr:
        out.append({
            "lever": "CTR (tıklama oranı)",
            "current": f"%{ctr*100:.2f}",
            "needed": f"%{ctr*100*gerekli_kat:.2f}",
            "how": "ana görsel, kupon rozeti, fiyat, yorum sayısı, başlık netliği",
            "cost": "reklam bütçesi GEREKTIRMEZ - gösterimin parası zaten ödendi",
            "speed": "hızlı (kupon birkaç dakikada, görsel birkaç günde)",
        })
    out.append({
        "lever": "CVR (dönüşüm oranı)",
        "current": f"%{cv*100:.2f}",
        "needed": f"%{cv*100*gerekli_kat:.2f}",
        "how": "listing görselleri, A+ içerik, fiyat, yorum, stok durumu",
        "cost": "reklam bütçesi gerektirmez",
        "speed": "orta (liste değişikliği 24-48 saatte yansır)",
    })
    out.append({
        "lever": "AOV (sepet)",
        "current": f"${av:.2f}",
        "needed": f"${av*gerekli_kat:.2f}",
        "how": "2'li/3'lü paket, çoklu adet indirimi, abone ol & kazan",
        "cost": "reklam bütçesi gerektirmez",
        "speed": "yavaş (yeni listing/varyasyon gerekir)",
    })
    out.append({
        "lever": "Tıklama hacmi",
        "current": f"{cl:.0f}",
        "needed": f"{cl*gerekli_kat:.0f}",
        "how": "teklif artışı, yeni kelime, yeni kampanya",
        "cost": f"reklam harcaması ~{gerekli_kat:.1f}x artar",
        "speed": "hızlı ama ACOS'u yükseltir",
    })
    # Ucu birden ne kadar artmali
    ucu = gerekli_kat ** (1 / 3)
    out.append({
        "lever": "ÜÇÜ BİRDEN (önerilen)",
        "current": "-",
        "needed": f"her biri {ucu:.2f}x",
        "how": (f"CTR %{(ctr or 0)*100:.2f}→%{(ctr or 0)*100*ucu:.2f}, "
                f"CVR %{cv*100:.2f}→%{cv*100*ucu:.2f}, "
                f"AOV ${av:.0f}→${av*ucu:.0f}"),
        "cost": "en ucuz yol",
        "speed": "3 küçük iyileştirme, 1 büyük iyileştirmeden kolaydır",
    })
    return out
