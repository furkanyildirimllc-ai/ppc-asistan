"""Karar politikasi - ARACIN DEGER SIRALAMASI.

Bu dosya "nasil hesaplanir" degil, "neyi tercih ederiz" sorusunu cevaplar.
Hesaplama kurallari benchmarks.py'de; oncelik sirasi burada.

=======================================================================
KESKIN KURAL: CIRO BIRINCI ONCELIKTIR
=======================================================================
Kullanicinin acik talimati: "zaman zaman karsizligi bile kabul ediyorum
ama ciro bizim birinci onceligimiz".

Bu sunlari DEGISTIRIR:
  - Ciro ureten bir kampanya, ACOS yuksek diye KAPATILMAZ. Teklifi
    ayarlanir, hacmi korunur.
  - Kapatma yalnizca ciro URETMEYEN icin gecerlidir (yeterli veriyle).
  - Iki secenek arasinda kalindiginda daha COK CIRO getiren secilir,
    daha karli olan degil.
  - Butce daraltmak son caredir; once teklif ayarlanir - butce daraltmak
    ciroyu dogrudan keser.

Bunun SINIRI da nettir (aksi halde para yakan bir arac olur):
  - Yapisal zarar kabul edilmez: teklif, tiklama basina ciroyu (AOV x CVR)
    kabul edilen ACOS tavanini asamaz. Cunku o noktada harcanan her dolar
    ciroyu buyutmez, sadece zarari buyutur.
  - Ciro uretmeyen harcama korunmaz. "Ciro onceligi" = ciroyu koru
    demektir, israfi koru demek degil.
"""

# Ciro ureten bir kampanyayi kapatmak yerine teklifini dusurmeyi tercih et.
REVENUE_FIRST = True

# Ciro ureten kampanya ancak bu kadar kotuyse kapatilir. Altindaysa
# teklif ayarlanir, kampanya YASAR. (kabul edilen ACOS'un kati)
CLOSE_ONLY_ABOVE_ACOS_MULTIPLE = 4.0

# Teklif tek seferde en fazla bu kadar dusurulur. Sert kesinti ciroyu
# aniden ucurur ve olcum bozulur.
MAX_BID_CUT = 0.50

# Ciro ureten kampanyanin butcesi ASLA dusurulmez - butce daraltmak
# ciroyu dogrudan keser. Butce yalnizca ciro uretmeyende kisilir.
NEVER_CUT_BUDGET_IF_SELLING = True


def should_close(sales, spend, clicks, accepted_acos_pct, zero_order_conf=None):
    """Bu kampanya/hedef kapatilmali mi?

    Doner: (kapat_mi, sebep)

    CIRO ONCELIGI burada uygulanir: satis varsa kapatma esigi cok yuksektir.
    """
    sa, sp, cl = float(sales or 0), float(spend or 0), float(clicks or 0)

    if sa > 0:
        acos = sp / sa * 100
        sinir = (accepted_acos_pct or 100) * CLOSE_ONLY_ABOVE_ACOS_MULTIPLE
        if acos > sinir:
            return True, (f"ACOS %{acos:.0f}, kabul edilenin {CLOSE_ONLY_ABOVE_ACOS_MULTIPLE:.0f} "
                          f"katından fazla (%{sinir:.0f}) - teklif düşürmek kurtarmaz")
        return False, (f"CİRO ÜRETİYOR (${sa:.0f}) - kapatılmaz, teklifi ayarlanır. "
                       f"Ciro birinci önceliktir.")

    # Satis yok: kapatma karari istatistige dayanir
    if zero_order_conf is not None and zero_order_conf >= 0.80:
        return True, (f"{cl:.0f} tık / 0 sipariş, ${sp:.0f} harcandı "
                      f"(istatistiksel güven %{zero_order_conf*100:.0f})")
    return False, (f"{cl:.0f} tık / 0 sipariş ama karar için veri yetersiz - "
                   f"erken kapatmak potansiyel ciroyu öldürür")


def budget_direction(sales, utilization, accepted_acos_pct, acos_pct):
    """Butce artmali mi, sabit mi, azalmali mi?

    CIRO ONCELIGI: satis varsa butce ASLA azaltilmaz.
    """
    sa = float(sales or 0)
    kul = float(utilization or 0)
    if sa > 0:
        if kul >= 0.6:
            return "artir", ("bütçe tıkıyor ve ciro üretiyor - para koymak "
                             "doğrudan ciro getirir")
        return "sabit", ("ciro üretiyor ama bütçe tıkamıyor - sorun bütçe "
                         "değil talep; teklif ayarlanmalı")
    if NEVER_CUT_BUDGET_IF_SELLING and sa > 0:
        return "sabit", "ciro üreten kampanyada bütçe kısılmaz"
    return "azalt", "ciro üretmiyor - bütçe israfı"


def pick(secenekler):
    """Iki plan arasinda secim: DAHA COK CIRO getiren kazanir.

    secenekler: [{"name":..., "revenue":..., "profit":...}, ...]
    Karlilik esitlik bozucudur, birincil olcut DEGILDIR.
    """
    if not secenekler:
        return None
    return sorted(secenekler,
                  key=lambda s: (-float(s.get("revenue") or 0),
                                 -float(s.get("profit") or 0)))[0]
