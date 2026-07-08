"""Denetci Ajan - Fable 5 ile strateji ciktisini son kontrolden gecirir.

Girdi: strateji JSON + deterministik onerileri + marka ayarlari
Cikti: {approved: bool, issues: [...], corrected_strategy: {...} | null,
        risk_level: "low|medium|high", summary: "..."}

Uc turdan sonra karar zorla verilir. Cift denetim: hem heuristic hem AI kontrolu.
"""
import json
import re
from anthropic import Anthropic

import config
from expert_knowledge import EXPERT_KNOWLEDGE

_client = None


def client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


SUPERVISOR_PROMPT = EXPERT_KNOWLEDGE + "\n\n" + """Sen Amazon PPC ekibinde HATA TESPIT eden kidemli bir denetleyicisin.
Yukaridaki uzman bilgi bankasi seni tam donatti - pro-seviyesi taktikleri (traffic
sculpting, placement multipliers, brand defense, kampanya yasi, IS sinyalleri) bil ve
onlara aykiri onerileri isaretle.

Bu marka yuksek butce ile calisiyor - senin gorevin: STRATEJI JSON'unda somut
hata olup olmadigini bulmak. Turkce cevap ver.

DENETIM KONTROL LISTESI:
1. MATEMATIK: Onerilen bid'ler mantikli mi? Min $0.15 alti var mi?
   Cok agresif artislar (>+%50) var mi?
2. CAKISMA: Harvest edilen kelime ayni zamanda negatif olarak onerilmis mi?
   Ayni kelime birden fazla farkli bid ile onerilmis mi?
3. POLICY: Marka ihlali riski olan kelime var mi (yasakli terimler, rakip
   marka adi eger yasal degilse)?
4. FORMAT: JSON semasi eksik alan icermiyor mu? Match type'lar dogru mu?
5. MANTIK: Yeni kampanya onerileri gercekten mantikli mi yoksa gereksiz mi?
   Butce dagilimi %100'e mi toplaniyor?
6. VERI YETERSIZ ISE: strateji buna ragmen agresif oneriler verdiyse UYAR.

CIKTI FORMATI: SADECE JSON, baska metin YOK.
{
  "approved": true | false,
  "risk_level": "low" | "medium" | "high",
  "summary": "1-2 cumle ozet",
  "issues": [
    {"severity": "critical|warning|info",
     "location": "strategy'nin hangi kismi (ornek: new_campaigns[2].starting_bid_usd)",
     "problem": "...",
     "fix": "..."}
  ],
  "corrected_strategy": null,
  "safe_to_send_to_user": true | false
}

Onemli:
- Kritik sorun varsa approved=false, safe_to_send_to_user=false.
- Sadece uyari varsa approved=true, safe_to_send_to_user=true ama issues doldur.
- Emin degilsen safe_to_send_to_user=false yap - kullaniciya asla hatali gitmeme.
"""


