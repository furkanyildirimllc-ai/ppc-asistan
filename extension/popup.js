let API = "http://localhost:8642";

const $ = (id) => document.getElementById(id);
const setStatus = (t) => { $("status-text").textContent = t; };

let currentStep = 1;
let scrapedData = null;
let selectedCompetitors = [];
let searchSuggestions = [];
let lastPlan = null;
let bidStrategy = "profit";   // profit | balanced | aggressive

// --- STATE PERSISTENCE ---
// Chrome popup'i disariya tiklayinca / sayfayi kaydirinca kapanir ve DOM ile
// tum JS degiskenleri sifirlanir. Bunu engellemek mumkun degil; bu yuzden her
// degisiklikte durumu chrome.storage'a yazip acilista geri yukluyoruz.
const FORM_FIELDS = ["f-title", "f-asin", "f-price", "f-sku", "f-brand", "f-cogs", "f-fba"];
let restoring = false;

function saveState() {
  if (restoring) return;
  const form = {};
  FORM_FIELDS.forEach(id => { const el = $(id); if (el) form[id] = el.value; });
  try {
    chrome.storage.local.set({
      ppc_state: {
        currentStep, form, scrapedData, selectedCompetitors,
        searchSuggestions, lastPlan, bidStrategy,
      }
    });
  } catch (_) {}
}

async function restoreState() {
  let s;
  try { s = (await chrome.storage.local.get("ppc_state")).ppc_state; } catch (_) { return false; }
  if (!s) return false;
  restoring = true;
  try {
    FORM_FIELDS.forEach(id => {
      const el = $(id);
      if (el && s.form && s.form[id] != null) el.value = s.form[id];
    });
    scrapedData = s.scrapedData || null;
    selectedCompetitors = s.selectedCompetitors || [];
    searchSuggestions = s.searchSuggestions || [];
    lastPlan = s.lastPlan || null;
    if (s.bidStrategy) {
      bidStrategy = s.bidStrategy;
      document.querySelectorAll(".strat-btn").forEach(x =>
        x.classList.toggle("active", x.dataset.strategy === bidStrategy));
    }
    if (scrapedData) {
      if (scrapedData.kind === "product") updateIndicators(scrapedData);
      setStatus("Kaldığın yerden ✓");
    }
    if (lastPlan) renderPlan(lastPlan);
  } finally {
    restoring = false;
  }
  // renderPlan step 4 panelini doldurur; kullaniciyi birakip gittigi adima don.
  if (s.currentStep && s.currentStep > 1) goToStep(s.currentStep);
  return true;
}

// --- STEP NAVIGATION ---
function goToStep(n) {
  document.querySelectorAll('.step-panel').forEach(p => p.classList.remove('active'));
  $(`step-${n}`).classList.add('active');
  
  document.querySelectorAll('.step-dot').forEach((d, i) => {
    d.classList.remove('active', 'done');
    if (i + 1 < n) d.classList.add('done');
    else if (i + 1 === n) d.classList.add('active');
  });
  currentStep = n;

  if (n === 2) renderCompetitors();
  if (n === 3) discoverKeywords();
  saveState();
}

