// content.js - Deep scraping engine for PPC Launch Pro

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

// === PRODUCT DEEP SCRAPER ===
function scrapeProductDeep() {
  const title = txt("#productTitle") || txt("#title");
  if (!title) return null; // Not a product page

  const asin = asinFromUrl();
  const brand = txt("#bylineInfo") || txt("a#bylineInfo") || txt("#brand");
  let price =
    parsePrice(txt(".a-price .a-offscreen")) ||
    parsePrice(txt("#corePrice_feature_div .a-offscreen")) ||
    parsePrice(txt("#priceblock_ourprice")) ||
    parsePrice(txt("span.a-price-whole"));

  // Bullets
  const bullets = [];
  document.querySelectorAll("#feature-bullets ul li, .a-unordered-list.a-vertical li").forEach(li => {
    const t = li.textContent.trim();
    if (t && !li.classList.contains("a-spacing-small")) bullets.push(t);
  });

  // Description
  const description = txt("#productDescription p") || txt("#productDescription_feature_div");

  // Rating
  const ratingText = txt("#acrPopover") || txt(".a-icon-star .a-icon-alt");
  const rating = parsePrice(ratingText) || 0;

  // Review count
  const reviewCountStr = txt("#acrCustomerReviewText");
  const reviewCount = reviewCountStr ? parseInt(reviewCountStr.replace(/[^0-9]/g, ""), 10) : 0;

  // BSR
  let bsr = { rank: null, category: null, sub_ranks: [] };
  const bsrText = txt("#productDetails_detailBullets_sections1") || txt("#SalesRank") || txt("#detailBullets_feature_div");
  if (bsrText) {
    const ranks = bsrText.match(/#([0-9,]+)\s+in\s+([^\(]+)/g);
    if (ranks && ranks.length > 0) {
      ranks.forEach((r, i) => {
        const m = r.match(/#([0-9,]+)\s+in\s+(.+)/);
        if (m) {
          const rankNum = parseInt(m[1].replace(/,/g, ""), 10);
          if (i === 0) {
            bsr.rank = rankNum;
            bsr.category = m[2].trim();
          } else {
            bsr.sub_ranks.push({ rank: rankNum, category: m[2].trim() });
          }
        }
      });
    }
  }

  // Badges
  const badges = {
    best_seller: !!document.querySelector(".p13n-best-seller-badge, #zeitgeistBadge_feature_div"),
    amazon_choice: !!document.querySelector(".ac-badge-wrapper, .ac-badge"),
    coupon: txt("#couponText") || txt(".couponBadge")
  };

  // Listing Quality
  const variantCount = document.querySelectorAll("#variation_color_name li, .twister-dropdown-option").length;
  const imageCount = document.querySelectorAll("#altImages img").length;
  const hasAplus = !!document.querySelector("#aplus, #aplus_feature_div, .aplus-v2");

  const listing_quality = { has_aplus: hasAplus, image_count: imageCount, variant_count: variantCount };

  return {
    kind: 'product',
    title,
    asin,
    brand: brand.replace(/^(Visit the|Brand:|marka:)\s*/i, "").replace(/\s*Store$/i, "").trim(),
    price,
    bullets: bullets.slice(0, 10),
    description: description.slice(0, 1000),
    rating,
    review_count: reviewCount,
    bsr,
    badges,
    listing_quality,
    competitors: scrapeCompetitorsDeep(),
    url: location.href
  };
}

// === COMPETITOR DEEP SCRAPER ===
function scrapeCompetitorsDeep() {
  const comps = [];
  const seen = new Set();
  const currentAsin = asinFromUrl();
  
  // 1. Scan all product links across the page (carousels, related items, sponsored, etc.)
  document.querySelectorAll("a[href*='/dp/'], a[href*='/gp/product/'], div[data-asin]").forEach(el => {
    let asin = "";
    let a = null;
    let card = el;
    
    if (el.tagName === "A") {
      a = el;
      asin = asinFromUrl(a.getAttribute("href"));
      card = a.closest("li, div[class*='card'], div[class*='grid'], div[class*='item'], div[data-asin], .a-carousel-card") || a.parentElement;
    } else {
      asin = (el.getAttribute("data-asin") || "").toUpperCase();
      a = el.querySelector("a[href*='/dp/'], a[href*='/gp/product/']");
    }
    
    if (!asin || asin.length !== 10 || seen.has(asin) || asin === currentAsin) return;
    
    let title = "";
    if (a) {
      title = a.getAttribute("title") || 
              (a.querySelector("img") && a.querySelector("img").getAttribute("alt")) || 
              a.getAttribute("aria-label") || "";
    }
    if (!title && card) {
      title = txt("h2 a span", card) || 
              txt("h2", card) || 
              txt("[class*='truncate']", card) || 
              txt(".p13n-sc-truncate", card) ||
              txt("[class*='line-clamp']", card) ||
              txt("[class*='title']", card) || 
              txt("span.a-size-medium", card) || 
              txt("span.a-size-base-plus", card) || 
              txt("span.a-size-base", card) || 
              (a ? txt("span", a) : "");
    }
    
    // Additional fallback for images
    if (!title && card) {
       const img = card.querySelector("img");
       if (img) title = img.getAttribute("alt") || img.getAttribute("title") || "";
    }
    
    title = (title || "").trim().replace(/\s+/g, " ");
    if (title.length < 5) return;
    
    const price = parsePrice(txt(".a-price .a-offscreen", card)) || parsePrice(txt(".a-color-price", card));
    const rating = parsePrice(txt(".a-icon-star .a-icon-alt", card)) || parsePrice(txt(".a-icon-alt", card)) || 0;
    
    const reviewText = txt("a[href*='customerReviews']", card) || txt("span[aria-label*='rating']", card) || txt(".a-size-small", card);
    const review_count = reviewText ? parseInt(reviewText.replace(/[^0-9]/g, ""), 10) : 0;
    
    const is_best_seller = !!card.querySelector(".p13n-best-seller-badge, .badge, [class*='best-seller']");
    const is_amazon_choice = !!card.querySelector(".ac-badge-wrapper, .ac-badge, [class*='choice']");
    const is_sponsored = !!txt(".puis-sponsored-label-text", card) || txt("span", card).toLowerCase().includes("sponsored");
    
    // Get competitor image with robust fallback
    let image = '';
    const img = card.querySelector('img[src*="images-I"], img[src*="media-amazon"], img');
    if (img) {
      const dyn = img.getAttribute('data-a-dynamic-image');
      if (dyn) {
        try {
          const parsed = JSON.parse(dyn);
          const urls = Object.keys(parsed);
          if (urls.length > 0) image = urls[0];
        } catch(e) {
          const m = dyn.match(/"(https:[^"]+)"/);
          if (m) image = m[1];
        }
      }
      if (!image) {
        image = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('srcset')?.split(' ')[0] || '';
      }
    }
    
    seen.add(asin);
    comps.push({ 
      asin, 
      title: title.slice(0, 200), 
      price, 
      image,
      rating, 
      review_count: isNaN(review_count) ? 0 : review_count, 
      badges: { best_seller: is_best_seller, amazon_choice: is_amazon_choice, sponsored: is_sponsored } 
    });
  });
  
  return comps.slice(0, 35);
}

// --- SEARCH PAGE SCRAPER (existing logic preserved) ---
function scrapeSearchResults() {
  const comps = [];
  document.querySelectorAll("div[data-asin]").forEach((el) => {
    const asin = (el.getAttribute("data-asin") || "").toUpperCase();
    if (!asin || asin.length !== 10) return;
    const title = txt("h2 a span", el) || txt("h2", el) || txt("span.a-text-normal", el) || txt("span.a-size-medium", el) || txt("span.a-size-base-plus", el);
    const price = parsePrice(txt(".a-price .a-offscreen", el)) || parsePrice(txt(".a-color-price", el));
    
    const rating = parsePrice(txt(".a-icon-star .a-icon-alt", el)) || parsePrice(txt(".a-icon-alt", el)) || 0;
    const reviewText = txt("span[aria-label*='rating']", el) || txt(".a-size-base", el) || txt("a[href*='customerReviews']", el);
    const review_count = reviewText ? parseInt(reviewText.replace(/[^0-9]/g, ""), 10) : 0;
    
    // Get competitor image
    let image = '';
    const img = el.querySelector('img');
    if (img) {
      image = img.getAttribute('src') || img.getAttribute('data-a-dynamic-image')?.match(/"(https[^"]+)"/)?.[1] || '';
    }
    
    if (title && title.length > 3) comps.push({ asin, title: title.slice(0, 200), price, image, rating, review_count: isNaN(review_count) ? 0 : review_count });
  });
  
  if (comps.length > 0) {
    const [first, ...rest] = comps;
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
  return null;
}

// === SEARCH SUGGESTIONS (Amazon Autocomplete) ===
function extractMainKeywords(title) {
  if (!title) return [];
  let t = title.toLowerCase().replace(/[,|&]/g, " ").replace(/\s+/g, " ");
  const words = t.split(" ").slice(0, 6); // take first few words
  if (words.length < 2) return [t];
  return [
    words.slice(0, 2).join(" "),
    words.slice(0, 3).join(" "),
    words.slice(0, 4).join(" ")
  ];
}

async function fetchSearchSuggestions(keyword) {
  const baseKeywords = extractMainKeywords(keyword);
  const results = await Promise.all(baseKeywords.map(async (kw) => {
    if (!kw) return [];
    try {
      const url = `https://completion.amazon.com/api/2017/suggestions?prefix=${encodeURIComponent(kw)}&mid=ATVPDKIKX0DER&alias=aps`;
      const res = await fetch(url);
      const data = await res.json();
      return (data.suggestions || []).map(s => s.value).filter(Boolean);
    } catch(e) { return []; }
  }));
  const suggestions = new Set();
  results.flat().forEach(s => suggestions.add(s));
  return Array.from(suggestions);
}

// === MESSAGE HANDLER ===
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'SCRAPE') {
    const data = scrapeProductDeep() || scrapeSearchResults() || {kind:'none'};
    sendResponse(data);
  }
  if (msg.type === 'SCRAPE_SEARCH') {
    sendResponse({results: scrapeSearchResults()});
  }
  if (msg.type === 'FETCH_SUGGESTIONS') {
    fetchSearchSuggestions(msg.keyword).then(s => sendResponse({suggestions: s}));
    return true; // async
  }
  return true;
});
