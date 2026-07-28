"""Sifir urun (launch) PPC asistani.

Yeni listelenen bir urun icin:
  1) urunu tani (baslik/ASIN/fiyat/rakipler)  -> extension veya gorsel yukleme saglar
  2) keyword bul (rakip basliklarindan + AI genisletme)
  3) kampanya plani kur (Auto + Manual Broad/Phrase/Exact + ASIN targeting)
  4) Amazon canonical bulk sheet uret (Create operasyonlari)

Bu modul mevcut bulksheet.BULK_HEADERS formatini yeniden kullanir; cikti
Seller Central > Bulk Operations'a dogrudan yuklenebilir.
"""
import io
import re
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill

import config
from bulksheet import BULK_HEADERS, _sanitize_name

try:
    import keepa_engine
except Exception:  # pragma: no cover
    keepa_engine = None


# ------------------------------------------------------------------ keywords
_STOP = set("""
a an and or the for with of to in on at by from your you our this that these those
new best top hot sale premium quality pack set of size pcs pack piece pieces
amazon fba prime free shipping buy set kit pack x large small medium
ve ile icin bir bu su cok en daha the a
""".split())

_NOISE_RE = re.compile(r"[^a-z0-9\s\-']")


def _tokens(text):
    text = _NOISE_RE.sub(" ", (text or "").lower())
    return [t for t in text.split() if t and t not in _STOP and len(t) > 2]


def _ngrams(tokens, n):
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def heuristic_keywords(title, competitors, max_kw=40):
    """Baslik + rakip basliklarindan frekansa gore aday keyword'ler."""
    freq = {}
    sources = [title or ""] + [c.get("title", "") for c in (competitors or [])]
    for src in sources:
        toks = _tokens(src)
        for n in (1, 2, 3):
            for g in _ngrams(toks, n):
                # tek kelimelik cok genel terimleri hafif cezalandir
                w = 1.0 if n == 1 else 1.6 if n == 2 else 1.4
                freq[g] = freq.get(g, 0) + w
    # kendi basligindaki terimlere bonus
    own = set(_tokens(title))
    ranked = sorted(freq.items(),
                    key=lambda kv: (kv[1] + (0.5 if set(kv[0].split()) & own else 0)),
                    reverse=True)
    out, seen = [], set()
    for kw, _ in ranked:
        # alt-string tekrarlarini azalt
        if kw in seen:
            continue
        seen.add(kw)
        out.append(kw)
        if len(out) >= max_kw:
            break
    return out


def ai_strategy(title, competitors, price=None, economics=None, model=None):
    """Claude ile tam launch stratejisi: keyword'ler + negatifler + gerekce +
    2 haftalik aksiyon plani. Anahtar yoksa None."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    comp_titles = "\n".join(f"- {c.get('title','')}" for c in (competitors or [])[:14])
    econ_line = ""
    if economics:
        econ_line = (f"\nEKONOMI: birim kar ${economics.get('unit_profit_before_ads')}, "
                     f"break-even ACOS %{economics.get('break_even_acos_pct')}, "
                     f"onerilen hedef ACOS %{economics.get('recommended_target_acos_pct')}. "
                     f"Bid onerilerini bu marja gore mantikli tut.")
    prompt = f"""Sen Amazon PPC uzmanisin. Yeni listelenen ("sifir") bir urun icin
Sponsored Products LAUNCH stratejisi kur.

URUN: {title}
FIYAT: {price or 'bilinmiyor'}{econ_line}
RAKIP BASLIKLARI:
{comp_titles or '(yok)'}

Sadece gecerli JSON dondur, baska hicbir sey yazma:
{{
  "exact": ["5-10 en yuksek donusum, spesifik alici-niyeti terim"],
  "phrase": ["8-15 orta genislik terim"],
  "broad": ["10-20 kesif terim"],
  "brand_defense": ["varsa marka/rakip terimleri, yoksa []"],
  "negatives": ["auto/broad'da bosa para yakacak alakasiz terimler (exact negatif)"],
  "rationale": "2-3 cumle Turkce: bu urun icin launch stratejisinin OZU",
  "action_plan": [
    "Hafta 1: ... (Turkce, somut aksiyon)",
    "Hafta 2: ...",
    "Hafta 3-4: ..."
  ]
}}
Keyword'leri urun dilinde (genelde Ingilizce) yaz. Alakasiz cok-genel tek kelimeleri ele."""
    import json
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    last_err = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model or config.LAUNCH_MODEL,
                max_tokens=2500,
                system="Sadece istenen JSON'u dondur. Aciklama, markdown fence veya ek metin yazma.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                last_err = f"JSON bulunamadi (yanit: {text[:80]!r})"
                continue
            raw = m.group(0)
            try:
                data = json.loads(raw)
            except Exception:
                import json_repair
                data = json_repair.loads(raw)
            clean = {}
            for k in ("exact", "phrase", "broad", "brand_defense", "negatives"):
                vals = data.get(k) or []
                clean[k] = [str(v).strip().lower() for v in vals if str(v).strip()]
            clean["rationale"] = str(data.get("rationale") or "").strip()
            clean["action_plan"] = [str(x).strip() for x in (data.get("action_plan") or []) if str(x).strip()]
            if clean["exact"] or clean["broad"]:
                return clean
            last_err = "bos keyword listesi"
        except Exception as e:
            last_err = str(e)
    print(f"ai_strategy basarisiz (3 deneme): {last_err}")
    return None