// Make step dots clickable
document.addEventListener("DOMContentLoaded", () => {
  [1, 2, 3, 4, 5].forEach(n => {
    const dot = $(`dot-${n}`);
    if (dot) dot.addEventListener("click", () => goToStep(n));
  });
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// --- STEP 1: SCAN ---
function updateIndicators(d) {
  const inds = $("product-indicators");
  inds.style.display = "block";
  
  const aplus = $("ind-aplus");
  if (d.listing_quality?.has_aplus) { aplus.className = "indicator i-ok"; aplus.textContent = "✓ A+ İçerik"; }
  else { aplus.className = "indicator i-warn"; aplus.textContent = "⚠ A+ Yok"; }

  const imgs = $("ind-imgs");
  const c = d.listing_quality?.image_count || 0;
  imgs.className = c >= 5 ? "indicator i-ok" : "indicator i-warn";
  imgs.textContent = `📸 ${c} Görsel`;

  const rat = $("ind-rating");
  rat.className = d.rating >= 4.0 ? "indicator i-ok" : "indicator i-danger";
  rat.textContent = `⭐ ${d.rating || 0.0}`;
}

function fillForm(d) {
  $("f-title").value = d.title || "";
  $("f-asin").value = d.asin || "";
  $("f-price").value = d.price != null ? d.price : "";
  $("f-brand").value = d.brand || "";
  if (d.kind === 'product') updateIndicators(d);
  
  // Auto-estimate FBA fee if price is available
  if (d.price && d.price > 0) {
    const p = d.price;
    // Standard FBA fee estimation: referral (15%) + fulfillment ($3.22-$6.10 based on price tier)
    const fulfillment = p < 10 ? 3.22 : p < 25 ? 3.86 : p < 50 ? 5.26 : 6.10;
    if (!$("f-fba").value) $("f-fba").value = fulfillment.toFixed(2);
    // COGS rough estimate: ~25% of price if not set
    if (!$("f-cogs").value) $("f-cogs").value = (p * 0.25).toFixed(2);
  }
}

async function rescan() {
  setStatus("Okunuyor...");
  try {
    const tab = await activeTab();
    if (!tab || !tab.id) { setStatus("Sekme bulunamadı"); return; }
    
    let res = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE" }).catch(() => null);
    if (!res && chrome.scripting) {
      // Fallback: Programmatically inject content.js if missing
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"]
      }).catch(() => null);
      res = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE" }).catch(() => null);
    }
    
    if (!res || res.kind === "none") {
      setStatus("Sayfa okunamadı");
      $("f-title").placeholder = "Lütfen bir Amazon ürün veya arama sayfası açın.";
      return;
    }
    scrapedData = res;
    selectedCompetitors = [...(res.competitors || [])];
    fillForm(res);
    setStatus("Hazır ✓");
    saveState();
  } catch (e) {
    setStatus("Hata oluştu");
    console.error(e);
  }
}

// --- STEP 2: COMPETITORS ---
function renderStarRating(rating) {
  let stars = '';
  for(let i=1; i<=5; i++) {
    stars += i <= Math.round(rating) ? '★' : '☆';
  }
  return `<span class="star-rating">${stars}</span> <span style="color:var(--fg)">${rating}</span>`;
}

function scoreCompetitor(comp, ownPrice) {
  let score = 50;
  let reasons = [];
  const price = comp.price || 0;
  const rating = comp.rating || 0;
  const reviews = comp.review_count || 0;
  
  if (ownPrice > 0 && price > 0) {
    if (price > ownPrice * 1.2) { score += 20; reasons.push('Pahalı'); }
    else if (price < ownPrice * 0.8) { score -= 15; reasons.push('Ucuz'); }
  }
  if (rating > 0 && rating < 4.0) { score += 25; reasons.push('Düşük puan'); }
  else if (rating >= 4.5) { score -= 10; }
  if (reviews < 50) { score += 15; reasons.push('Az yorum'); }
  else if (reviews > 500) { score -= 20; reasons.push('Güçlü'); }

  // Kesifle gelen sinyal: cok kelimede ust siralarda cikan urun gercek rakiptir,
  // kolay hedef degildir. Tek kelimede goruluyorsa nis/tesadufi olabilir.
  const overlap = comp.keyword_overlap || 0;
  if (overlap >= 3) { score -= 15; reasons.push(`${overlap} kelimede rakip`); }
  else if (overlap === 1) { score += 5; }
  if (comp.avg_rank && comp.avg_rank <= 5) { score -= 10; reasons.push('İlk sıralarda'); }
  
  score = Math.max(0, Math.min(100, score));
  return { score, reasons, isWeak: score >= 65, isStrong: score <= 35 };
}

