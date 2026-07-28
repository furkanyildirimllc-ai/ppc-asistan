// popup.js — sayfayi oku, backend'e gonder, plani goster, bulk sheet indir.
const API = "http://localhost:8642";

const $ = (id) => document.getElementById(id);
const setStatus = (t, cls = "") => { const s = $("status"); s.textContent = t; s.className = cls; };

let scraped = { competitors: [] };
let lastPlan = null;

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function fillForm(d) {
  $("f-title").value = d.title || "";
  $("f-asin").value = d.asin || "";
  $("f-price").value = d.price != null ? d.price : "";
  $("f-brand").value = d.brand || "";
  const n = (d.competitors || []).length;
  $("comp-count").textContent = n
    ? `✓ ${n} rakip algilandi${d.searchQuery ? ` ("${d.searchQuery}" aramasi)` : ""}`
    : "Rakip algilanamadi — yine de devam edebilirsin.";
}

async function rescan() {
  setStatus("okunuyor…", "spin");
  try {
    const tab = await activeTab();
    const res = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE" }).catch(() => null);
    if (!res || res.kind === "none") {
      setStatus("sayfa okunamadi");
      $("comp-count").textContent =
        res && res.error ? res.error : "Amazon urun/arama sayfasinda ac.";
      return;
    }
    scraped = res;
    fillForm(res);
    setStatus("okundu");
  } catch (e) {
    setStatus("hata");
    $("comp-count").textContent = String(e);
  }
}

function collectProduct() {
  return {
    title: $("f-title").value.trim(),
    asin: $("f-asin").value.trim().toUpperCase(),
    sku: $("f-sku").value.trim(),
    price: parseFloat($("f-price").value) || null,
    brand: $("f-brand").value.trim(),
    cogs: parseFloat($("f-cogs").value) || null,
    fba_fee: parseFloat($("f-fba").value) || null,
    competitors: scraped.competitors || [],
    use_ai: true,
  };
}

async function analyze() {
  const body = collectProduct();
  if (!body.title) { setStatus("baslik gerekli"); return; }
  setStatus("plan uretiliyor… (AI)", "spin");
  $("btn-analyze").disabled = true;
  try {
    const r = await fetch(`${API}/api/launch/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    lastPlan = await r.json();
    renderPlan(lastPlan);
    setStatus("plan hazir", "spin");
  } catch (e) {
    setStatus("hata");
    $("plan").innerHTML = `<div class="note">Backend'e ulasilamadi: ${e}.<br/>
      PPC Asistan calisiyor mu? <code>uvicorn app:app --port 8642</code></div>`;
  } finally {
    $("btn-analyze").disabled = false;
  }
}

function chips(arr) {
  return (arr || []).map((k) => `<span class="kw">${k}</span>`).join("");
}

function renderPlan(plan) {
  const kw = plan.keywords || {};
  const camps = (plan.campaigns || []).map((c) => `
    <div class="camp">
      <b>${c.name}</b><br/>
      <span class="muted">${c.targeting_type} · butce $${c.budget}/gun · bid $${c.default_bid}
      ${c.keywords && c.keywords.length ? `· ${c.keywords.length} kw` : ""}
      ${c.product_targets && c.product_targets.length ? `· ${c.product_targets.length} ASIN` : ""}
      ${c.auto_groups ? "· 4 auto grup" : ""}</span>
    </div>`).join("");
  const notes = (plan.notes || []).map((n) => `<div class="note">${n}</div>`).join("");
  const e = plan.economics;
  const econHtml = e ? `
    <div class="card">
      <div class="tag">💰 Kar analizi</div>
      <div style="margin-top:4px">Birim kar: <b>$${e.unit_profit_before_ads}</b> ·
      Break-even ACOS: <b>%${e.break_even_acos_pct}</b> ·
      Hedef ACOS: <b style="color:var(--ok)">%${e.recommended_target_acos_pct}</b></div>
    </div>` : "";
  const rationaleHtml = plan.rationale ? `
    <div class="card"><div class="tag">🧠 Strateji ozeti</div>
      <div style="margin-top:4px">${plan.rationale}</div></div>` : "";
  const planHtml = (plan.action_plan && plan.action_plan.length) ? `
    <div class="card"><div class="tag">📅 Launch takvimi</div>
      <ul style="margin:6px 0 0 16px;padding:0">${plan.action_plan.map((s) => `<li style="margin:3px 0">${s}</li>`).join("")}</ul></div>` : "";
  const negHtml = (plan.negatives && plan.negatives.length) ? `
    <div class="tag" style="margin-top:8px">🚫 Negatif keyword (bosa parayi keser)</div>${chips(plan.negatives)}` : "";
  $("plan").innerHTML = `
    <div class="card">
      <div class="tag">Kampanya plani · toplam $${plan.daily_budget_total}/gun
        · keyword kaynagi: ${plan.keyword_source}</div>
      ${camps}
    </div>
    ${econHtml}
    ${rationaleHtml}
    <div class="card">
      <div class="tag">Exact (scale)</div>${chips(kw.exact)}
      <div class="tag" style="margin-top:8px">Phrase</div>${chips(kw.phrase)}
      <div class="tag" style="margin-top:8px">Broad (kesif)</div>${chips(kw.broad)}
      ${plan.competitor_asins && plan.competitor_asins.length
        ? `<div class="tag" style="margin-top:8px">Rakip ASIN targeting</div>${chips(plan.competitor_asins)}`
        : ""}
      ${negHtml}
    </div>
    ${planHtml}
    ${notes}
    <button class="success" id="btn-dl">⬇️ Amazon Bulk Sheet indir (.xlsx)</button>
    <div class="muted" style="margin-top:6px">Seller Central → Bulk Operations → Spreadsheet upload'a yukle.</div>
  `;
  $("btn-dl").addEventListener("click", downloadBulksheet);
}

async function downloadBulksheet() {
  if (!lastPlan) return;
  setStatus("bulk sheet…", "spin");
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
    const brand = (lastPlan.product.brand || lastPlan.product.title || "launch")
      .replace(/[^a-z0-9]+/gi, "-").slice(0, 24);
    a.download = `${brand}-launch-bulksheet.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus("indirildi ✓", "spin");
  } catch (e) {
    setStatus("indirilemedi");
  }
}

$("btn-rescan").addEventListener("click", rescan);
$("btn-analyze").addEventListener("click", analyze);
document.addEventListener("DOMContentLoaded", rescan);
rescan();
