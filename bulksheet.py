"""Amazon Sponsored Products Bulk Operations Excel formatinda export.

Amazon Ads Console -> Bulk Operations sayfasinda direkt yuklenebilir.

GUVENLIK KURALI (kritik): Bulk'a SADECE hedef Campaign Name + Ad Group Name
KESIN OLARAK bilinen satirlar yazilir. Bilinmeyen/belirsiz durumda satir bulk
sheet'e YAZILMAZ; onun yerine ayri bir "manuel ekle" listesine dusurulur ve
kullanici Amazon konsolunda normal (guvenli) UI akisiyla ekler. Amac: yanlis
kampanya adi ya da uydurma ad group adiyla bulk satiri yukleyip yanlis yere
harcama baglatmamak.

Neden bu kurala ihtiyac var:
- 'harvest' (yeni exact kelime) ve 'harvest_pt' (yeni urun hedefleme) onerileri
  BIRDEN FAZLA kaynak (auto/broad/phrase) kampanyadan gelir; kelimenin GIDECEGI
  hedef exact kampanya farkli bir kampanyadir ve sistemin bunu bilmesinin tek
  yolu marka ayarlarindaki harvest_campaign/harvest_ad_group alanlaridir.
  Bu alanlar bos ise hedef kesin degildir -> bulk'a yazilmaz.
- Negatif KELIME'ler campaign-level 'Campaign Negative Keyword' entity'siyle
  eklenebilir (ad group gerektirmez) -> bunlar HER ZAMAN guvenle bulk'a yazilir.
- Negatif ASIN (product targeting) Amazon'da sadece ad-group seviyesinde var;
  ad group bilinmedigi icin bunlar da manuel listeye duser.
- Bid guncellemeleri (bid_down/bid_up) targeting raporundan gelir; kampanya VE
  ad group ADI GERCEK ve TEKIL'dir (Amazon'un kendi raporundan) -> her zaman
  guvenle bulk'a yazilir.
"""
import io
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

BULK_HEADERS = [
    "Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
    "Portfolio ID", "Ad ID (Read only)", "Keyword ID (Read only)",
    "Product Targeting ID (Read only)", "Campaign Name", "Ad Group Name",
    "Campaign Name (Informational only)", "Ad Group Name (Informational only)",
    "Portfolio Name (Informational only)", "Start Date", "End Date",
    "Targeting Type", "State", "Daily Budget", "SKU", "ASIN (Informational only)",
    "Eligibility Status (Informational only)", "Reason for Ineligibility (Informational only)",
    "Ad Group Default Bid", "Ad Group Default Bid (Informational only)",
    "Bid", "Keyword Text", "Native Language Keyword", "Native Language Locale",
    "Match Type", "Bidding Strategy",
    "Placement", "Percentage",
    "Product Targeting Expression",
    "Resolved Product Targeting Expression (Informational only)",
    "Impressions", "Clicks", "Click-through Rate", "Spend", "Sales",
    "Orders", "Units", "Conversion Rate", "ACOS", "CPC", "ROAS",
]


def _row(campaign, ad_group, entity, operation, extra):
    r = {h: "" for h in BULK_HEADERS}
    r["Product"] = "Sponsored Products"
    r["Entity"] = entity
    r["Operation"] = operation
    r["Campaign Name"] = campaign
    r["Ad Group Name"] = ad_group
    r["State"] = "enabled"
    r.update(extra)
    return r