function renderCompetitors() {
  const container = $("competitors-list");
  if (!selectedCompetitors.length) {
    container.innerHTML = '<div class="muted">Rakip bulunamadı. Lütfen manuel ekleyin.</div>';
    $("comp-count-title").textContent = "0 seçildi";
    return;
  }
  
  const ownPrice = parseFloat($("f-price").value) || 0;
  selectedCompetitors.forEach(c => {
    c.intel = scoreCompetitor(c, ownPrice);
  });
  selectedCompetitors.sort((a, b) => b.intel.score - a.intel.score);
  
  let html = '';
  let checkedCount = 0;
  let weakCount = 0;
  let strongCount = 0;
  
  selectedCompetitors.forEach(c => {
    if (c.intel.isWeak) weakCount++;
    if (c.intel.isStrong) strongCount++;
  });
  
  html += `<div class="comp-summary">🎯 ${weakCount} kolay hedef, ⚠️ ${strongCount} güçlü rakip bulundu</div>`;
  
  selectedCompetitors.forEach((c, i) => {
    const cls = c.intel.isStrong ? 'strong' : (c.intel.isWeak ? 'weak' : '');
    const checked = c.selected !== false;
    if (checked) checkedCount++;
    
    let badges = '';
    if (c.intel.isWeak) badges += '<span class="comp-badge weak">🎯 Kolay Hedef</span>';
    if (c.intel.isStrong) badges += '<span class="comp-badge strong">⚠️ Güçlü Rakip</span>';
    // Kesif sinyali: kac ana kelimede karsina cikti, ortalama kacinci sirada
    if (c.keyword_overlap) {
      const t = (c.seen_for || []).join(", ");
      badges += `<span class="comp-badge overlap" title="${t}">🔁 ${c.keyword_overlap} kelimede` +
                (c.avg_rank ? ` · ort. ${c.avg_rank}. sıra` : "") + `</span>`;
    }
    
    // Gorsel her zaman bir yer tutucunun UZERINE binir. Boylece gorsel yoksa
    // ya da yuklenemezse kirik ikon degil, duzgun bir kutu gorunur.
    const imgHtml = `
      <div class="comp-thumb">
        <span class="comp-thumb-ph">📦</span>
        ${c.image ? `<img data-thumb src="${c.image}" alt="">` : ""}
      </div>`;
    
    html += `
      <div class="comp-card ${cls}">
        <input type="checkbox" id="comp-${i}" data-comp-idx="${i}" ${checked ? 'checked' : ''}>
        ${imgHtml}
        <div class="comp-info">
          <div class="comp-title" title="${c.title}">${c.title}</div>
          <div class="comp-meta">
            <span>${c.asin}</span>
            <span>$${c.price || '?'}</span>
            ${renderStarRating(c.rating || 0)}
            <span>(${c.review_count || 0} rev)</span>
            ${badges}
          </div>
        </div>
      </div>
    `;
  });
  
  container.innerHTML = html;
  $("comp-count-title").textContent = `${checkedCount} seçildi`;

  // Inline onerror MV3 CSP'sinde calismaz; yuklenemeyen gorseli JS ile gizle
  // ki altindaki yer tutucu ortaya ciksin (kirik ikon gorunmesin).
  container.querySelectorAll("img[data-thumb]").forEach(img => {
    const hide = () => { img.style.display = "none"; };
    img.addEventListener("error", hide);
    if (img.complete && img.naturalWidth === 0) hide();
  });
}

// Inline onchange MV3 CSP'sinde calismaz -> delegasyonla dinle.
$("competitors-list").addEventListener("change", (ev) => {
  const el = ev.target;
  if (!el || el.dataset.compIdx === undefined) return;
  const c = selectedCompetitors[Number(el.dataset.compIdx)];
  if (!c) return;
  c.selected = el.checked;
  const count = selectedCompetitors.filter(x => x.selected !== false).length;
  $("comp-count-title").textContent = `${count} seçildi`;
  saveState();
});

// Rakipleri urunun ana kelimelerinde arama yaparak kesfeder.
async function discoverCompetitors() {
  const btn = $("btn-discover");
  const status = $("discover-status");
  const title = $("f-title").value.trim();
  if (!title) { setStatus("Önce ürün başlığı gerekli"); return; }

  btn.disabled = true;
  btn.textContent = "🔍 Aranıyor...";
  status.style.display = "block";
  status.textContent = "Ana kelimeler çıkarılıyor, Amazon'da aranıyor...";

  try {
    const tab = await activeTab();
    if (!tab || !tab.id) throw new Error("Sekme bulunamadı");
    const res = await chrome.tabs.sendMessage(tab.id, {
      type: "DISCOVER_COMPETITORS",
      title,
      asin: $("f-asin").value.trim().toUpperCase(),
      keywords: searchSuggestions.slice(0, 2),
    }).catch(() => null);

    if (!res || !res.competitors) throw new Error("Tarama yanıt vermedi");
    if (!res.competitors.length) {
      status.textContent = "Rakip bulunamadı. " +
        (res.errors && res.errors.length ? res.errors[0] : "Amazon sayfasında olduğundan emin ol.");
      return;
    }

    // Kesfedilenleri mevcut listeyle birlestir (ASIN'e gore tekille).
    const byAsin = new Map(selectedCompetitors.map(c => [c.asin, c]));
    let added = 0;
    res.competitors.forEach(c => {
      if (byAsin.has(c.asin)) {
        Object.assign(byAsin.get(c.asin), {
          keyword_overlap: c.keyword_overlap, avg_rank: c.avg_rank, seen_for: c.seen_for,
        });
      } else {
        byAsin.set(c.asin, c);
        added++;
      }
    });
    selectedCompetitors = Array.from(byAsin.values());
    renderCompetitors();
    saveState();

    const qs = (res.queries || []).join(", ");
    status.innerHTML = `✅ <b>${added}</b> yeni rakip eklendi (toplam ${selectedCompetitors.length}).` +
      (qs ? `<br/>Aranan kelimeler: ${qs}` : "") +
      (res.errors && res.errors.length ? `<br/>⚠️ ${res.errors.length} arama başarısız.` : "");
  } catch (e) {
    status.textContent = "Tarama hatası: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "🔍 Rakipleri Otomatik Tara";
  }
}

