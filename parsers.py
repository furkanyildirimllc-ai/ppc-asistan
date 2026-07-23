"""Amazon Ads rapor dosyalarini (csv/xlsx) okur, tipini otomatik tanir, normalize eder."""
import csv
import io
import re

import openpyxl

# Rapor tipini ayirt eden imza kolonlari
SIGNATURES = [
    ("bulk_ids", {"Entity", "Operation", "Campaign ID"}),
    ("search_term_is", {"Customer Search Term", "Search Term Impression Rank"}),
    ("search_term", {"Customer Search Term", "Match Type"}),
    ("targeting", {"Targeting", "Top-of-search Impression Share"}),
    ("placement", {"Placement", "Bidding strategy"}),
    ("campaign", {"Budget Amount", "Targeting Type"}),
]

REPORT_LABELS = {
    "search_term": "Search Term Raporu",
    "search_term_is": "Search Term Impression Share Raporu",
    "targeting": "Targeting Raporu",
    "placement": "Placement Raporu",
    "campaign": "Kampanya Raporu",
    "bulk_ids": "Bulk Operations (Campaign/Ad Group ID eslemesi)",
}

ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$", re.IGNORECASE)


def _num(v):
    """'$1,234.56', '12.5%', '-', None -> float"""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if s in ("", "-", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _pct(v):
    """Yuzde degerini orana cevirir. CSV'de '39.7%' -> 0.397, xlsx'te 0.397 zaten oran.

    Mantik: xlsx'te ACOS bazen 0.397 (oran) bazen 39.7 (yuzde) olarak gelir.
    Esik 1.0: 1'den buyukse yuzde kabul et (39.7 -> 0.397), kucukse oran kabul et.
    Eski esik 5.0'ti — bu %1-5 arasi ACOS degerlerini yanlis yorumluyordu!
    """
    if isinstance(v, str) and "%" in v:
        return _num(v) / 100.0
    n = _num(v)
    return n / 100.0 if n > 1.0 else n


def _read_sheet(ws):
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(it, ())]
    out = []
    for row in it:
        if row is None or all(v is None for v in row):
            continue
        out.append(dict(zip(headers, row)))
    return headers, out


def read_rows(filename, content: bytes):
    """Dosyayi header listesi + dict satirlari olarak dondurur.

    Amazon'un 'Bulk operations > Download spreadsheet' dosyasi COK SEKMELIDIR
    (Portfolios, Sponsored Products Campaigns, Sponsored Brands Campaigns, ...)
    ve openpyxl'in 'aktif' sekmesi bizim istedigimiz veri olmayabilir (ornegin
    Portfolios sekmesi acik kalmis olabilir). Once aktif sekmeyi dene, taninmazsa
    diger sekmeleri sirayla tara ve ilk taninan sekmeyi kullan.
    """
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            return [], []
        headers = [h.strip() for h in rows[0]]
        return headers, [dict(zip(headers, r)) for r in rows[1:]]
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    headers, out = _read_sheet(wb.active)
    if detect_type(headers) is None:
        for name in wb.sheetnames:
            if wb[name] is wb.active:
                continue
            h2, r2 = _read_sheet(wb[name])
            if detect_type(h2) is not None:
                headers, out = h2, r2
                break
    wb.close()
    return headers, out


def detect_type(headers):
    hs = set(headers)
    for rtype, sig in SIGNATURES:
        if sig <= hs:
            return rtype
    # Fallback: case-insensitive eslestirme (Amazon bazen kolon adlarini degistirir)
    hs_lower = {h.lower() for h in headers}
    for rtype, sig in SIGNATURES:
        if {s.lower() for s in sig} <= hs_lower:
            return rtype
    return None


def parse(filename, content: bytes):
    """-> (report_type, normalized_rows)"""
    headers, rows = read_rows(filename, content)
    rtype = detect_type(headers)
    if rtype is None:
        raise ValueError(
            f"Rapor tipi taninamadi. Kolonlar: {', '.join(headers[:8])}...")
    if rtype == "search_term":
        return rtype, [_norm_search_term(r) for r in rows]
    if rtype == "targeting":
        return rtype, [_norm_targeting(r) for r in rows]
    if rtype == "campaign":
        return rtype, [_norm_campaign(r) for r in rows]
    if rtype == "placement":
        return rtype, [_norm_placement(r) for r in rows]
    if rtype == "bulk_ids":
        return rtype, [_norm_bulk_ids(r) for r in rows]
    # impression share: simdilik saklamiyoruz
    return rtype, []


