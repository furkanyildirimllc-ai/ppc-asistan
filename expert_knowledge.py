"""Amazon PPC Uzman Bilgi Bankasi.

Tum AI cagrilarina (strateji, chat, denetci) enjekte edilen ust duzey taktikler.
Sadece profesyonel Amazon PPC uzmanlarinin kullandigi yaklasimlar.

Kaynaklar: Canopy Management, Ad Badger, SellerMetrics, JumpFly, Perpetua,
Amazon Ads dokumantasyonu, sektor best practice'leri (2025-2026).
"""

EXPERT_KNOWLEDGE = """
# AMAZON PPC UZMAN BILGI - PRO SEVIYE TAKTIKLER

## 1. MATCH TYPE FUNNEL (Kesif -> Kesinlestir -> Buyut)
Profesyonel yapi:
- BROAD kampanya: KESIF. Dusuk bid (hedef CPC'nin %60-70'i). Amazon genisletme yapar.
  Yogun negative harvest gerekir - agresif negatifle.
- PHRASE kampanya: KALIFIYE. Orta bid (hedef CPC'nin %80-90'i). Broad'dan siparis
  getiren termleri buraya cek.
- EXACT kampanya: KAZANANLAR. Yuksek bid + placement multiplier. Sadece kanitlanmis
  termler. Buraya girdikten sonra bid'i agresif optimize et.

TRAFFIC SCULPTING (kritik): Bir term exact'e tasindiginda kaynak kampanyada MUTLAKA
negative exact ekle. Yoksa iki kampanya birbirine karsi acik artirmaya girer.
Buna "traffic sculpting" denir - Amazon algoritmasi ayni terimin en yuksek bidli
kampanyaya trafik verir, bu senin kontrol katmanini bozar.

Sonuc: Bu funnel tek basina %23 ACOS dususu saglar (satis hacmi ayni kalirken).

## 2. PLACEMENT MULTIPLIER OPTIMIZASYONU (cok az kullanicinin bildigi)
Top of Search (TOS) placement'i genelde %30-70 daha pahali AMA HER ZAMAN 30-70 daha
iyi cevrilmez. Kural:
- TOS conversion rate / Product Pages CR orani X ise -> TOS carpani = (X-1) * 100%
- Ornek: TOS %8 CR, product pages %4 CR -> +%100 carpan mantikli.
- TOS impression share <%40 + satis geliyor -> carpan artir.
- TOS ACOS hedefin %70'inin altinda + siparis var -> agresif carpan +%50.

BID STACKING: Base bid × Dynamic bidding (max +%100) × Placement multiplier (max +%900).
Ornek: $0.80 bid × Up&Down (Amazon +%50) × TOS +%75 = $2.10 efektif bid guclu
auction'larda. Bunu bilmeden "bid'i neden bu kadar yuksek odedim" derken sasirirsin.

## 3. BID STRATEJI SECIMI (Fixed / Down Only / Up&Down)
- YENI URUN veya ranking icin bidding: Up & Down. Amazon ogrenmeye zaman ayirsin.
- OLGUN ACOS problemli: Down Only. Riski minimize et.
- KAZANAN KANITLANMIS exact kampanya: Fixed + placement multiplier. Manuel kontrol.
- Kesinlikle YAPMA: Yeni kampanya + Up&Down + agresif bid = butce anlik erir.

## 4. NEGATIVE STRATEJISI (basit degil)
Cesitler:
- Negative Exact: sadece o kesin ibareyi bloke eder. GUVENLI, cok kullan.
- Negative Phrase: o ibareyi iceren TUM sorgulari bloke eder. TEHLIKELI, sadece
  kesin alakasiz kok kelimelerde kullan (ornek: "erkek", "cocuk").
- Negative Product Targeting (ASIN): rakip ASIN'de reklamini durdurma icin.
  Auto kampanyada rakip zayif ASIN'i negatifle - kendi PT kampanyanla oraya
  agresif bid at, boylece iki kez odeme yapmazsin.
- NEGATIVE KENDI ASIN'INE: Auto kampanyada KENDI ASIN'INI negative product yap -
  yoksa kendi urununu kendine reklam edip kendi kanibalizmini besliyorsun.

Amazon guvenlik: yeni kampanyada baslangictan proaktif negative koy:
- Alakasiz: free, cheap, used, second hand, wholesale, bulk
- Premium urunde: budget, economy, ucuz, cheap
- Fiyat segmenti: farkli model/versiyon numaralari
- Yanlis niyet: dropshipping, supplier, manufacturer (B2B trafik)

## 5. BRAND DEFENSE (cogu satici atlar - buyuk kacinilan alan)
- Kendi ASIN'ini kendi ASIN'inle target et: SP + SD ile kendi urun sayfanda kendi
  ilanini goster. Rakip senin sayfanda reklam yapamasin.
- Kardes ASIN cross-sell: A urununun sayfasinda B urununu goster (ayni brand).
  Bu Amazon'un "bought together" onerileriyle rekabet eder.
- Marka kelimesini exact match'te sat: "brandname product" gibi. Rakip senin marka
  aramalarindan calamasin.
- Sponsored Display Product Targeting: kendi ASIN'ine SD product targeting reklami
  ekle - detay sayfasinin ustunde ve altinda gorunur. CVR cok yuksek, CPC dusuk
  cunku az kullanilir.

## 6. SPONSORED DISPLAY (SD) - Az kullanilan altin madeni
- Views Remarketing: urununu goren ama almayan kullaniciya 30-90 gun sonra
  tekrar goster. CVR SP'den yuksek, CPC daha dusuk.
- Purchase Remarketing: satan mustericiye komplementer urun goster.
- Product Targeting: rakip zayif urunlerini hedefle (dusuk yildiz, yuksek fiyat,
  stok sikintisi). SD'nin CPC'si SP'den ~%40 daha ucuz.
- Category Targeting: kategori-ustu genis hedefleme, brand awareness.

## 7. DAYPARTING (Amazon nativde vermez - pro'lar API/script kullanir)
Peak conversion pencereleri (kategoriye gore degisir ama ortalama):
- 09:00-12:00 (sabah alisveris)
- 19:00-23:00 (aksam alisveris)
Dusuk CVR pencereleri:
- 02:00-08:00 (gece/erken sabah)
Uygulama: dusuk CVR saatlerinde harcamayi kes veya butce carpanini dusur.
Tek basina %7-12 ACOS dususu saglar. Amazon dashboard'unda "Time of Day" raporunda
saatlik CVR'yi gor.

## 8. RANKING JUICE & ORGANIK HALO
Yeni urun icin ilk 14-30 gun agresif PPC = organik ranking pompalar.
- Yuksek CVR + yuksek satis hizi = Amazon algoritma bunu "populer" gorur.
- Long-tail exact kelimede tekrar tekrar donusum = o kelimede organik zirveye
  hizli cikilir.
- Yeni urun ilk 30 gunde hedef ACOS %30-50 kabul edilebilir (ranking icin
  yatirim). Olgun urunde %15-25 hedefle.

Ranking dususu tespit edildiyse (organik siralamada 5+ pozisyon dusme):
- O ana kelimede PPC bid'i gecici artir (defansif)
- Dus durunca kademeli normal seviyeye don

## 9. KAMPANYA YASI VE OGRENME DONEMI
- Yeni kampanya ilk 14 gun: OGRENME DONEMI. Bu surede degisiklik yapma.
  Amazon algoritmasi yeni bid'i "ogrenirken" gecici performans dusuklugu
  yasanir.
- 14-30 gun: veri toplama, kucuk degisiklikler (bid ±%10).
- 30+ gun: tam optimizasyon. Buyuk degisiklikler (bid ±%25 max tek seferde) ok.

BID CHANGE CAP: Bir seferde %25'ten fazla bid degistirme. Sertlik algoritmayi
konfuze eder - "arastirma" moduna gecer, performans dusuklugu 3-7 gun surer.

## 10. IMPRESSION SHARE (IS) SINYALLERI
Search Term Impression Share raporundan:
- TOS IS <%30 + siparis geliyor: BID ARTIR. Para birakiyorsun.
- TOS IS %30-60 + hedef ACOS altinda: kucuk artis (+%15) test et.
- TOS IS %60-80 + hedef ACOS icinde: KORU. Artirma.
- TOS IS >%80: doygunluk. Artirma - marjinal donus kotudur.

Rest of Search IS >TOS IS 3+ kat + dusuk CVR: rakipler TOS'ta seni yenmis. Yeni
strateji: farkli kelime + placement multiplier.

## 11. SKAG (Single Keyword Ad Group)
Bir ad group icinde tek exact kelime = maximum bid kontrolu. Ne zaman kullan:
- Yuksek hacimli kazanan exact kelimeler.
- Rakip ile agresif rekabet edilen ana keyword.
- Sezonluk trend kelime (kisa vadeli hakimiyet).
Downside: cok fazla kampanya/adgroup = yonetim yuku. AI/otomasyon yoksa
5-10 SKAG'la sinirla.

## 12. CAMPAIGN STRUCTURE (ideal marka mimarisi)
Bir marka icin baslangic yapisi (SP):
1. Auto - Kesif (dusuk bid, tum eslesmeler acik, negative harvest sart)
2. Auto - Close Match (yuksek bid, sadece close match)
3. Broad - Kesif (long tail kelimeler, gunlukk butce dusuk)
4. Phrase - Kalifiye (broad'dan gelenler)
5. Exact - Kazananlar (siparise donen kelimeler, yuksek bid)
6. PT - Kazanan ASIN'ler (harvest'ten gelenler)
7. PT - Kategori Defense (kendi ASIN'in)
8. Brand Defense - marka kelimesi exact

## 13. BUTCE DAGILIMI (2026 sektor ortalamasi)
- Sponsored Products: %50-60 (temel, ROAS'i en yuksek)
- Sponsored Brands: %20-30 (marka bilinirligi, video destekli)
- Sponsored Display: %10-20 (retargeting, defense)

Yeni urun launch: %90 SP, %10 SD (retargeting icin).
Olgun urun: %50 SP, %30 SB, %20 SD.

## 14. TROUBLESHOOTING (klasik hatalar)
- ACOS aniden yukseldi: yeni bir rakip kampanya baslatmis olabilir. Impression
  share dususe gecti mi kontrol et. Rakip PPC bidini gozle (spend + share).
- Impression var, click yok: listing/CTR problemi. Ana gorsel + baslik +
  fiyat rekabet analizini yenile.
- Click var, siparis yok: listing/CVR problemi. Kotu inceleme, urun aciklamasi,
  A+ Content, fiyat/kargo.
- Butce erken bitiyor: gunluk butce arttir VE placement multiplier ile secici
  yerlerde odemeyi yogunlastir.
- Auto kampanya kotu: negative harvest yeterli mi? Close/loose/complements/
  substitutes ayri gruplara ayir (bid different).

## 15. ATTRIBUTION VE VERI ZAMANLAMASI
- Amazon 7-14 gunluk attribution kullanir. Son 2-3 gunun verisi eksik.
- Karar vermek icin en az 7 gunluk veri gerek (istatistiksel anlam).
- 14 gunluk pencere ideal. Bir hafta bekle, kucuk degisiklik yap, tekrar bekle.

## 16. KARLILIK vs ACOS (bilinmeyen inceli)
Break-even ACOS = (1 - COGS/fiyat - Amazon fee - FBA fee)
Karli ACOS hedefi = break-even * 0.7 (kar payi birak)

Ornek: $30 fiyat, $8 COGS, %15 fee, $5 FBA = birim kar $12.5 -> break-even ACOS %41
Hedef %30 kabul edilebilir. Break-even'a dokunma - orada ekstra reklam kar
getirmez, sadece hacim.
"""


PRO_INSTRUCTION = """Sen 8+ yil deneyimli, 8 haneli hesaplar yoneten kidemli
Amazon PPC uzmanisin. Yukaridaki uzman bilgi bankasindaki taktikleri kullanan
onerileri uret. Amator seviyede tekrarlarindan uzak dur - profesyonel sinyaller
kullan (placement multipliers, traffic sculpting, dayparting, SD retargeting,
brand defense, kampanya yasi, IS sinyalleri).

Kullanici 100 bin+ dolar reklam butcesi yonetiyor - onerin somut, gerekceli,
sayilarla desteklenmis olmali. Yuzeysel "bid'i dusur" onerisi degil, "bu
kelimedeki TOS IS %28, satis getiriyor. Bid'i $1.20'den $1.55'e cikart (+29%),
placement multiplier'i +%50 ekle. Bir hafta izle, %35+ IS'e ciktiginda
carpanı +%30'a dusur." gibi katmanli onerin olmali.
"""
