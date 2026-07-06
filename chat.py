"""AI Chat - marka context'ini kullanarak soru cevap.

Kullanici uzman Amazon'cuya sorar gibi konusur. AI marka verisini biliyor.
"""
from anthropic import Anthropic
import config
from expert_knowledge import EXPERT_KNOWLEDGE, PRO_INSTRUCTION

_client = None


def client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


CHAT_SYSTEM = EXPERT_KNOWLEDGE + "\n\n" + PRO_INSTRUCTION + "\n\n" + """Sen kidemli bir Amazon PPC uzmanisin. Kullaniciyla Turkce konusuyorsun.
Marka verisi ve son metrikler her mesajda sana veriliyor - o veriye referansla
somut, sayilarla desteklenmis cevaplar ver.

Kurallar:
- Kisa ve net ol. Maddeleyerek yaz.
- Emin degilsen "veri yetersiz, sunu daha yakindan incelemek lazim" de.
- Onerdigin bid/butce degerlerinde HER ZAMAN gerekce ver.
- Amazon Ads politika ihlali icerecek bir sey sorulursa reddet.
- Kullanici somut aksiyona hazirsa "Bunu yapmak icin: 1) ... 2) ..." formati kullan.
- Formul kullanacaksan formul + sayilari goster.
"""


def data_summary(brand, search_terms, targets, campaigns):
    """Kullaniciya gosterilecek 'elimdeki veri' ozeti."""
    total_spend = sum(t.get("spend", 0) for t in targets) or sum(t.get("spend", 0) for t in search_terms)
    total_sales = sum(t.get("sales", 0) for t in targets) or sum(t.get("sales", 0) for t in search_terms)
    return {
        "search_terms": len(search_terms),
        "targets": len(targets),
        "campaigns": len(campaigns),
        "total_spend": round(total_spend, 2),
        "total_sales": round(total_sales, 2),
        "acos_pct": round(total_spend / total_sales * 100, 1) if total_sales else None,
    }


def _brand_context(brand, search_terms, targets, campaigns, placements=None):
    total_spend = sum(t.get("spend", 0) for t in targets)
    total_sales = sum(t.get("sales", 0) for t in targets)
    total_orders = sum(t.get("orders", 0) for t in targets)
    total_clicks = sum(t.get("clicks", 0) for t in targets)
    total_imps = sum(t.get("impressions", 0) for t in targets)
    acos = f"%{total_spend/total_sales*100:.1f}" if total_sales else "N/A"
    roas = f"{total_sales/total_spend:.2f}x" if total_spend else "N/A"
    cvr = f"%{total_orders/total_clicks*100:.2f}" if total_clicks else "N/A"
    ctr = f"%{total_clicks/total_imps*100:.2f}" if total_imps else "N/A"
    cpc = f"${total_spend/total_clicks:.2f}" if total_clicks else "N/A"
    aov = f"${total_sales/total_orders:.2f}" if total_orders else "N/A"

    top_camps = sorted(campaigns, key=lambda c: -c.get("spend", 0))[:8]
    top_terms = sorted(search_terms, key=lambda t: -t.get("spend", 0))[:15]
    top_targets = sorted(targets, key=lambda t: -t.get("spend", 0))[:15]
    top_selling_terms = sorted(search_terms, key=lambda t: -t.get("sales", 0))[:10]

    # Match type dagilimi
    from collections import Counter
    match_dist = Counter(t.get("match_type", "?") for t in targets)

    lines = [
        f"MARKA: {brand['name']}",
        f"Hedef ACOS: %{brand['target_acos']*100:.0f}",
    ]
    if brand.get("sell_price"):
        lines.append(f"Urun fiyati: ${brand['sell_price']}, COGS: ${brand.get('cogs',0)}")
    lines += [
        "",
        "=== VERI OZET ===",
        f"Toplam harcama: ${total_spend:.2f} · Satis: ${total_sales:.2f} · Siparis: {int(total_orders)}",
        f"ACOS: {acos} · RoAS: {roas} · CVR: {cvr} · CTR: {ctr} · Ort.CPC: {cpc} · AOV: {aov}",
        f"Impression: {int(total_imps):,} · Tiklama: {int(total_clicks):,}",
        f"Kampanya: {len(campaigns)} · Hedef: {len(targets)} · Arama terimi: {len(search_terms)}",
        f"Match dagilimi: {dict(match_dist)}",
        "",
        "=== EN YUKSEK HARCAMALI 8 KAMPANYA ===",
    ]
    for c in top_camps:
        s = c.get("sales", 0)
        a = f"%{c['spend']/s*100:.1f}" if s else "satis yok"
        lines.append(f"- {c['campaign']}: ${c['spend']:.2f} harcama, {int(c.get('orders',0))} sip, ACOS {a}")
    lines.append("")
    lines.append("=== EN COK HARCAYAN 15 ARAMA TERIMI (musteri ne yazdi) ===")
    for t in top_terms:
        s = t.get("sales", 0)
        a = f"%{t['spend']/s*100:.1f}" if s else "satis yok"
        lines.append(f"- '{t['term']}' ({t.get('match_type','?')}): "
                     f"${t['spend']:.2f}, {int(t.get('orders',0))} sip, ACOS {a}")
    lines.append("")
    lines.append("=== EN COK SATAN 10 ARAMA TERIMI ===")
    for t in top_selling_terms:
        s = t.get("sales", 0)
        if s <= 0: continue
        lines.append(f"- '{t['term']}': ${s:.2f} satis, {int(t.get('orders',0))} sip, "
                     f"${t.get('spend',0):.2f} harcama")
    lines.append("")
    lines.append("=== EN COK HARCAYAN 15 HEDEF (bid uygulanabilen) ===")
    for t in top_targets:
        s = t.get("sales", 0)
        a = f"%{t['spend']/s*100:.1f}" if s else "satis yok"
        tos = t.get("tos_is", 0)
        tos_str = f" TOS IS %{tos*100:.0f}" if tos else ""
        lines.append(f"- '{t.get('targeting','?')}' ({t.get('match_type','?')}): "
                     f"${t['spend']:.2f}, {int(t.get('orders',0))} sip, ACOS {a}, CPC ${t.get('cpc',0):.2f}{tos_str}")
    if placements:
        lines.append("")
        lines.append("=== YER BAZLI HARCAMA (Placement) ===")
        for p in sorted(placements, key=lambda x: -x.get("spend", 0))[:8]:
            s = p.get("sales", 0)
            a = f"%{p['spend']/s*100:.1f}" if s else "satis yok"
            lines.append(f"- {p['campaign']} @ {p['placement']}: ${p['spend']:.2f}, ACOS {a}")
    return "\n".join(lines)


def reply(brand, search_terms, targets, campaigns, history, user_msg,
          placements=None):
    """Chat cevabi uret."""
    ctx = _brand_context(brand, search_terms, targets, campaigns, placements)
    system = CHAT_SYSTEM + "\n\nBu markaya ait guncel veri (asagida): kullanicinin sordugu her seye referansla bu veriyi kullan. 'Elimde su kadar veri var' de, ozel isimler ver.\n\n" + ctx

    messages = []
    for m in history[-30:]:
        if m["role"] in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_msg})

    resp = client().messages.create(
        model=config.STRATEGY_MODEL,
        max_tokens=1500,
        system=system,
        messages=messages,
    )
    return "\n".join(b.text for b in resp.content
                     if getattr(b, "type", "") == "text").strip()