def _base_metrics(r):
    return {
        "impressions": _num(r.get("Impressions")),
        "clicks": _num(r.get("Clicks")),
        "spend": _num(r.get("Spend")),
        "sales": _num(r.get("7 Day Total Sales ") or r.get("7 Day Total Sales")),
        "orders": _num(r.get("7 Day Total Orders (#)")),
        "cpc": _num(r.get("Cost Per Click (CPC)")),
        "acos": _pct(r.get("Total Advertising Cost of Sales (ACOS) ")
                     or r.get("Total Advertising Cost of Sales (ACOS)")),
    }


def _id(v):
    """Amazon ID kolonlarini normalize et (float/int/str)."""
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _ids(r):
    """Amazon rapor kolonlarindan Campaign/AdGroup/Portfolio/Keyword/Target ID'lerini yakala."""
    return {
        "campaign_id": _id(r.get("Campaign ID")),
        "ad_group_id": _id(r.get("Ad Group ID")),
        "portfolio_id": _id(r.get("Portfolio ID")),
        "keyword_id": _id(r.get("Keyword ID") or r.get("Keyword or Product Targeting ID")),
        "targeting_id": _id(r.get("Product Targeting ID")),
    }


def _norm_search_term(r):
    d = _base_metrics(r)
    d.update(_ids(r))
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "ad_group": str(r.get("Ad Group Name") or "").strip(),
        "targeting": str(r.get("Targeting") or "").strip(),
        "match_type": str(r.get("Match Type") or "").strip().upper(),
        "term": str(r.get("Customer Search Term") or "").strip().lower(),
    })
    d["is_asin"] = bool(ASIN_RE.match(d["term"]))
    return d


def _norm_targeting(r):
    d = _base_metrics(r)
    d.update(_ids(r))
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "ad_group": str(r.get("Ad Group Name") or "").strip(),
        "targeting": str(r.get("Targeting") or "").strip(),
        "match_type": str(r.get("Match Type") or "").strip().upper(),
        "tos_is": _pct(r.get("Top-of-search Impression Share")),
    })
    return d


def _norm_placement(r):
    d = _base_metrics(r)
    d.update(_ids(r))
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "placement": str(r.get("Placement") or "").strip(),
        "bidding_strategy": str(r.get("Bidding strategy") or "").strip(),
    })
    return d


def _norm_bulk_ids(r):
    """Amazon 'Bulk Operations' indirmesinden Campaign/Ad Group/Keyword ID
    eslemesini cikarir. Bu dosyada metrik yok - sadece isim<->ID eslemesi icin
    kullanilir.

    ONEMLI: Amazon ust seviye satirlarda (Campaign, Ad Group) ismi 'Campaign
    Name'/'Ad Group Name' kolonuna yazar, ama alt seviye satirlarda (Keyword,
    Product Targeting) bu kolonlar BOS birakilir - isim sadece 'Campaign Name
    (Informational only)' / 'Ad Group Name (Informational only)' kolonlarinda
    bulunur. Ikisini de dener, hangisi doluysa onu kullanir."""
    d = _ids(r)
    campaign = r.get("Campaign Name") or r.get("Campaign Name (Informational only)")
    ad_group = r.get("Ad Group Name") or r.get("Ad Group Name (Informational only)")
    d.update({
        "campaign": str(campaign or "").strip(),
        "ad_group": str(ad_group or "").strip(),
        "entity": str(r.get("Entity") or "").strip(),
        "keyword": str(r.get("Keyword Text") or "").strip().lower(),
        "match_type": str(r.get("Match Type") or "").strip().upper(),
        # Entity == 'Bidding Adjustment' satirlari icin: mevcut placement
        # carpanini okumak icin (tahmin etmek yerine gercek degerden Update
        # yapabilmek). Diger entity turlerinde bos kalir.
        "placement": str(r.get("Placement") or "").strip(),
        "percentage": _num(r.get("Percentage")),
        "impressions": 0, "clicks": 0, "spend": 0, "sales": 0,
        "orders": 0, "cpc": 0, "acos": 0,
    })
    return d


def _norm_campaign(r):
    d = _base_metrics(r)
    d.update(_ids(r))
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "status": str(r.get("Status") or "").strip(),
        "budget": _num(r.get("Budget Amount")),
        "targeting_type": str(r.get("Targeting Type") or "").strip(),
        "bidding_strategy": str(r.get("Bidding strategy") or "").strip(),
    })
    return d
