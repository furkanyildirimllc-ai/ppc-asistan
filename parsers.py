"""Amazon Ads rapor dosyalarini (csv/xlsx) okur, tipini otomatik tanir, normalize eder."""
import csv
import io
import re

import openpyxl

# Rapor tipini ayirt eden imza kolonlari
SIGNATURES = [
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
    """Yuzde degerini orana cevirir. CSV'de '39.7%' -> 0.397, xlsx'te 0.397 zaten oran."""
    if isinstance(v, str) and "%" in v:
        return _num(v) / 100.0
    n = _num(v)
    # xlsx ACOS bazen 0.397 bazen 39.7 gelebilir; 5'ten buyukse yuzde kabul et
    return n / 100.0 if n > 5 else n


def read_rows(filename, content: bytes):
    """Dosyayi header listesi + dict satirlari olarak dondurur."""
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            return [], []
        headers = [h.strip() for h in rows[0]]
        return headers, [dict(zip(headers, r)) for r in rows[1:]]
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(it, ())]
    out = []
    for row in it:
        if row is None or all(v is None for v in row):
            continue
        out.append(dict(zip(headers, row)))
    wb.close()
    return headers, out


def detect_type(headers):
    hs = set(headers)
    for rtype, sig in SIGNATURES:
        if sig <= hs:
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


def _norm_search_term(r):
    d = _base_metrics(r)
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
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "placement": str(r.get("Placement") or "").strip(),
        "bidding_strategy": str(r.get("Bidding strategy") or "").strip(),
    })
    return d


def _norm_campaign(r):
    d = _base_metrics(r)
    d.update({
        "campaign": str(r.get("Campaign Name") or "").strip(),
        "status": str(r.get("Status") or "").strip(),
        "budget": _num(r.get("Budget Amount")),
        "targeting_type": str(r.get("Targeting Type") or "").strip(),
        "bidding_strategy": str(r.get("Bidding strategy") or "").strip(),
    })
    return d
