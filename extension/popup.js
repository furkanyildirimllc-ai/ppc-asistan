let API = "http://localhost:8642";

const $ = (id) => document.getElementById(id);
const setStatus = (t) => { $("status-text").textContent = t; };

let currentStep = 1;
let scrapedData = null;
let selectedCompetitors = [];
let searchSuggestions = [];
let lastPlan = null;

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
    
    html += `
      <div class="comp-card ${cls}">
        <input type="checkbox" id="comp-${i}" ${checked ? 'checked' : ''} onchange="toggleComp(${i}, this.checked)">
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
}

window.toggleComp = function(index, isChecked) {
  selectedCompetitors[index].selected = isChecked;
  const count = selectedCompetitors.filter(c => c.selected !== false).length;
  $("comp-count-title").textContent = `${count} seçildi`;
};

$("btn-add-comp").addEventListener("click", () => {
  const v = $("f-manual-asin").value.trim().toUpperCase();
  if (v && v.length >= 10) {
    selectedCompetitors.push({ asin: v, title: "Manuel Eklenen Rakip", price: null, rating: 0, review_count: 0 });
    $("f-manual-asin").value = "";
    renderCompetitors();
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
      const compTokens = new Set();
      selectedCompetitors.forEach(c => {
        (c.title || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).forEach(w => {
          if (w.length > 2) compTokens.add(w);
        });
      });
      kws = Array.from(compTokens).slice(0, 20);
    }
    
    if (kws.length) {
      let html = '';
      kws.forEach((k, i) => {
        let cls = i < 3 ? 'high' : (i < 8 ? 'med' : 'low');
        html += `<span class="chip ${cls}">${k}</span>`;
      });
      container.innerHTML = html;
    } else {
      container.innerHTML = '<div class="muted">Kelime bulunamadı. AI doğrudan başlık üzerinden analiz yapacak.</div>';
    }
  } catch (e) {
    container.innerHTML = '<div class="muted">Bağlantı hatası.</div>';
  }
  
  loading.style.display = 'none';
  container.style.display = 'block';
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
  };
}

async function analyze() {
  const body = collectData();
  if (!body.title) { setStatus("Başlık gerekli!"); return; }
  
  goToStep(4);
  $("loading-view").style.display = "flex";
  $("plan-view").style.display = "none";
  
  try {
    const r = await fetch(`${API}/api/launch/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    lastPlan = await r.json();
    renderPlan(lastPlan);
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
  if (!lastPlan) return;
  const btn = $("btn-dl");
  btn.textContent = "Hazırlanıyor...";
  btn.disabled = true;
  
  try {
    const r = await fetch(`${API}/api/launch/bulksheet`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastPlan),
    });
    if (!r.ok) throw new Error(r.status);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const brand = (lastPlan.product.brand || lastPlan.product.title || "launch").replace(/[^a-z0-9]+/gi, "-").slice(0, 24);
    a.download = `${brand}-launch-bulksheet.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    btn.textContent = "✅ İndirildi";
  } catch (e) {
    btn.textContent = "İndirme Hatası!";
    console.error(e);
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
  rescan();
});