$("btn-discover").addEventListener("click", discoverCompetitors);

$("btn-add-comp").addEventListener("click", () => {
  const v = $("f-manual-asin").value.trim().toUpperCase();
  if (v && v.length >= 10) {
    selectedCompetitors.push({ asin: v, title: "Manuel Eklenen Rakip", price: null, rating: 0, review_count: 0 });
    $("f-manual-asin").value = "";
    renderCompetitors();
    saveState();
  }
});

// --- STEP 3: KEYWORDS ---
async function discoverKeywords() {
  const container = $("keywords-container");
  const loading = $("keyword-loading");
  container.style.display = 'none';
  loading.style.display = 'block';
  
  try {
    const tab = await activeTab();
    const title = $("f-title").value || (scrapedData ? scrapedData.title : "");
    const res = await chrome.tabs.sendMessage(tab.id, { type: "FETCH_SUGGESTIONS", keyword: title }).catch(() => null);
    
    let kws = (res && res.suggestions) ? res.suggestions : [];
    
    // Add words from competitor titles as fallback if empty
    if (!kws.length && selectedCompetitors.length) {
      // Tek tek kelime dokmek yerine rakip basliklarindan anlamli ikili/uclu
      // obekler cikar. Noktalama ve stop-word SINIR olur; yoksa
      // "shampoo for thin, fine hair" -> "shampoo thin" gibi sahte terim uretir.
      const STOP = new Set(['for','with','and','the','of','to','in','on','by','from','your','our','plus','pack','set','count']);
      const freq = new Map();
      selectedCompetitors.forEach(c => {
        (c.title || '').toLowerCase()
          .replace(/[^a-z0-9\s,;:/()\-]/g, ' ')
          .split(/[,;:/()]|\s-\s/)
          .forEach(seg => {
            const w = seg.split(/\s+/).filter(x => x.length > 2 && !STOP.has(x));
            for (let n = 2; n <= 3; n++) {
              for (let i = 0; i + n <= w.length; i++) {
                const g = w.slice(i, i + n).join(' ');
                freq.set(g, (freq.get(g) || 0) + 1);
              }
            }
          });
      });
      kws = [...freq.entries()].sort((a, b) => b[1] - a[1]).map(e => e[0]).slice(0, 20);
    }
    
    // STRICT RELEVANCE FILTER
    const ownTokens = new Set(title.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(w => w.length > 2));
    const stopWords = new Set(['the','and','for','with','set','pack','size','new','best','top','sale','prime','men','women','kids','pack','pcs','oz','ml','gram','kg','large','small','medium','black','white','blue','red']);
    const cleanOwnTokens = new Set([...ownTokens].filter(w => !stopWords.has(w)));
    
    if (cleanOwnTokens.size > 0 && kws.length > 0) {
      kws = kws.filter(kw => {
        const kwWords = kw.toLowerCase().split(/\s+/);
        return kwWords.some(w => cleanOwnTokens.has(w));
      });
    }
    
    if (kws.length) {
      let html = '';
      kws.forEach((k, i) => {
        let cls = i < 3 ? 'high' : (i < 8 ? 'med' : 'low');
        html += `<span class="chip ${cls}">${k}</span>`;
      });
      container.innerHTML = html;
    } else {
      container.innerHTML = '<div class="muted">Ürününüzle doğrudan alakalı kelime süzüldü. AI doğrudan başlık üzerinden analiz yapacak.</div>';
    }
  } catch (e) {
    container.innerHTML = '<div class="muted">Bağlantı hatası.</div>';
  }
  
  loading.style.display = 'none';
  container.style.display = 'block';
}

// Zaman asimi olmayan fetch, sunucu dusunce sonsuza kadar bekler ve arayuz
// "uretiliyor" ekraninda kilitlenir. Her istek bir sureye baglanir.
let activeAbort = null;   // kullanici iptal edebilsin diye disari acilir