def build(recs, brand_name, brand=None):
    """recs -> BytesIO(xlsx). brand: dict (harvest_campaign/harvest_ad_group icerebilir).

    Eger harvest_campaign bos ise, dosyada YENI KAMPANYA + YENI AD GROUP Create
    satirlari otomatik olusturulur - kullanicinin Amazon'da elle kampanya
    olusturmasina gerek kalmaz. Yalnizca ilk Product Ad'i Amazon UI'dan eklemesi
    gerekir (talimatlarda net yazar).
    """
    brand = brand or {}
    dest_campaign = (brand.get("harvest_campaign") or "").strip()
    dest_ad_group = (brand.get("harvest_ad_group") or "").strip()
    # Fallback: default harvest kampanya adi
    if not dest_campaign:
        dest_campaign = f"{brand_name} - Exact - Kazananlar (yeni)"
        auto_create_campaign = True
    else:
        auto_create_campaign = False
    if not dest_ad_group:
        dest_ad_group = "Kazananlar"
    has_dest = True  # artik hep hedef var

    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F2937")

    def sheet(name):
        ws = wb.create_sheet(name)
        ws.append(BULK_HEADERS)
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
        return ws

    kw_ws = neg_ws = pt_ws = setup_ws = None
    manual_rows = []
    skipped_asin_neg = 0

    # ---- Auto Campaign + AdGroup Create (eger harvest_campaign yoksa) ----
    if auto_create_campaign:
        # Harvest onerileri var mi kontrol et
        has_harvest = any(r["type"] in ("harvest", "harvest_pt") for r in recs)
        if has_harvest:
            setup_ws = sheet("SP_SETUP")
            # Campaign Create satiri
            camp_row = {h: "" for h in BULK_HEADERS}
            camp_row.update({
                "Product": "Sponsored Products",
                "Entity": "Campaign",
                "Operation": "Create",
                "Campaign Name": dest_campaign,
                "Start Date": today,
                "Targeting Type": "Manual",
                "State": "enabled",
                "Daily Budget": "20",
                "Bidding Strategy": "Dynamic bids - down only",
            })
            setup_ws.append([camp_row[h] for h in BULK_HEADERS])
            # AdGroup Create satiri
            ag_row = {h: "" for h in BULK_HEADERS}
            ag_row.update({
                "Product": "Sponsored Products",
                "Entity": "Ad Group",
                "Operation": "Create",
                "Campaign Name": dest_campaign,
                "Ad Group Name": dest_ad_group,
                "State": "enabled",
                "Ad Group Default Bid": "1.00",
            })
            setup_ws.append([ag_row[h] for h in BULK_HEADERS])

    for rec in recs:
        rtype = rec["type"]
        mt = (rec.get("match_type") or "").upper()
        kw = rec.get("keyword", "")
        bid = rec.get("suggested_value")
        src_campaign = rec.get("campaign", "")

        if rtype == "harvest":
            if has_dest:
                if kw_ws is None:
                    kw_ws = sheet("SP_KEYWORDS")
                row = _row(dest_campaign, dest_ad_group, "Keyword", "Create", {
                    "Keyword Text": kw, "Match Type": "exact", "Bid": bid or "",
                })
                kw_ws.append([row[h] for h in BULK_HEADERS])
            else:
                manual_rows.append(("Yeni Exact Kelime", src_campaign, kw, bid,
                                     "Hedef exact kampanyana MANUEL ekle"))

        elif rtype == "harvest_pt":
            if has_dest:
                if pt_ws is None:
                    pt_ws = sheet("SP_PRODUCT_TARGETING")
                expr = f'asin="{kw.upper()}"' if kw else ""
                row = _row(dest_campaign, dest_ad_group, "Product Targeting",
                           "Create", {"Product Targeting Expression": expr,
                                      "Bid": bid or ""})
                pt_ws.append([row[h] for h in BULK_HEADERS])
            else:
                manual_rows.append(("Yeni Urun Hedefi (ASIN)", src_campaign, kw, bid,
                                     "Hedef Product Targeting kampanyana MANUEL ekle"))

        elif rtype == "negative":
            if "PRODUCT" in mt:
                # Amazon'da negatif ASIN sadece ad-group seviyesinde var;
                # ad group bilinmedigi icin guvenle bulk'a yazilamaz.
                skipped_asin_neg += 1
                manual_rows.append(("Negatif ASIN", src_campaign, kw, None,
                                     "Bu kampanyada Negative targeting > ASIN ekle"))
            else:
                # Campaign Negative Keyword: ad group gerektirmez, guvenli.
                if neg_ws is None:
                    neg_ws = sheet("SP_NEGATIVES")
                row = _row(src_campaign, "", "Campaign Negative Keyword", "Create", {
                    "Keyword Text": kw, "Match Type": "negativeExact",
                })
                neg_ws.append([row[h] for h in BULK_HEADERS])

        elif rtype in ("bid_down", "bid_up"):
            ad_group = rec.get("ad_group", "")
            if not (src_campaign and ad_group):
                manual_rows.append(("Bid Guncelleme", src_campaign, kw, bid,
                                     "Ad group bilgisi eksik - Amazon'da manuel guncelle"))
                continue
            if kw_ws is None:
                kw_ws = sheet("SP_KEYWORDS")
            row = _row(src_campaign, ad_group, "Keyword", "Update", {
                "Keyword Text": kw, "Match Type": mt.lower(), "Bid": bid or "",
            })
            kw_ws.append([row[h] for h in BULK_HEADERS])
        # placement icin Amazon bulk yok - talimatla veriyoruz (OKU_ONCE)

    # ---- OKU_ONCE ----
    ws0 = wb.create_sheet("OKU_ONCE")
    lines = [
        (f"MARKA: {brand_name}", True),
        (f"Uretilme tarihi: {datetime.now():%d.%m.%Y %H:%M}", False),
        ("", False),
        ("AMAZON'A YUKLEME - 3 ADIM", True),
        ("", False),
        ("1) Amazon Ads Console'a git: advertising.amazon.com/cm/campaigns", False),
        ("2) Sol menude 'Bulk operations' bolumune tikla (Measurement & Reporting altinda olabilir).", False),
        ("3) 'Upload' butonuna bas -> bu Excel dosyayi sec -> 'Upload' tikla.", False),
        ("   Amazon 10-30 sn icinde validate eder. 'Success' gorursen bitti.", False),
        ("", False),
    ]
    if auto_create_campaign and setup_ws:
        lines += [
            ("!!! ONEMLI: ILK YUKLEMEDE PRODUCT AD EKLENECEK !!!", True),
            ("Bu dosya senin icin YENI bir exact kampanya olusturuyor:", False),
            (f"    Kampanya adi: {dest_campaign}", False),
            (f"    Ad group: {dest_ad_group}", False),
            ("Bulk yukleme basarili olduktan SONRA, bu yeni kampanyaya URUN eklemen lazim:", False),
            ("  a) Amazon Ads Console -> yeni kampanyayi ac", False),
            (f"  b) Ad Group '{dest_ad_group}' -> Products / Ads sekmesi", False),
            ("  c) 'Add products' -> reklam yapmak istedigin urun(ler)i sec -> Add", False),
            ("Bu tek seferlik. Sonraki bulksheet yuklemelerinde bu adim gerekmez.", False),
            ("", False),
            ("IPUCU: Marka ayarlarindan 'Harvest kampanya' alanini bir kez doldur:", False),
            ("Boylece sonraki dosyalar var olan kampanyana yazar, yeni acmaya gerek kalmaz.", False),
            ("", False),
        ]
    elif has_dest and not auto_create_campaign:
        lines += [
            (f"HEDEF KAMPANYA: {dest_campaign}", True),
            (f"HEDEF AD GROUP: {dest_ad_group}", True),
            ("Bu dosyadaki harvest kelimeleri yukaridaki kampanyaya eklenir.", False),
            ("Amazon'daki kampanya adinin BIRE BIR bu isim olmasi lazim.", False),
            ("", False),
        ]
    lines += [
        ("SEKMELERIN ICERIGI", True),
    ]
    if setup_ws:
        lines.append(("SP_SETUP        -> yeni kampanya + ad group olusturur (once bu calisir)", False))
    lines += [
        ("SP_KEYWORDS     -> yeni exact kelimeler (Create) + mevcut kelime bid guncellemeleri (Update)", False),
        ("SP_NEGATIVES    -> negatif kelimeler (0 siparis getiren israf yakalari) + traffic sculpting negatifleri", False),
        ("SP_PRODUCT_TARGETING -> yeni ASIN hedefleri (rakip urun sayfalarina reklam)", False),
    ]
    if manual_rows:
        lines += [
            ("MANUEL_EKLE     -> Amazon bulk formatinda desteklenmeyen az sayida ozel satir", False),
        ]
    lines += [
        ("", False),
        ("HATA CIKARSA", True),
        ("- 'Campaign not found' -> SP_KEYWORDS'de Campaign Name yanlis, Amazon'daki gercek isimle kontrol et.", False),
        ("- 'Ad group not found' -> Ad group ismi yanlis - Amazon'da olustur veya SP_SETUP'a ekle.", False),
        ("- 'Bid below minimum' -> bid < $0.15 var, en dusuk $0.15 olmali.", False),
        ("- 'Row rejected' -> o satiri atla, digerleri gecmis olabilir.", False),
        ("", False),
        ("GENEL KURALLAR", True),
        ("- Bid degisikligi sonrasi 7-14 gun bekle, erken mudahale etme.", False),
        ("- Once negatifleri uygula (kanamayi durdur), sonra yeni kelime/bid.", False),
        ("- Bir seferde max %25 bid degisimi - fazlasi algoritmayi konfuze eder.", False),
    ]
    if manual_rows:
        lines += [
            ("", False),
            (f"MANUEL_EKLE sekmesinde {len(manual_rows)} satir var - o kadar da az.", False),
        ]
    for i, (line, bold) in enumerate(lines, 1):
        cell = ws0.cell(row=i, column=1, value=line)
        if bold:
            cell.font = Font(bold=True, size=12, color="F59E0B")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws0.column_dimensions["A"].width = 95

    # ---- MANUEL_EKLE (bulk formatinda DEGIL, sade kopyala-yapistir listesi) ----
    if manual_rows:
        wm = wb.create_sheet("MANUEL_EKLE")
        wm.append(["Kategori", "Kaynak Kampanya(lar)", "Kelime / ASIN",
                    "Onerilen Bid", "Ne Yapmali"])
        for cell in wm[1]:
            cell.font, cell.fill = head_font, head_fill
        for cat, camp, kw, bid, note in manual_rows:
            wm.append([cat, camp, kw, bid, note])
        for i, w in enumerate([22, 40, 34, 12, 46], 1):
            wm.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # Bulk sheet genislikleri
    for ws in wb.worksheets:
        if ws.title in ("OKU_ONCE", "MANUEL_EKLE"):
            continue
        for i, h in enumerate(BULK_HEADERS, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = \
                min(28, max(12, len(h) + 2))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