def break_even(price, cogs=0, fee_pct=0.15, fba_fee=0):
    """Basit break-even ACOS + onerilen hedef ACOS."""
    p = float(price or 0)
    if p <= 0:
        return None
    unit_profit = p - float(cogs or 0) - p * float(fee_pct or 0.15) - float(fba_fee or 0)
    be = unit_profit / p if p > 0 else 0
    return {
        "unit_profit_before_ads": round(unit_profit, 2),
        "break_even_acos_pct": round(be * 100, 1),
        "recommended_target_acos_pct": round(be * 0.7 * 100, 1),
        "margin_pct_before_ads": round(be * 100, 1),
    }


# ------------------------------------------------------------------ bids/budget
def suggest_bids(price):
    """Fiyata gore baslangic bid'leri (USD). Kaba ama makul launch degerleri."""
    p = float(price or 0)
    if p <= 0:
        base = 0.75
    else:
        # ortalama CPC ~ fiyatin %8-12'si civari baslar
        base = max(0.35, min(3.0, round(p * 0.10, 2)))
    return {
        "auto": round(base * 0.85, 2),
        "broad": round(base * 0.90, 2),
        "phrase": round(base * 1.0, 2),
        "exact": round(base * 1.25, 2),   # exact'a agresif gir
        "pt": round(base * 0.95, 2),
    }


def suggest_budgets(price):
    p = float(price or 0)
    lo = 10 if p < 25 else 15
    return {
        "auto": lo,
        "broad": lo,
        "phrase": lo,
        "exact": lo + 5,   # en cok butce exact'a
        "pt": lo,
    }


# ------------------------------------------------------------------ plan
def build_plan(product, competitors=None, use_ai=True, model=None):
    """product: {title, asin, sku, price, brand, cogs, fba_fee, fee_pct}. -> plan dict."""
    title = product.get("title") or ""
    asin = (product.get("asin") or "").strip()
    sku = (product.get("sku") or "").strip() or asin  # SKU yoksa ASIN'i placeholder yap
    price = product.get("price")
    competitors = competitors or []

    econ = break_even(price, product.get("cogs"),
                      product.get("fee_pct", 0.15), product.get("fba_fee"))

    heur = heuristic_keywords(title, competitors)
    ai = ai_strategy(title, competitors, price, econ, model=model) if use_ai else None

    negatives, rationale, action_plan = [], "", []
    if ai:
        exact = ai.get("exact") or heur[:8]
        phrase = ai.get("phrase") or heur[:15]
        broad = ai.get("broad") or heur[:20]
        negatives = ai.get("negatives") or []
        rationale = ai.get("rationale") or ""
        action_plan = ai.get("action_plan") or []
        source = "ai"
    else:
        exact = heur[:8]
        phrase = heur[:15]
        broad = heur[:20]
        source = "heuristic"

    # ASIN targeting: rakip ASIN'ler + Keepa "birlikte alinan"
    comp_asins = [c.get("asin") for c in competitors if c.get("asin")]
    if keepa_engine and asin and config.KEEPA_API_KEY:
        try:
            for rec in keepa_engine.search_related_asins(asin):
                a = rec.get("keyword")
                if a and a not in comp_asins:
                    comp_asins.append(a)
        except Exception:
            pass
    comp_asins = list(dict.fromkeys(comp_asins))[:20]

    bids = suggest_bids(price)
    budgets = suggest_budgets(price)
    prefix = _sanitize_name(product.get("brand") or title[:20] or "Launch")[:24] or "Launch"

    campaigns = [
        {"key": "auto", "name": f"{prefix} | Auto | Discovery",
         "targeting_type": "Auto", "budget": budgets["auto"],
         "default_bid": bids["auto"], "match": None, "keywords": [],
         "auto_groups": True, "product_targets": [], "negatives": negatives},
        {"key": "broad", "name": f"{prefix} | Manual | Broad Research",
         "targeting_type": "Manual", "budget": budgets["broad"],
         "default_bid": bids["broad"], "match": "broad", "keywords": broad,
         "auto_groups": False, "product_targets": [], "negatives": negatives},
        {"key": "phrase", "name": f"{prefix} | Manual | Phrase",
         "targeting_type": "Manual", "budget": budgets["phrase"],
         "default_bid": bids["phrase"], "match": "phrase", "keywords": phrase,
         "auto_groups": False, "product_targets": [], "negatives": negatives},
        {"key": "exact", "name": f"{prefix} | Manual | Exact (Scale)",
         "targeting_type": "Manual", "budget": budgets["exact"],
         "default_bid": bids["exact"], "match": "exact", "keywords": exact,
         "auto_groups": False, "product_targets": [], "negatives": []},
    ]
    if comp_asins:
        campaigns.append(
            {"key": "pt", "name": f"{prefix} | Manual | ASIN Targeting",
             "targeting_type": "Manual", "budget": budgets["pt"],
             "default_bid": bids["pt"], "match": None, "keywords": [],
             "auto_groups": False, "product_targets": comp_asins, "negatives": []})

    total_budget = sum(c["budget"] for c in campaigns)
    return {
        "product": {"title": title, "asin": asin, "sku": sku,
                    "price": price, "brand": product.get("brand")},
        "keyword_source": source,
        "competitor_count": len(competitors),
        "competitor_asins": comp_asins,
        "keywords": {"exact": exact, "phrase": phrase, "broad": broad},
        "negatives": negatives,
        "economics": econ,
        "rationale": rationale,
        "action_plan": action_plan,
        "bids": bids,
        "budgets": budgets,
        "daily_budget_total": round(total_budget, 2),
        "campaigns": campaigns,
        "notes": _launch_notes(sku, asin, source),
    }


