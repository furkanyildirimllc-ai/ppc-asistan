"""Amazon Sponsored Products Bulk Operations Excel formatinda export.

Amazon Ads Console -> Bulk Operations sayfasinda direkt yuklenebilir.
Onemli: gercek kampanya adlarinin Amazon'daki adlarla ayni olmasi gerek.
Kullanici yeni kampanya/adgroup icin manuel yaratma dilekcesi gorur.
"""
import io
import openpyxl
from openpyxl.styles import Font, PatternFill

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


def _row_dict(**kw):
    return {h: kw.get(h.split(" (")[0].lower().replace(" ", "_").replace("-", "_"),
                      kw.get(h, "")) for h in BULK_HEADERS}


def _row(rec, entity, operation, extra):
    r = {h: "" for h in BULK_HEADERS}
    r["Product"] = "Sponsored Products"
    r["Entity"] = entity
    r["Operation"] = operation
    r["Campaign Name"] = rec.get("campaign", "")
    r["Ad Group Name"] = rec.get("ad_group", "") or "Ad Group"
    r["State"] = "enabled"
    r.update(extra)
    return r


def build(recs, brand_name):
    """recs -> BytesIO(xlsx)"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F2937")
    warn_fill = PatternFill("solid", fgColor="7C2D12")

    # Talimatlar sayfasi
    ws0 = wb.create_sheet("OKU_ONCE")
    lines = [
        f"Marka: {brand_name}",
        "",
        "Bu dosya Amazon Sponsored Products Bulk Upload icin uretildi.",
        "1. Amazon Ads Console -> Bulk Operations",
        "2. 'Upload spreadsheet' bolumune bu dosyayi yukle",
        "3. Amazon her satiri validate edecek, hatalari duzelt ve yeniden yukle",
        "",
        "ONEMLI:",
        "- Kampanya/AdGroup adlari Amazon'daki gercek adlarla ayni OLMALI",
        "- Yeni kampanya/adgroup olusturuluyorsa 'Operation' = Create",
        "- Guncelleme yapiliyorsa 'Operation' = Update",
        "- Bid degerleri USD cinsinden",
        "- SP_KEYWORDS: harvest (yeni kelime) ve bid guncelleme",
        "- SP_NEGATIVES: negatif kelime/urun",
        "- SP_PRODUCT_TARGETING: ASIN hedefleme",
        "- SP_CAMPAIGNS: (opsiyonel) yeni kampanya olusturmak icin",
    ]
    for i, line in enumerate(lines, 1):
        cell = ws0.cell(row=i, column=1, value=line)
        if line.startswith("ONEMLI") or line.startswith("Marka"):
            cell.font = Font(bold=True)
    ws0.column_dimensions["A"].width = 90

    def sheet(name):
        ws = wb.create_sheet(name)
        ws.append(BULK_HEADERS)
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
        return ws

    kw_ws = None
    neg_ws = None
    pt_ws = None

    for rec in recs:
        rtype = rec["type"]
        mt = (rec.get("match_type") or "").upper()
        kw = rec.get("keyword", "")
        bid = rec.get("suggested_value")
        if rtype == "harvest":
            if kw_ws is None:
                kw_ws = sheet("SP_KEYWORDS")
            row = _row(rec, "Keyword", "Create", {
                "Keyword Text": kw, "Match Type": "exact",
                "Bid": bid or "",
            })
            kw_ws.append([row[h] for h in BULK_HEADERS])
        elif rtype == "harvest_pt":
            if pt_ws is None:
                pt_ws = sheet("SP_PRODUCT_TARGETING")
            expr = f'asin="{kw.upper()}"' if kw else ""
            row = _row(rec, "Product Targeting", "Create", {
                "Product Targeting Expression": expr,
                "Bid": bid or "",
            })
            pt_ws.append([row[h] for h in BULK_HEADERS])
        elif rtype == "negative":
            if neg_ws is None:
                neg_ws = sheet("SP_NEGATIVES")
            if "PRODUCT" in mt:
                row = _row(rec, "Negative Product Targeting", "Create", {
                    "Product Targeting Expression": f'asin="{kw.upper()}"',
                })
            else:
                row = _row(rec, "Negative Keyword", "Create", {
                    "Keyword Text": kw,
                    "Match Type": "negativeExact",
                })
            neg_ws.append([row[h] for h in BULK_HEADERS])
        elif rtype in ("bid_down", "bid_up"):
            if kw_ws is None:
                kw_ws = sheet("SP_KEYWORDS")
            row = _row(rec, "Keyword", "Update", {
                "Keyword Text": kw, "Match Type": mt.lower(),
                "Bid": bid or "",
            })
            kw_ws.append([row[h] for h in BULK_HEADERS])
        # placement icin Amazon bulk manuel - talimatlarla veriyoruz

    # Genislikleri ayarla
    for ws in wb.worksheets:
        if ws.title == "OKU_ONCE":
            continue
        for i, h in enumerate(BULK_HEADERS, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = \
                min(28, max(12, len(h) + 2))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