async function fetchWithTimeout(url, opts, ms, onTick) {
  const ctrl = new AbortController();
  activeAbort = ctrl;
  const started = Date.now();
  const tick = onTick && setInterval(
    () => onTick(Math.round((Date.now() - started) / 1000)), 1000);
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error(`Sunucu ${Math.round(ms / 1000)} saniyede yanıt vermedi. ` +
                      `Sunucunun çalıştığını kontrol et (${API}).`);
    }
    throw new Error(`Sunucuya ulaşılamadı (${API}). Çalışıyor mu?`);
  } finally {
    clearTimeout(timer);
    if (tick) clearInterval(tick);
    activeAbort = null;
  }
}

// Sifirlama: takilan bir istek, bozuk kayitli durum ya da yanlis urun
// verisiyle ugrasmak yerine temiz baslamak icin tek dugme.
async function resetAll() {
  if (activeAbort) { try { activeAbort.abort(); } catch (_) {} }
  try { await chrome.storage.local.remove("ppc_state"); } catch (_) {}
  scrapedData = null;
  selectedCompetitors = [];
  searchSuggestions = [];
  lastPlan = null;
  bidStrategy = "profit";
  document.querySelectorAll(".strat-btn").forEach(x =>
    x.classList.toggle("active", x.dataset.strategy === "profit"));
  FORM_FIELDS.forEach(id => { const el = $(id); if (el) el.value = ""; });
  const pc = $("plan-content"); if (pc) pc.innerHTML = "";
  $("plan-view").style.display = "none";
  $("loading-view").style.display = "none";
  const ds = $("discover-status"); if (ds) { ds.style.display = "none"; ds.textContent = ""; }
  const cl = $("competitors-list"); if (cl) cl.innerHTML = "";
  goToStep(1);
  setStatus("Sıfırlandı, yeniden taranıyor...");
  await rescan();
}

// Sunucu secimi: elle URL yazmak yerine tek tik. Secilen adres kaydedilir ve
// canli olup olmadigi aninda test edilir.
const API_PRESETS = {
  local: "http://localhost:8642",
  cloud: "https://ppc-asistan.onrender.com",
};

async function setApi(url) {
  API = url;
  if ($("f-api-url")) $("f-api-url").value = url;
  try { await chrome.storage.local.set({ ppc_api_url: url }); } catch (_) {}
  const st = $("api-status");
  if (st) st.textContent = "Bağlantı test ediliyor...";
  try {
    // Canli sunucu uykudan kalkarken yavas olabilir, bol sure ver.
    const r = await fetchWithTimeout(url + "/", { method: "GET" }, 90000);
    if (st) st.textContent = r.ok ? `✅ Bağlandı: ${url}` : `⚠️ Yanıt ${r.status}: ${url}`;
  } catch (e) {
    if (st) st.textContent = `❌ Ulaşılamadı: ${url}`;
  }
}

if ($("btn-api-local")) $("btn-api-local").addEventListener("click", () => setApi(API_PRESETS.local));
if ($("btn-api-cloud")) $("btn-api-cloud").addEventListener("click", () => setApi(API_PRESETS.cloud));

if ($("btn-reset")) {
  $("btn-reset").addEventListener("click", resetAll);
}

if ($("btn-cancel-analyze")) {
  $("btn-cancel-analyze").addEventListener("click", () => {
    if (activeAbort) activeAbort.abort();
    goToStep(3);
  });
}

// FastAPI 422'de detail bir nesne listesidir; duz string'e cevrilmezse
// mesaj "[object Object]" olarak gorunur.
async function errText(r) {
  let d;
  try { d = (await r.json()).detail; } catch (_) { return `Sunucu ${r.status}`; }
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map(e => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join(" | ");
  }
  return d ? JSON.stringify(d) : `Sunucu ${r.status}`;
}

// --- STEP 4: ANALYSIS ---
function collectData() {
  return {
    title: $("f-title").value.trim(),
    asin: $("f-asin").value.trim().toUpperCase(),
    sku: $("f-sku").value.trim(),
    price: parseFloat($("f-price").value) || null,
    brand: $("f-brand").value.trim(),
    cogs: parseFloat($("f-cogs").value) || null,
    fba_fee: parseFloat($("f-fba").value) || null,
    competitors: selectedCompetitors.filter(c => c.selected !== false),
    use_ai: true,
    bid_strategy: bidStrategy,
  };
}