def _launch_notes(sku, asin, source):
    notes = []
    if sku == asin:
        notes.append("⚠️ SKU girilmedi — bulk sheet'te ASIN placeholder olarak kullanildi. "
                     "Seller iseniz Product Ad satirlarinda GERCEK SKU'nuzu yazin.")
    if source == "heuristic":
        notes.append("ℹ️ AI anahtari yok/kapali — keyword'ler rakip basliklarindan sezgisel cikarildi.")
    notes.append("💡 Launch stratejisi: 2 hafta veri topla, exact'a kazananlari tasi, "
                 "auto/broad'daki alakasiz terimleri negatif yap.")
    return notes


# ------------------------------------------------------------------ bulksheet
_AUTO_EXPR = [
    ("close-match", "loose-match", "substitutes", "complements"),
]


def _blank():
    return {h: "" for h in BULK_HEADERS}


def build_bulksheet(plan):
    """plan -> BytesIO(xlsx). Amazon SP Create operasyonlari."""
    p = plan["product"]
    asin = p.get("asin") or ""
    sku = p.get("sku") or asin
    today = datetime.now().strftime("%Y%m%d")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Sponsored Products Campaigns")
    ws.append(BULK_HEADERS)
    head_font = Font(bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font, cell.fill = head_font, head_fill
    ws.freeze_panes = "A2"

    def emit(d):
        ws.append([d.get(h, "") for h in BULK_HEADERS])

    for c in plan["campaigns"]:
        cid = _sanitize_name(c["name"])          # placeholder ID = kampanya adi
        agid = f"{cid} - AG"
        ag_name = "Ad Group 1"

        # 1) Campaign
        r = _blank()
        r.update({
            "Product": "Sponsored Products", "Entity": "Campaign",
            "Operation": "Create", "Campaign ID": cid, "Campaign Name": c["name"],
            "Start Date": today, "Targeting Type": c["targeting_type"],
            "State": "enabled", "Daily Budget": c["budget"],
            "Bidding Strategy": "Dynamic bids - down only",
        })
        emit(r)

        # 2) Ad Group
        r = _blank()
        r.update({
            "Product": "Sponsored Products", "Entity": "Ad Group",
            "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
            "Ad Group Name": ag_name, "State": "enabled",
            "Ad Group Default Bid": c["default_bid"],
        })
        emit(r)

        # 3) Product Ad
        r = _blank()
        r.update({
            "Product": "Sponsored Products", "Entity": "Product Ad",
            "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
            "State": "enabled", "SKU": sku, "ASIN (Informational only)": asin,
        })
        emit(r)

        # 3b) Negatif exact keyword'ler (bosa harcamayi keser)
        for nk in c.get("negatives", []):
            r = _blank()
            r.update({
                "Product": "Sponsored Products", "Entity": "Negative Keyword",
                "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
                "State": "enabled", "Keyword Text": nk, "Match Type": "negativeExact",
            })
            emit(r)

        # 4a) Auto targeting gruplari
        if c.get("auto_groups"):
            for grp in ("close-match", "loose-match", "substitutes", "complements"):
                r = _blank()
                r.update({
                    "Product": "Sponsored Products", "Entity": "Product Targeting",
                    "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
                    "State": "enabled", "Bid": c["default_bid"],
                    "Product Targeting Expression": grp,
                })
                emit(r)

        # 4b) Keyword'ler
        for kw in c.get("keywords", []):
            r = _blank()
            r.update({
                "Product": "Sponsored Products", "Entity": "Keyword",
                "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
                "State": "enabled", "Bid": c["default_bid"],
                "Keyword Text": kw, "Match Type": c["match"],
            })
            emit(r)

        # 4c) ASIN product targeting
        for a in c.get("product_targets", []):
            r = _blank()
            r.update({
                "Product": "Sponsored Products", "Entity": "Product Targeting",
                "Operation": "Create", "Campaign ID": cid, "Ad Group ID": agid,
                "State": "enabled", "Bid": c["default_bid"],
                "Product Targeting Expression": f'asin="{a}"',
            })
            emit(r)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
