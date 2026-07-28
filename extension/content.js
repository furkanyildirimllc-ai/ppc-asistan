// content.js — acik Amazon sayfasindan urun + rakip verisini okur.
// Popup, chrome.tabs.sendMessage({type:"SCRAPE"}) ile cagirir.

function txt(sel, root = document) {
  const el = root.querySelector(sel);
  return el ? el.textContent.trim().replace(/\s+/g, " ") : "";
}

function parsePrice(s) {
  if (!s) return null;
  const m = s.replace(/[, ]/g, "").match(/(\d+(\.\d+)?)/);
  return m ? parseFloat(m[1]) : null;
}

function asinFromUrl(url) {
  const m = (url || location.href).match(/\/(?:dp|gp\/product|product)\/([A-Z0-9]{10})/i);
  return m ? m[1].toUpperCase() : "";
}

// --- Urun detay sayfasi ---
function scrapeProduct() {
  const title = txt("#productTitle") || txt("#title");
  if (!title) return null;
  const asin = asinFromUrl();
  const brand = txt("#bylineInfo") || txt("a#bylineInfo") || txt("#brand");
  let price =
    parsePrice(txt(".a-price .a-offscreen")) ||
    parsePrice(txt("#corePrice_feature_div .a-offscreen")) ||
    parsePrice(txt("#priceblock_ourprice")) ||
    parsePrice(txt("span.a-price-whole"));
  return {
    kind: "product",
    title,
    asin,
    brand: brand.replace(/^(Visit the|Brand:|marka:)\s*/i, "").replace(/\s*Store$/i, "").trim(),
    price,
  };
}

// --- Ayni sayfadaki rakipler (carousel / benzer urunler) ---
function scrapeCompetitorsOnPage() {
  const comps = [];
  const seen = new Set();
  // "Products related to this item", "4 stars and above" vb. carousel kartlari
  document.querySelectorAll("a[href*='/dp/'], a[href*='/gp/product/']").forEach((a) => {
    const asin = asinFromUrl(a.getAttribute("href"));
    if (!asin || seen.has(asin) || asin === asinFromUrl()) return;
    // baslik: karttaki alt/aria/text
    const card = a.closest("li, div");
    let t =
      a.getAttribute("title") ||
      (a.querySelector("img") && a.querySelector("img").getAttribute("alt")) ||
      (card && (card.querySelector("[class*='p13n-sc-truncate']") || {}).textContent) ||
      a.textContent;
    t = (t || "").trim().replace(/\s+/g, " ");
    if (t.length < 8) return;
    seen.add(asin);
    comps.push({ asin, title: t.slice(0, 200) });
  });
  return comps.slice(0, 20);
}

// --- Arama sonucu sayfasi ---
function scrapeSearchResults() {
  const comps = [];
  document.querySelectorAll("div[data-asin]").forEach((el) => {
    const asin = (el.getAttribute("data-asin") || "").toUpperCase();
    if (!asin || asin.length !== 10) return;
    const title = txt("h2 a span", el) || txt("h2", el);
    const price = parsePrice(txt(".a-price .a-offscreen", el));
    if (title) comps.push({ asin, title: title.slice(0, 200), price });
  });
  return comps.slice(0, 25);
}

function scrapeAll() {
  const product = scrapeProduct();
  if (product) {
    return { ...product, competitors: scrapeCompetitorsOnPage(), url: location.href };
  }
  // arama sayfasi -> ilk urunu "aday urun" gibi don, gerisi rakip
  const results = scrapeSearchResults();
  if (results.length) {
    const [first, ...rest] = results;
    return {
      kind: "search",
      title: first.title,
      asin: first.asin,
      brand: "",
      price: first.price,
      competitors: rest,
      url: location.href,
      searchQuery: new URLSearchParams(location.search).get("k") || "",
    };
  }
  return { kind: "none", error: "Bu sayfada urun/arama sonucu bulunamadi." };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "SCRAPE") {
    try {
      sendResponse(scrapeAll());
    } catch (e) {
      sendResponse({ kind: "none", error: String(e) });
    }
  }
  return true;
});
