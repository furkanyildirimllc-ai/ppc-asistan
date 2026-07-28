"""Rekabet analizi ve istihbarat modulu."""
import re
from typing import Dict, List, Any

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

def analyze_competitors(competitors: List[Dict[str, Any]], own_product: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze each competitor and assign weakness scores."""
    weak_targets = []
    strong_competitors = []
    
    total_price = 0
    total_reviews = 0
    valid_prices = 0
    valid_reviews = 0

    own_price = own_product.get('price') or 0

    for comp in competitors:
        price = comp.get('price') or 0
        rating = comp.get('rating') or 0
        reviews = comp.get('review_count') or 0
        title = comp.get('title') or ''
        asin = comp.get('asin') or ''
        
        if price > 0:
            total_price += price
            valid_prices += 1
        if reviews > 0:
            total_reviews += reviews
            valid_reviews += 1

        # Zayiflik skoru hesaplama
        score = 50
        reason = []
        strategy = ""
        threat_level = "moderate"

        # Fiyat karsilastirmasi
        if own_price > 0 and price > 0:
            if price > own_price * 1.15:
                score += 20
                reason.append("Fiyatı bizden yüksek")
            elif price < own_price * 0.85:
                score -= 15
                reason.append("Fiyatı bizden düşük")
        
        # Yorum ve rating karsilastirmasi
        if rating > 0 and rating < 4.0:
            score += 25
            reason.append("Düşük puanlı")
        elif rating >= 4.5:
            score -= 10
            reason.append("Yüksek puanlı")
            
        if reviews < 50:
            score += 15
            reason.append("Az yorumlu")
        elif reviews > 500:
            score -= 20
            reason.append("Çok yorumlu, güçlü")

        if not comp.get('bullets') and not comp.get('description'):
            score += 10
            reason.append("İçeriği zayıf")

        score = max(0, min(100, score))

        if score >= 65:
            strategy = "Agresif hedefle"
            weak_targets.append({
                'asin': asin,
                'title': title,
                'price': price,
                'weakness_score': score,
                'reason': ", ".join(reason) if reason else "Genel zayıflık",
                'strategy': strategy
            })
        elif score <= 35:
            threat_level = "high"
            strong_competitors.append({
                'asin': asin,
                'title': title,
                'threat_level': threat_level,
                'reason': ", ".join(reason) if reason else "Genel güç"
            })
        else:
            threat_level = "moderate"
            strong_competitors.append({
                'asin': asin,
                'title': title,
                'threat_level': threat_level,
                'reason': ", ".join(reason) if reason else "Ortalama rakip"
            })

    avg_price = (total_price / valid_prices) if valid_prices > 0 else 0
    avg_reviews = int(total_reviews / valid_reviews) if valid_reviews > 0 else 0

    price_pos = "at_avg"
    if own_price > 0 and avg_price > 0:
        if own_price > avg_price * 1.1:
            price_pos = "above_avg"
        elif own_price < avg_price * 0.9:
            price_pos = "below_avg"
            
    summary = f"Pazarda {len(competitors)} rakip analiz edildi. "
    if len(weak_targets) > len(strong_competitors):
        summary += "Pazar yeni girişler için uygun, zayıf rakipler çoğunlukta."
    else:
        summary += "Rekabet yoğun, güçlü rakiplere dikkat edilmeli."

    return {
        'weak_targets': sorted(weak_targets, key=lambda x: x['weakness_score'], reverse=True),
        'strong_competitors': strong_competitors,
        'market_summary': summary,
        'avg_price': round(avg_price, 2),
        'avg_reviews': avg_reviews,
        'price_position': price_pos
    }

def reverse_engineer_keywords(own_title: str, competitors: List[Dict[str, Any]], search_suggestions: List[str] = None) -> Dict[str, Any]:
    """Extract keywords from competitor titles, bullets, descriptions."""
    search_suggestions = search_suggestions or []
    search_suggestions_lower = [s.lower() for s in search_suggestions]
    
    kw_sources = {}  # {kw: set_of_asins}
    
    for comp in competitors:
        asin = comp.get('asin') or 'unknown'
        text_parts = [comp.get('title') or ""]
        text_parts.extend(comp.get('bullets') or [])
        text_parts.append(comp.get('description') or "")
        
        full_text = " ".join(text_parts)
        toks = _tokens(full_text)
        
        for n in (1, 2, 3):
            for g in _ngrams(toks, n):
                if g not in kw_sources:
                    kw_sources[g] = set()
                kw_sources[g].add(asin)

    high_priority = []
    medium_priority = []
    niche_opportunities = []
    all_kws = []
    
    for kw, asins in kw_sources.items():
        found_count = len(asins)
        in_autocomplete = kw in search_suggestions_lower
        
        # Intent belirleme
        intent = "research"
        if any(buy_word in kw.split() for buy_word in ['buy', 'cheap', 'price', 'best']):
            intent = "purchase"
        elif any(comp_word in kw.split() for comp_word in ['vs', 'compare', 'review']):
            intent = "comparison"
            
        entry = {
            'keyword': kw,
            'found_in': found_count,
            'sources': list(asins),
            'intent': intent,
            'reason': ''
        }
        
        if found_count >= 3 and in_autocomplete:
            entry['reason'] = "Autocomplete'de var ve çok rakipte bulundu"
            high_priority.append(entry)
            all_kws.append(kw)
        elif found_count >= 2 or in_autocomplete:
            entry['reason'] = "Birden fazla rakipte var veya autocomplete'de"
            medium_priority.append(entry)
            all_kws.append(kw)
        elif found_count == 1 and len(kw.split()) >= 3:
            entry['reason'] = "Spesifik, uzun kuyruklu niş fırsat"
            niche_opportunities.append(entry)
            all_kws.append(kw)
            
    # Siralama (bulunma sayisina ve kelime uzunluguna gore)
    high_priority.sort(key=lambda x: (x['found_in'], len(x['keyword'].split())), reverse=True)
    medium_priority.sort(key=lambda x: (x['found_in'], len(x['keyword'].split())), reverse=True)
    niche_opportunities.sort(key=lambda x: len(x['keyword'].split()), reverse=True)
    
    return {
        'high_priority': high_priority,
        'medium_priority': medium_priority,
        'niche_opportunities': niche_opportunities,
        'all_keywords_ranked': sorted(all_kws, key=lambda k: len(kw_sources.get(k, set())), reverse=True)
    }

def assess_market_opportunity(own_product: Dict[str, Any], competitors: List[Dict[str, Any]], bsr_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Assess overall market opportunity and recommend strategy intensity."""
    score = 50
    aggression = "moderate"
    reasoning = []
    advantages = []
    risks = []
    
    comp_intel = analyze_competitors(competitors, own_product)
    avg_price = comp_intel['avg_price']
    own_price = own_product.get('price') or 0
    
    if len(comp_intel['weak_targets']) > len(comp_intel['strong_competitors']):
        score += 20
        reasoning.append("Zayıf rakip sayısı fazla, kolay hedefler mevcut.")
        advantages.append("Düşük rekabet direnci")
    else:
        score -= 10
        reasoning.append("Pazar doymuş, güçlü rakipler var.")
        risks.append("Yüksek tıklama maliyetleri")
        
    if own_price > 0 and avg_price > 0:
        if own_price < avg_price * 0.9:
            score += 15
            reasoning.append("Fiyat avantajımız var.")
            advantages.append("Rekabetçi fiyatlandırma")
        elif own_price > avg_price * 1.1:
            score -= 10
            reasoning.append("Premium fiyatlıyız, dönüşüm zor olabilir.")
            risks.append("Fiyat dezavantajı nedeniyle düşük dönüşüm oranı")

    score = max(0, min(100, score))
    
    if score >= 70:
        aggression = "aggressive"
    elif score <= 40:
        aggression = "conservative"

    return {
        'opportunity_score': score,
        'recommended_aggression': aggression,
        'reasoning': " ".join(reasoning) if reasoning else "Ortalama piyasa koşulları.",
        'key_advantages': advantages,
        'key_risks': risks,
        'suggested_daily_budget_range': {
            'min': 20.0 if aggression == "conservative" else 30.0,
            'max': 40.0 if aggression == "conservative" else 100.0
        }
    }