// Strateji secici
$("strategy-picker").addEventListener("click", (ev) => {
  const b = ev.target.closest(".strat-btn");
  if (!b || b.dataset.strategy === bidStrategy) return;
  bidStrategy = b.dataset.strategy;
  document.querySelectorAll(".strat-btn").forEach(x => x.classList.remove("active"));
  b.classList.add("active");

  // KRITIK: indirme, kayitli plandaki bid'leri oldugu gibi kullanir. Strateji
  // degistirip yeniden analiz etmezsen ESKI bid'lerle dosya inerdi - sessizce
  // yanlis dosya. Bu yuzden plan gecersiz kilinir.
  if (lastPlan) {
    lastPlan = null;
    const pc = $("plan-content");
    if (pc) pc.innerHTML = `<div class="feas tight"><b>⚠️ Strateji değişti.</b>
      Bid'ler yeniden hesaplanmalı — "AI Analizi Başlat" ile planı yenile,
      yoksa indirilen dosya eski bid'leri taşır.</div>`;
    $("plan-view").style.display = "block";
    setStatus("Strateji değişti, yeniden analiz gerekli");
  }
  saveState();
});

function renderOutlook(o) {
  if (!o || !o.per_match) return "";
  const order = ["exact", "phrase", "broad", "auto", "pt"];
  const label = { exact: "Exact", phrase: "Phrase", broad: "Broad", auto: "Auto", pt: "ASIN" };
  const rows = order.filter(k => o.per_match[k]).map(k => {
    const r = o.per_match[k];
    const dot = r.impression_odds === "iyi" ? "🟢" : r.impression_odds === "orta" ? "🟡" : "🔴";
    const acosColor = r.profitable === false ? "var(--danger)" : "var(--ok)";
    return `<tr>
      <td>${label[k]}</td>
      <td><b>$${r.bid}</b></td>
      <td style="color:${acosColor}">%${r.expected_acos_pct}</td>
      <td>${dot} %${r.vs_market_pct}</td>
    </tr>`;
  }).join("");
  return `
    <div class="card" style="margin-top:12px;">
      <div class="tag">🎯 Bu Bid'lerle Ne Olur?</div>
      <table class="outlook">
        <tr><th>Tip</th><th>Bid</th><th>Tahmini ACOS</th><th>Pazarın %'si</th></tr>
        ${rows}
      </table>
      <div class="muted" style="margin-top:6px; font-size:10px;">
        Break-even ACOS %${o.break_even_acos_pct} · Pazar CPC tahmini $${o.market_cpc_estimate}.
        🟢 gösterim alır · 🟡 sınırda · 🔴 muhtemelen gösterim almaz.
      </div>
    </div>`;
}

function renderFeasibility(f) {
  if (!f || !f.headline) return "";
  const icon = f.status === "ok" ? "✅" : f.status === "tight" ? "⚠️" : "🚫";
  const tips = (f.advice || []).map(a => `<li>${a}</li>`).join("");
  return `
    <div class="feas ${f.status}">
      <b>${icon} ${f.headline}</b>
      <div class="feas-nums">
        <span>Ödenebilir bid: <b>$${f.affordable_bid}</b></span>
        <span>Pazar CPC (tahmini): <b>$${f.market_cpc_estimate}</b></span>
        <span>Karşılama: <b>%${f.ratio_pct}</b></span>
      </div>
      ${tips ? `<ul>${tips}</ul>` : ""}
      <div class="muted" style="margin-top:5px; font-size:10px;">${f.note || ""}</div>
    </div>`;
}