def _heuristic_checks(strategy, det_recs):
    """AI cagirmadan once temel hatalari yakala - hizli ve ucuz."""
    issues = []

    if not isinstance(strategy, dict):
        return [{"severity": "critical", "location": "root",
                 "problem": "Strateji dict degil", "fix": "Yeniden uret"}]

    if strategy.get("error"):
        return [{"severity": "critical", "location": "root",
                 "problem": f"AI parse hatasi: {strategy['error']}",
                 "fix": "Yeniden uret veya raw_output'u incele"}]

    # 1. Harvest ve negatif cakismasi
    det_harvest = {r["keyword"].lower() for r in det_recs
                   if r["type"] in ("harvest", "harvest_pt")}
    for neg in strategy.get("extra_negatives", []) or []:
        kw = (neg.get("keyword") or "").lower()
        if kw in det_harvest:
            issues.append({
                "severity": "critical",
                "location": f"extra_negatives -> '{kw}'",
                "problem": "Bu kelime harvest onerilmisken negatif olarak da onerildi",
                "fix": "Bu negatifi cikart - kelimeyi kazanan olarak topluyoruz",
            })

    # 2. Yeni kampanya bid'leri
    for i, camp in enumerate(strategy.get("new_campaigns", []) or []):
        bid = camp.get("starting_bid_usd")
        if isinstance(bid, (int, float)):
            if bid < 0.15:
                issues.append({
                    "severity": "critical",
                    "location": f"new_campaigns[{i}].starting_bid_usd",
                    "problem": f"Bid ${bid} minimum $0.15 altinda",
                    "fix": "En az $0.15 yap",
                })
            elif bid > 10:
                issues.append({
                    "severity": "warning",
                    "location": f"new_campaigns[{i}].starting_bid_usd",
                    "problem": f"Bid ${bid} cok yuksek",
                    "fix": "Kategori benchmark'i ile karsilastir",
                })
        budget = camp.get("suggested_daily_budget_usd")
        if isinstance(budget, (int, float)) and budget < 5:
            issues.append({
                "severity": "warning",
                "location": f"new_campaigns[{i}].suggested_daily_budget_usd",
                "problem": f"Gunluk butce ${budget} cok dusuk - kampanya erken tukenir",
                "fix": "En az $10 oner",
            })

    # 3. Butce dagilimi toplami
    dist = (strategy.get("budget_allocation") or {}).get("distribution") or []
    total_pct = sum(d.get("percent", 0) for d in dist if isinstance(d.get("percent"), (int, float)))
    if dist and not (95 <= total_pct <= 105):
        issues.append({
            "severity": "warning",
            "location": "budget_allocation.distribution",
            "problem": f"Butce dagilimi toplami %{total_pct} (100 olmali)",
            "fix": "Yuzdeleri yeniden dagit",
        })

    return issues


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import json_repair
            fixed = json_repair.loads(text)
            if isinstance(fixed, dict):
                return fixed
        except Exception:
            pass
        raise


def review(strategy, det_recs, brand):
    """Denetle. Return: {approved, risk_level, summary, issues, safe_to_send_to_user,
    heuristic_issues, _meta}."""
    heur = _heuristic_checks(strategy, det_recs)

    critical_heur = [i for i in heur if i["severity"] == "critical"]
    if critical_heur:
        # AI'yi bosuna cagirma - kritik hata var, geri gonder
        return {
            "approved": False,
            "risk_level": "high",
            "summary": f"{len(critical_heur)} kritik heuristik hata bulundu",
            "issues": heur,
            "heuristic_issues": heur,
            "safe_to_send_to_user": False,
            "_meta": {"ai_called": False},
        }

    payload = {
        "brand": {"name": brand["name"], "target_acos_pct": round(brand["target_acos"] * 100, 1)},
        "strategy": strategy,
        "deterministic_recommendation_count": len(det_recs),
        "deterministic_types": sorted({r["type"] for r in det_recs}),
        "heuristic_issues_already_found": heur,
    }
    user_msg = ("Asagidaki strateji ciktisini denetle:\n\n```json\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n```")

    resp = client().messages.create(
        model=config.SUPERVISOR_MODEL,
        max_tokens=config.MAX_SUPERVISOR_TOKENS,
        system=SUPERVISOR_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "\n".join(b.text for b in resp.content
                     if getattr(b, "type", "") == "text").strip()
    try:
        review = _extract_json(text)
    except Exception as e:
        return {
            "approved": False,
            "risk_level": "high",
            "summary": f"Denetci ciktisi parse edilemedi: {e}",
            "issues": heur + [{"severity": "critical", "location": "supervisor",
                               "problem": str(e), "fix": "Manuel incele"}],
            "heuristic_issues": heur,
            "safe_to_send_to_user": False,
            "_meta": {"ai_called": True, "raw": text[:1000]},
        }

    # heuristik uyarilari her zaman ekle
    review.setdefault("issues", []).extend(
        i for i in heur if i not in (review.get("issues") or []))
    review["heuristic_issues"] = heur
    review["_meta"] = {
        "ai_called": True,
        "model": config.SUPERVISOR_MODEL,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return review
