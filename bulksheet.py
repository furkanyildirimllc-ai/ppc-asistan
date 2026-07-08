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
    """recs -> BytesIO(xlsx). brand: dict (harvest_campaign/harvest_ad_group icerebilir)."""
    brand = brand or {}
    dest_campaign = (brand.get("harvest_campaign") or "").strip()
    dest_ad_group = (brand.get("harvest_ad_group") or "").strip()
    has_dest = bool(dest_campaign and dest_ad_group)

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

    kw_ws = neg_ws = pt_ws = None
    manual_rows = []  # (kategori, kaynak_kampanya(lar), kelime/ASIN, bid, not)
    skipped_asin_neg = 0

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
        ("", False),
        ("BU DOSYA GUVENLI BULK UPLOAD ICIN URETILDI.", True),
        ("Kural: sadece hedef kampanya/ad-group KESIN bilinen satirlar bulk", False),
        ("sheet'lere yazildi. Belirsiz olanlar asagida 'MANUEL_EKLE' sekmesinde.", False),
        ("", False),
        ("1. Amazon Ads Console -> Bulk Operations -> Upload spreadsheet", True),
        ("2. Bu dosyayi yukle (SP_KEYWORDS / SP_NEGATIVES / SP_PRODUCT_TARGETING)", False),
        ("3. Amazon her satiri validate eder; hata varsa duzelt, tekrar yukle", False),
        ("4. Sonra MANUEL_EKLE sekmesindeki satirlari Amazon UI'dan elle ekle", False),
        ("", False),
        ("SEKME ICERIKLERI", True),
        ("SP_KEYWORDS: bid guncellemeleri (mevcut kelimeler, Update)"
         + (" + yeni exact kelimeler (Create)" if has_dest else ""), False),
        ("SP_NEGATIVES: negatif kelimeler (Campaign Negative Keyword - kampanya "
         "genelinde gecerli, ad group gerektirmez)", False),
        ("SP_PRODUCT_TARGETING: " + ("yeni ASIN hedefleri (Create)" if has_dest
         else "bos - hedef kampanya ayari yapilmadi, MANUEL_EKLE'ye bak"), False),
    ]
    if not has_dest:
        lines += [
            ("", False),
            ("NEDEN YENI KELIMELER BULK'TA YOK?", True),
            ("Yeni kelimelerin GIDECEGI exact kampanya/ad group adi sistemde "
             "tanimli degil. Yanlis kampanyaya otomatik eklemek riskli oldugu "
             "icin bu satirlar MANUEL_EKLE sekmesine alindi.", False),
            ("Otomatiklestirmek icin: Ayarlar > 'Yeni kelime hedef kampanya/ad "
             "group' alanlarini bir kere doldur -> sonraki bulksheet'ler otomatik "
             "bu hedefe Create satiri yazar.", False),
        ]
    if manual_rows:
        lines += [
            ("", False),
            (f"MANUEL_EKLE sekmesinde {len(manual_rows)} satir var.", True),
            ("Bunlari Amazon Ads Console'da ilgili kampanyanin normal 'Add "
             "keywords / Add negative targeting' ekranindan elle ekle - bu "
             "ekranda kampanya/ad group'u sen secersin, yanlis yer riski yoktur.", False),
        ]
    lines += [
        ("", False),
        ("GENEL KURALLAR", True),
        ("- Bid degisikligi sonrasi 7-14 gun bekle, erken mudahale etme.", False),
        ("- Once negatifleri uygula (kanamayi durdur), sonra yeni kelime/bid.", False),
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