async function analyze() {
  const body = collectData();
  if (!body.title) { setStatus("Başlık gerekli!"); return; }
  
  goToStep(4);
  $("loading-view").style.display = "flex";
  $("plan-view").style.display = "none";
  
  try {
    const r = await fetchWithTimeout(`${API}/api/launch/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, 240000, (sec) => {
      const el = $("loading-timer");
      if (el) el.textContent = `Geçen süre: ${sec} sn` +
        (sec > 90 ? " — AI analizi normalde 40-90 sn sürer." : "");
    });
    if (!r.ok) throw new Error(await errText(r));
    lastPlan = await r.json();
    renderPlan(lastPlan);
    saveState();
  } catch (e) {
    $("plan-content").innerHTML = `<div class="expert-note" style="border-color:var(--danger)">Backend hatası: ${e}. Lütfen lokal sunucunun (port 8642) çalıştığından emin olun.</div>`;
    $("loading-view").style.display = "none";
    $("plan-view").style.display = "block";
  }
}

function renderPlan(plan) {
  const camps = (plan.campaigns || []).map((c) => `
    <div class="camp-card">
      <b>${c.name}</b><br/>
      <div class="muted" style="margin-top:4px;">
        ${c.targeting_type} · Bütçe: $${c.budget}/gün · Bid: $${c.default_bid}<br/>
        ${c.keywords && c.keywords.length ? `🎯 ${c.keywords.length} Kelime ` : ""}
        ${c.product_targets && c.product_targets.length ? `🎯 ${c.product_targets.length} Rakip ASIN ` : ""}
        ${c.auto_groups ? "⚡ 4 Auto Grup" : ""}
      </div>
    </div>`).join("");
    
  const rationaleHtml = plan.rationale ? `
    <div class="expert-note"><b>💡 Strateji Özeti:</b> ${plan.rationale}</div>
  ` : "";

  // Economics Card
  const econ = plan.economics;
  const econHtml = econ ? `
    <div class="card" style="margin-top:12px;">
      <div class="tag">💰 Karlılık & Break-Even</div>
      <div style="margin-top:4px; font-size:12px;">
        Birim Kar: <b>$${econ.unit_profit_before_ads}</b> · 
        Break-Even ACOS: <b style="color:var(--warn)">%${econ.break_even_acos_pct}</b> · 
        Hedef ACOS: <b style="color:var(--ok)">%${econ.recommended_target_acos_pct}</b>
      </div>
    </div>
  ` : "";

  // Competitor Intel Summary
  const cIntel = plan.competitor_intel;
  let compIntelHtml = "";
  if (cIntel && cIntel.weak_targets && cIntel.weak_targets.length > 0) {
    const weakList = cIntel.weak_targets.slice(0, 3).map(w => 
      `<li style="margin-bottom:4px;"><b>${w.asin}</b> (${w.title.slice(0, 35)}...): ${w.reason}</li>`
    ).join("");
    compIntelHtml = `
      <div class="card" style="margin-top:12px; border-left: 3px solid var(--ok);">
        <div class="tag" style="color:var(--ok)">🎯 Zayıf Rakip Fırsatları (${cIntel.weak_targets.length} Hedef)</div>
        <div class="muted" style="margin-top:4px;">PPC targeting ile pay çalınabilecek zayıf rakipler:</div>
        <ul style="margin:6px 0 0 16px; padding:0; font-size:11px; color:var(--fg);">${weakList}</ul>
      </div>
    `;
  }

  // Expert Reasoning Details
  const expReason = plan.expert_reasoning;
  let expertReasonHtml = "";
  if (expReason) {
    expertReasonHtml = `
      <div class="card" style="margin-top:12px;">
        <div class="tag">🧠 Profesyonel PPC Uzman Mantığı</div>
        ${expReason.keyword_strategy ? `<div style="margin-top:6px; font-size:11px;"><b>🔑 Keyword Stratejisi:</b> ${expReason.keyword_strategy}</div>` : ''}
        ${expReason.bid_strategy ? `<div style="margin-top:6px; font-size:11px;"><b>💵 Bid Mantığı:</b> ${expReason.bid_strategy}</div>` : ''}
        ${expReason.risk_assessment ? `<div style="margin-top:6px; font-size:11px; color:var(--warn)"><b>⚠️ Risk Analizi:</b> ${expReason.risk_assessment}</div>` : ''}
      </div>
    `;
  }
  
  const timelineHtml = (plan.action_plan && plan.action_plan.length) ? `
    <div class="card" style="margin-top:12px;">
      <div class="tag">📅 Lansman Takvimi & Fazlar</div>
      <div class="timeline" style="margin-top:12px;">
        ${plan.action_plan.map(s => `<div class="tl-item">${s}</div>`).join("")}
      </div>
    </div>
  ` : "";

  $("plan-content").innerHTML = `
    ${renderFeasibility(plan.bid_feasibility)}
    ${renderOutlook(plan.bid_outlook)}
    ${rationaleHtml}
    ${econHtml}
    ${compIntelHtml}
    <div class="card" style="margin-top:12px;">
      <div class="tag">Önerilen Kampanyalar (Toplam: $${plan.daily_budget_total}/gün)</div>
      ${camps}
    </div>
    ${expertReasonHtml}
    ${timelineHtml}
  `;
  
  $("loading-view").style.display = "none";
  $("plan-view").style.display = "block";
  
  // Prep step 5 data
  $("summary-budget").textContent = `$${plan.daily_budget_total || 0}`;
  $("summary-camps").textContent = (plan.campaigns || []).length;
  
  let kwCount = 0;
  (plan.campaigns || []).forEach(c => {
    kwCount += (c.keywords || []).length + (c.product_targets || []).length;
  });
  $("summary-kws").textContent = kwCount;
}

// --- STEP 5: DOWNLOAD ---
async function downloadBulksheet() {
  const btn = $("btn-dl");
  if (!lastPlan) {
    // Popup yeniden acildiysa bellekteki plan gitmis olur; kayitliyi geri yukle.
    try {
      const s = (await chrome.storage.local.get("ppc_state")).ppc_state;
      if (s && s.lastPlan) lastPlan = s.lastPlan;
    } catch (_) {}
  }
  if (!lastPlan) {
    btn.textContent = "Önce Analiz Et";
    setTimeout(() => { btn.textContent = "⬇️ Bulk Sheet İndir (.xlsx)"; }, 3000);
    return;
  }
  btn.textContent = "Hazırlanıyor...";
  btn.disabled = true;
  
  try {
    const r = await fetchWithTimeout(`${API}/api/launch/bulksheet`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastPlan),
    }, 120000);
    if (!r.ok) throw new Error(await errText(r));
    const blob = await r.blob();
    if (!blob || blob.size === 0) throw new Error("Bos dosya");

    const p = lastPlan.product || {};
    const brand = (p.brand || p.title || "launch")
      .replace(/[^a-z0-9]+/gi, "-").slice(0, 24) || "launch";
    // Strateji dosya adina yazilir: hangi bid seviyesiyle uretildigi sonradan
    // tahmin edilmesin, dosyanin uzerinde yazsin.
    const stratTag = { profit: "karli", balanced: "dengeli",
                       aggressive: "pazarpayi" }[lastPlan.bid_strategy] || "";
    const filename = `${brand}-launch${stratTag ? "-" + stratTag : ""}-bulksheet.xlsx`;
    // Chrome, chrome.downloads'a data: URL kabul etmez; blob: URL sart.
    const url = URL.createObjectURL(blob);

    // Anchor birincil yol: saveAs dialogu popup'i kapatmaz, blob URL yasar.
    // chrome.downloads + saveAs:true kullanilirsa popup kapanir, blob revoke olur
    // ve indirme sessizce basarisiz olur.
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    btn.textContent = "✅ İndirildi";
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) {
    btn.textContent = "İndirme Hatası!";
    console.error("Bulksheet indirme hatasi:", e);
  } finally {
    setTimeout(() => { btn.textContent = "⬇️ Bulk Sheet İndir (.xlsx)"; btn.disabled = false; }, 3000);
  }
}

// --- EVENT LISTENERS ---
$("btn-rescan").addEventListener("click", rescan);
$("btn-step-1-next").addEventListener("click", () => goToStep(2));
$("btn-step-2-next").addEventListener("click", () => goToStep(3));
$("btn-analyze").addEventListener("click", analyze);
$("btn-dl").addEventListener("click", downloadBulksheet);

// Adim gecis butonlari: inline onclick MV3 CSP'sinde calismaz, burada baglaniyor.
[1, 2, 3, 4, 5].forEach((n) => {
  const b = $(`btn-goto-${n}`);
  if (b) b.addEventListener("click", () => goToStep(n));
});

if ($("api-settings-toggle")) {
  $("api-settings-toggle").addEventListener("click", () => {
    const p = $("api-settings-panel");
    p.style.display = p.style.display === "none" ? "block" : "none";
  });
}
if ($("btn-save-api")) {
  $("btn-save-api").addEventListener("click", () => {
    const val = $("f-api-url").value.trim();
    if (val) {
      API = val;
      if (typeof chrome !== 'undefined' && chrome.storage) {
        chrome.storage.local.set({ppc_api_url: val});
      }
      $("api-settings-panel").style.display = "none";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  if (typeof chrome !== 'undefined' && chrome.storage) {
    chrome.storage.local.get('ppc_api_url', (stored) => {
      if (stored.ppc_api_url) {
        API = stored.ppc_api_url;
        if ($("f-api-url")) $("f-api-url").value = API;
      }
    });
  }
  // Once kayitli durumu geri yukle; yoksa sayfayi tara. Boylece popup
  // kapanip acildiginda yapilanlar kaybolmaz.
  restoreState().then((restored) => { if (!restored) rescan(); });
});

// Form alanlarindaki her degisiklik aninda saklansin.
FORM_FIELDS.forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("input", saveState);
});
