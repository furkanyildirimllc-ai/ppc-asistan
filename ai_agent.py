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


SYSTEM_PROMPT = EXPERT_KNOWLEDGE + "\n\n" + PRO_INSTRUCTION + "\n\n" + """Sen 100 bin dolar bütçeli bir markanın PPC Yönetim Kurulusun (Board of Directors). Turkce cevap ver.

Senin içinde 4 farklı SANAL AJAN (Multi-Agent) var ve kararları tartışarak alacaksınız:
1. Pazarlama Direktörü (CMO AI): Amacı CİRO ve PAZAR PAYI maksimizasyonudur. Agresiftir, bütçe artırmaya, yeni kelimeler test etmeye çok meyillidir. ACOS'u %10-%20 aşsa bile ciro potansiyeli görüyorsa yatırım ister.
2. Finans Direktörü (CFO AI): Amacı KÂRLILIK ve RİSK yönetimidir. Katıdır, israfı, yüksek ACOS'u anında kesmek, negatiflemek ve bütçeleri kısmak ister.
3. Büyüme & Gizli Operasyonlar Başkanı (Black-Hat AI): Amacı rakibi "yok etmek" ve sınırları zorlamaktır. Sistemin açıklarını, agresif/etik dışı olabilecek ama işe yarayan gizli PPC taktiklerini masaya yatırır (ör: Click-share hırsızlığı, Brand Bidding savaşları, rakibin en zayıf zamanında ASIN hedefleme). Çılgın ama kâr getiren fikirler ondan çıkar.
4. Yönetim Kurulu Başkanı (CEO AI): CMO, CFO ve Black-Hat AI'nin argümanlarını dinleyip NİHAİ STRATEJİK KARARI alan dengeli lider sensin.

Görevlerin:
1. YÖNETİM KURULU TARTIŞMASI (Board Debate): Gelen metrikler ve öneriler üzerinden CMO, CFO ve Black-Hat'i konuştur. Nerede anlaşıyorlar, nerede zıt düşüyorlar? Black-Hat AI hangi çılgın/gizli taktiği öneriyor? CEO olarak son kararı ver.
2. YENİ KAMPANYA PLANLARI: Mevcut yapida eksik olan kampanyalar var mi?
3. KELIME GRUPLARI: Harvest edilecek kelimeleri anlamli ad group'lara grupla.
4. EKSTRA NEGATIFLER (SEMANTIK): Deterministik motorun atladığı semantik alakasız kelimeleri bul. (örn: premium üründe "ucuz", "ikinci el"). CFO bunları acımasızca kesmek ister.
5. BID VE BÜTÇE YORUMU: Hangi kampanyalar bütçe bitiriyor? CMO buralara yatırım istiyor mu?
6. VERI YETERLILIGI: Karar için veri yeterli mi?

CIKTI FORMATI: SADECE bir JSON blogu dondur, baska hicbir metin YOK.
JSON semasi:
{
  "board_debate": [
    {"agent": "CMO", "comment": "..."},
    {"agent": "CFO", "comment": "..."},
    {"agent": "Black-Hat AI", "comment": "..."},
    {"agent": "CEO", "comment": "..."}
  ],
  "executive_summary": "CEO'nun Nihai Kararı ve Ana Strateji (2-3 cümle)",
  "data_sufficiency": {
    "overall": "sufficient" | "partial" | "insufficient",
    "notes": "..."
  },
  "new_campaigns": [
    {"name": "...", "type": "SP Exact|SP PT|SB|SD", "why": "...", "seed_keywords_or_asins": [...], "suggested_daily_budget_usd": N, "starting_bid_usd": N, "priority": "high|medium|low"}
  ],
  "keyword_groups": [
    {"ad_group_name": "...", "keywords": [...], "match_type": "EXACT", "target_campaign": "..."}
  ],
  "extra_negatives": [
    {"keyword": "...", "match_type": "NEGATIVE PHRASE|NEGATIVE EXACT", "scope": "campaign_name veya 'account-level'", "reason": "..."}
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
    """Modelin cevabindan ilk JSON blogunu cikar. Bozuk JSON'u json_repair ile duzelt."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # ilk { den son } a
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    # once standart parse dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # bozuk JSON - json_repair kutuphanesi ile duzelt
        try:
            import json_repair
            fixed = json_repair.loads(text)
            if isinstance(fixed, dict):
                return fixed
            raise ValueError("json_repair sonucu dict degil")
        except Exception as e:
            # Son care: kismi parse
            raise ValueError(f"JSON parse edilemedi (json_repair de basaramadi): {e}")


WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
}


def _call_sonnet(user_msg, extra_note=""):
    """Tek bir Sonnet cagrisi yapar, ham cevabı dondurur."""
    system = SYSTEM_PROMPT + (extra_note or "")
    resp = client().messages.create(
        model=config.STRATEGY_MODEL,
        max_tokens=config.MAX_STRATEGY_TOKENS,
        system=system,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": user_msg}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    text = "\n".join(parts).strip()
    used_web = any(getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")
                   for b in resp.content)
    return text, used_web, resp.usage


def generate_strategy(payload):
    """Sonnet'ten strateji uret. Retry + json_repair fallback. Return: dict."""
    user_msg = ("Amazon PPC verisi ve deterministik onerilerim asagida. "
                "Sistem talimatindaki JSON semasina UYGUN sekilde strateji uret. "
                "JSON syntax'i MUTLAKA gecerli olsun - string icinde \" karakteri "
                "kullaniyorsan \\\" ile escape et, virgul ve parantez dengesine dikkat et.\n\n"
                f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")

    total_in = 0
    total_out = 0
    used_web = False
    for attempt in range(2):  # ilk deneme + 1 retry
        try:
            extra_note = ""
            if attempt > 0:
                extra_note = ("\n\nONEMLI: Onceki denemede JSON parse hatasi oldu. "
                              "Bu sefer DAHA KISA ve KESIN JSON uret, syntax kurallarina "
                              "cok dikkat et. Uzun stringlerde escape hatasi yapma.")
            text, web, usage = _call_sonnet(user_msg, extra_note)
            total_in += usage.input_tokens
            total_out += usage.output_tokens
            used_web = used_web or web
            data = _extract_json(text)
            data["_meta"] = {
                "model": config.STRATEGY_MODEL,
                "web_search_used": used_web,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "attempts": attempt + 1,
            }
            return data
        except Exception as e:
            if attempt == 1:
                # Son deneme de basarisiz - hata dondur
                return {
                    "error": f"AI cikti parse edilemedi ({attempt+1} denemede): {e}",
                    "raw_output": text[:2000] if 'text' in locals() else "",
                    "web_search_used": used_web,
                    "_meta": {"model": config.STRATEGY_MODEL,
                              "input_tokens": total_in,
                              "output_tokens": total_out,
                              "attempts": attempt + 1},
                }
            # ilk deneme basarisiz - loga yaz, tekrar dene
            continue
