"""AI Strateji Ajani - Claude Sonnet ile PPC stratejisi uretir.

Girdi: marka ayarlari + ozet metrikler + deterministik oneriler + ornek satirlar
Cikti: JSON {executive_summary, new_campaigns, keyword_groups, extra_negatives,
             bid_commentary, budget_allocation, data_sufficiency}

web_search tool'unu Claude kendi karariyla cagirir (sezon/benchmark/policy icin).
"""
import json
import re
from anthropic import Anthropic

import config
from expert_knowledge import EXPERT_KNOWLEDGE, PRO_INSTRUCTION

_client = None


def client():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY .env'de tanimli degil")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = EXPERT_KNOWLEDGE + "\n\n" + PRO_INSTRUCTION + "\n\n" + """Sen kidemli bir Amazon PPC strategist'isin. Turkce cevap ver.

Isin: Kullanicidan gelen marka verisi + deterministik matematik onerileri uzerine
STRATEJIK katman ekle. Matematiksel bid hesaplarini DEGISTIRME - onlar dogru.
Sen sunlari yap:

1. YENI KAMPANYA PLANLARI: Mevcut yapida eksik olan kampanyalar var mi?
   (ornek: Exact "kazananlar" kampanyasi, PT kampanyasi, marka savunma kampanyasi,
   SB/SD icin oneriler)

2. KELIME GRUPLARI: Harvest edilecek kelimeleri anlamli ad group'lara grupla.
   (ornek: "kadin spor ayakkabi" ve "bayan kosu ayakkabi" ayni grup)

3. EKSTRA NEGATIFLER (SEMANTIK): Deterministik motor sadece "0 siparis + esik"
   ile calisir. Sen semantik olarak alakasiz olabilecekleri de tespit et.
   (ornek: premium urunde "cheap", "free"; kadin urununde "erkek", "men's")

4. BID YORUMU: Deterministik onerilerdeki bid degerlerini AYNI birak, ama
   "bu terim yukselen trend" gibi stratejik yorumlar ekle.

5. BUTCE DAGILIMI: Toplam bir gunluk butce icin kampanya bazinda oneri.

6. VERI YETERLILIGI: Her bolum icin veri yeterli mi degerlendir. Yetersizse
   {"insufficient": true, "reason": "...", "recheck_after_days": N} dondur.

7. WEB ARAMA: Kategori benchmark'i, sezonluk trend veya Amazon Ads policy
   guncellemesi hakkinda EMIN DEGILSEN web_search tool'unu kullan. Emin oldugun
   konularda kullanma - gereksiz maliyet.

CIKTI FORMATI: SADECE bir JSON blogu dondur, baska hicbir metin YOK.
JSON semasi:
{
  "executive_summary": "2-3 cumle genel durum",
  "data_sufficiency": {
    "overall": "sufficient" | "partial" | "insufficient",
    "notes": "haftaya tekrar bakalim gibi notlar"
  },
  "new_campaigns": [
    {"name": "...", "type": "SP Exact|SP PT|SB|SD", "why": "...",
     "seed_keywords_or_asins": [...], "suggested_daily_budget_usd": N,
     "starting_bid_usd": N, "priority": "high|medium|low"}
  ],
  "keyword_groups": [
    {"ad_group_name": "...", "keywords": [...], "match_type": "EXACT",
     "target_campaign": "..."}
  ],
  "extra_negatives": [
    {"keyword": "...", "match_type": "NEGATIVE PHRASE|NEGATIVE EXACT",
     "scope": "campaign_name veya 'account-level'", "reason": "..."}
  ],
  "bid_commentary": [
    {"keyword": "...", "commentary": "...", "confidence": "high|medium|low"}
  ],
  "budget_allocation": {
    "notes": "...",
    "distribution": [{"campaign_or_type": "...", "percent": N, "reason": "..."}]
  },
  "web_findings": "web_search kullandiysan buldugun ozet, yoksa null"
}
"""


def _summarize(rows, keys, limit=25):
    """AI'ya gonderilecek satirlari kucult: en yuksek harcamalilar."""
    ranked = sorted(rows, key=lambda r: -r.get("spend", 0))[:limit]
    return [{k: r.get(k) for k in keys} for r in ranked]


def _totals(rows):
    return {
        "clicks": int(sum(r.get("clicks", 0) for r in rows)),
        "spend": round(sum(r.get("spend", 0) for r in rows), 2),
        "sales": round(sum(r.get("sales", 0) for r in rows), 2),
        "orders": int(sum(r.get("orders", 0) for r in rows)),
    }


def build_input(brand, search_terms, targets, placements, campaigns, det_recs):
    """AI'ya gidecek yapiyi hazirlar."""
    st_keys = ["campaign", "term", "match_type", "clicks", "spend", "sales",
               "orders", "is_asin"]
    tg_keys = ["campaign", "targeting", "match_type", "clicks", "spend",
               "sales", "orders", "cpc", "acos", "tos_is"]
    pl_keys = ["campaign", "placement", "clicks", "spend", "sales", "orders"]
    cp_keys = ["campaign", "targeting_type", "budget", "clicks", "spend",
               "sales", "orders", "status"]

    return {
        "brand": {
            "name": brand["name"],
            "target_acos_pct": round(brand["target_acos"] * 100, 1),
        },
        "totals": {
            "search_terms": _totals(search_terms),
            "targets": _totals(targets),
            "placements": _totals(placements),
            "campaigns": _totals(campaigns) if campaigns else None,
        },
        "campaigns_top15": _summarize(campaigns, cp_keys, 15) if campaigns else [],
        "search_terms_top30_by_spend": _summarize(search_terms, st_keys, 30),
        "targets_top30_by_spend": _summarize(targets, tg_keys, 30),
        "placements_all": _summarize(placements, pl_keys, 20),
        "deterministic_recommendations": [
            {"type": r["type"], "campaign": r["campaign"], "keyword": r["keyword"],
             "match_type": r["match_type"], "current_value": r["current_value"],
             "suggested_value": r["suggested_value"], "reason": r["reason"],
             "metrics": r["metrics"]}
            for r in det_recs
        ],
    }


def _extract_json(text):
    """Modelin cevabindan ilk JSON blogunu cikar."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # ilk { den son } a
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}


def generate_strategy(payload):
    """Sonnet'ten strateji uret. Return: dict."""
    user_msg = ("Amazon PPC verisi ve deterministik onerilerim asagida. "
                "Sistem talimatindaki JSON semasina UYGUN sekilde strateji uret.\n\n"
                f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")

    resp = client().messages.create(
        model=config.STRATEGY_MODEL,
        max_tokens=config.MAX_STRATEGY_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": user_msg}],
    )

    # Tum text bloklarini birlestir (web_search ara ciktilarindan sonra final text gelir)
    parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    text = "\n".join(parts).strip()

    used_web = any(getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")
                   for b in resp.content)

    try:
        data = _extract_json(text)
    except Exception as e:
        return {
            "error": f"AI cikti parse edilemedi: {e}",
            "raw_output": text[:2000],
            "web_search_used": used_web,
        }
    data["_meta"] = {
        "model": config.STRATEGY_MODEL,
        "web_search_used": used_web,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return data
