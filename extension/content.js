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
function soupAttr(sel, attr) {
  const n = document.querySelector(sel);
  return n ? (n.getAttribute(attr) || "") : "";
}

function parseRating(s) {
  /* "4.3 out of 5 stars" -> 4.3. Duz sayi kazima "4.34.3..." metninden
     4.34 uretiyordu; puan her zaman "X out of" kalibindan okunur. */
  if (!s) return 0;
  // Puan 0-5 arasi TEK hanedir. Genis kalip ([\d]+...) "4.34.3 out of 5"
  // metninde acgozlu davranip 34.3 yakaliyordu.
  const m = String(s).match(/([0-5](?:[.,]\d)?)\s*out of\s*5/i);
  if (m) return parseFloat(m[1].replace(",", "."));
  const m2 = String(s).match(/^\s*([\d]+[.,]?\d?)\b/);
  const v = m2 ? parseFloat(m2[1].replace(",", ".")) : 0;
  return v > 5 ? 0 : v;      // 5'ten buyukse yanlis okumadir
}

function cleanBrand(s) {
  /* "Visit the PURA D'OR Store" / "Brand: X" / "X Store" -> "X" */
  if (!s) return "";
  return String(s)
    .replace(/^\s*(visit the|brand:|marka:|store:)\s*/i, "")
    .replace(/\s+store\s*$/i, "")
    .replace(/['’]s\s+store\s*$/i, "")
    .trim();
}

function scrapeProductDeep() {
  const title = txt("#productTitle") || txt("#title");
  if (!title) return null; // Not a product page

  const asin = asinFromUrl();
  // "Visit the PURA D'OR Store" / "Brand: X" gibi sarmalayici metinleri temizle;
  // ham haliyle marka adi kampanya adina ve marka filtresine kirli giriyordu.
  const brand = cleanBrand(txt("#bylineInfo") || txt("a#bylineInfo") || txt("#brand"));

  // Fiyat: Amazon sayfa duzenini sik degistiriyor, tek secici yetmiyor.
  // Sirayla dene, ilk makul degeri al.
  let price = null;
  for (const sel of [
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    "#price_inside_buybox",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    ".a-price .a-offscreen",
  ]) {
    price = parsePrice(txt(sel));
    if (price) break;
  }
  if (!price) {
    // Son care: whole + fraction ayri span'lerde olabilir ($29 . 99)
    const whole = txt("span.a-price-whole");
    const frac = txt("span.a-price-fraction");
    if (whole) price = parsePrice(whole + (frac ? "." + frac.replace(/\D/g, "") : ""));
  }

  // Bullets
  const bullets = [];
  document.querySelectorAll("#feature-bullets ul li, .a-unordered-list.a-vertical li").forEach(li => {
    const t = li.textContent.trim();
    if (t && !li.classList.contains("a-spacing-small")) bullets.push(t);
  });

  // Description
  const description = txt("#productDescription p") || txt("#productDescription_feature_div");

  // Rating. DIKKAT: #acrPopover metni "4.34.3 out of 5 stars" seklinde
  // birlesik gelir; duz parse 4.34 uretiyordu. aria-label / "X out of" regex
  // ile okunmali.
  const rating = parseRating(
    (soupAttr("#acrPopover", "title") || "") + " " +
    txt("#acrPopover") + " " + txt(".a-icon-star .a-icon-alt"));

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
    
    const image = pickImage(card) || pickImage(a);

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
    
    const image = pickImage(el);

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
// Amazon gorsel URL'inde boyut dosya adinda kodludur:
//   ._SS64_.jpg (64px kucucuk)  ._AC_UL960_QL65_.jpg (960px devasa)
// Karisik boyutlar kart duzenini bozuyor; hepsini tek boyuta normalize et.
function normalizeAmazonImage(url, size) {
  if (!url) return '';
  return url.replace(/\._[A-Z0-9_,]+_\.(jpg|png|webp)/i, `._SL${size || 160}_.$1`);
}

// Kart icindeki GERCEK urun gorselini secer.
// Not: querySelector('a, b, img') secici onceligi degil BELGE SIRASI kullanir;
// bu yuzden tek cagriyla secmek rozet ikonu/lazy placeholder getiriyordu.
function pickImage(root) {
  if (!root) return '';
  const imgs = Array.from(root.querySelectorAll('img'));
  let best = '', bestArea = -1;

  const consider = (url, area) => {
    if (!url || url.startsWith('data:')) return;
    if (!/(media-amazon|images-amazon|ssl-images-amazon)\.com/.test(url)) return;
    if (/sprite|grey-pixel|transparent-pixel|loading|1x1/i.test(url)) return;
    if (area > bestArea) { bestArea = area; best = url; }
  };

  imgs.forEach(img => {
    // 1) data-a-dynamic-image: {"url": [genislik, yukseklik], ...} -> en buyugu
    const dyn = img.getAttribute('data-a-dynamic-image');
    if (dyn) {
      try {
        const parsed = JSON.parse(dyn);
        Object.entries(parsed).forEach(([u, dim]) => {
          const a = Array.isArray(dim) ? (dim[0] || 0) * (dim[1] || 0) : 0;
          consider(u, a || 1);
        });
      } catch (e) {
        const m = dyn.match(/"(https:[^"]+)"/);
        if (m) consider(m[1], 1);
      }
    }
    // 2) srcset: en yuksek cozunurluk
    const ss = img.getAttribute('srcset');
    if (ss) {
      ss.split(',').forEach(part => {
        const [u, d] = part.trim().split(/\s+/);
        consider(u, parseFloat(d) || 1);
      });
    }
    // 3) duz src / lazy attribute'lari
    const w = img.naturalWidth || parseInt(img.getAttribute('width'), 10) || 0;
    const h = img.naturalHeight || parseInt(img.getAttribute('height'), 10) || 0;
    const area = (w && h) ? w * h : 1;
    if (w && w < 40) return;                 // rozet/ikon ele
    consider(img.getAttribute('src'), area);
    consider(img.getAttribute('data-src'), area);
    consider(img.getAttribute('data-old-hires'), area);
  });

  return normalizeAmazonImage(best, 160);
}

const _KW_STOP = new Set(['for','with','and','the','of','to','in','on','by','from',
  'your','our','a','an','plus','pack','set','count','oz','ml','fl','pcs','piece','pieces']);

function extractMainKeywords(title) {
  // Ingilizce urun adlari head-final'dir: kategori nounu SONDA olur
  // ("... volumizing thickening SHAMPOO"). Basligin ilk kelimeleri ise
  // markadir ve autocomplete'e verilince alakasiz sonuc dondurur.
  if (!title) return [];
  // Stop-word'ler SILINMEZ, noktalama gibi SINIR olur; yoksa
  // "...shampoo for thin" -> "shampoo thin" gibi sahte obek cikar.
  // Olcu/adet token'lari (500mg, 120, 12oz) tohum olamaz.
  const isNoise = w => w.length <= 2 || _KW_STOP.has(w) ||
                       /^\d+([a-z]{1,4})?$/.test(w);
  const segs = title.toLowerCase()
    .replace(/[^a-z0-9\s,;:/()\-]/g, " ")
    .split(/[,;:/()]|\s-\s/)
    .flatMap(s => {
      const out = [];
      let cur = [];
      s.split(/\s+/).forEach(w => {
        if (isNoise(w)) { if (cur.length) { out.push(cur); cur = []; } }
        else cur.push(w);
      });
      if (cur.length) out.push(cur);
      return out;
    })
    .filter(s => s.length);
  if (!segs.length) return [title.toLowerCase().slice(0, 40)];

  // Kategori nounu baslikta TEKRAR eder (shampoo x2, hair x3); icerik
  // kelimeleri (malva, redensyl) bir kez gecer. Tohumlari buna gore sirala.
  const tf = new Map();
  segs.flat().forEach(w => tf.set(w, (tf.get(w) || 0) + 1));

  const seeds = new Set();
  segs.forEach(w => {
    if (w.length >= 3) seeds.add(w.slice(-3).join(" "));
    if (w.length >= 2) seeds.add(w.slice(-2).join(" "));
    seeds.add(w[w.length - 1]);            // yalin kategori nounu
  });

  const score = s => s.split(" ").reduce((a, w) => a + (tf.get(w) || 0), 0);
  return Array.from(seeds).sort((a, b) => score(b) - score(a)).slice(0, 6);
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

// === OTOMATIK RAKIP KESFI ===
// Sayfada ne varsa onu toplamak yerine, urunun ANA KELIMELERINDE kimin
// siralandigini bulur. Gercek rakip = ayni sorgularda karsina cikan urun.
// Bir ASIN ne kadar cok kelimede goruluyorsa o kadar guclu rakiptir.

function parseCompactNumber(s) {
  /* Amazon kisaltarak yazar: "7,997" | "7.9K" | "2K+" | "1.2M" */
  if (!s) return 0;
  const m = String(s).match(/([\d.,]+)\s*([KkMm])?/);
  if (!m) return 0;
  let v = parseFloat(m[1].replace(/,/g, ""));
  if (isNaN(v)) return 0;
  const u = (m[2] || "").toLowerCase();
  if (u === "k") v *= 1000;
  else if (u === "m") v *= 1000000;
  return Math.round(v);
}

function parseSearchDoc(doc) {
  /* Arama sonucu HTML'inden urun kartlarini cikarir (organik + sponsorlu).
     NOT: rating/yorum icin duz metin kazimak cop veri uretir ("4.3 out of 5
     stars" -> 4.35). Bu yuzden aria-label ve .a-icon-alt regex ile okunur. */
  const out = [];
  doc.querySelectorAll("div[data-asin]").forEach((el) => {
    const asin = (el.getAttribute("data-asin") || "").toUpperCase();
    if (!asin || asin.length !== 10) return;
    const t = (sel, root) => {
      const n = (root || el).querySelector(sel);
      return n ? (n.textContent || "").trim() : "";
    };
    const title = t("h2 a span") || t("h2") || t("span.a-text-normal")
               || t("span.a-size-medium") || t("span.a-size-base-plus");
    if (!title || title.length < 5) return;

    const rb = el.querySelector('[data-cy="reviews-block"]') || el;
    const rm = (t(".a-icon-alt", rb) || "").match(/([\d.,]+)\s*out of/i);
    const rating = rm ? parseFloat(rm[1].replace(",", ".")) : 0;

    // "7,997 ratings" seklindeki aria-label en guvenilir kaynak.
    const rlab = Array.from(rb.querySelectorAll("[aria-label]"))
      .map(n => n.getAttribute("aria-label"))
      .find(a => a && /rating/i.test(a) && /\d/.test(a) && !/out of/i.test(a));
    let reviews = rlab ? parseCompactNumber(rlab) : 0;
    if (!reviews) reviews = parseCompactNumber(t(".s-underline-text", rb));

    // Satis hizi sinyali: "2K+ bought in past month"
    const bm = (el.textContent || "").match(/([\d.,]+[KkMm]?)\+?\s*bought in past month/i);

    out.push({
      asin,
      title: title.slice(0, 200),
      price: parsePrice(t(".a-price .a-offscreen") || t(".a-color-price")),
      rating,
      review_count: reviews,
      bought_past_month: bm ? parseCompactNumber(bm[1]) : 0,
      // Ham querySelector rozet ikonu/placeholder getiriyor; pickImage
      // srcset/data-a-dynamic-image'i tarayip en buyuk gercek gorseli secer.
      image: pickImage(el),
      is_sponsored: /sponsored/i.test(el.textContent || ""),
    });
  });
  return out;
}

async function searchAsins(keyword) {
  /* Amazon arama sonucunu ayni origin uzerinden ceker ve parse eder.
     Content script amazon.com'da calistigi icin oturum/bolge korunur. */
  const url = `${location.origin}/s?k=${encodeURIComponent(keyword)}`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`arama basarisiz: ${res.status}`);
  const html = await res.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  return parseSearchDoc(doc);
}

async function discoverCompetitors(title, ownAsin, extraKeywords) {
  /* Ana kelimeleri belirle -> her biri icin arama yap -> ASIN'leri birlestir.
     Skorlama: kac farkli kelimede gorundugu + ortalama siralamasi. */
  const seeds = [];
  (extractMainKeywords(title) || []).forEach(k => seeds.push(k));
  (extraKeywords || []).forEach(k => seeds.push(k));
  const queries = Array.from(new Set(seeds.filter(Boolean))).slice(0, 5);
  if (!queries.length) return { competitors: [], queries: [], errors: ["kelime uretilemedi"] };

  const own = (ownAsin || "").toUpperCase();
  const agg = new Map();
  const errors = [];

  // Sirali ve araliklarla: paralel patlatmak Amazon'un bot korumasini tetikler.
  for (const q of queries) {
    let rows = [];
    try {
      rows = await searchAsins(q);
    } catch (e) {
      errors.push(`${q}: ${e.message}`);
      continue;
    }
    rows.slice(0, 20).forEach((r, i) => {
      if (!r.asin || r.asin === own) return;
      const cur = agg.get(r.asin) || {
        ...r, seen_for: [], ranks: [], sponsored_count: 0,
      };
      // Ayni ASIN tek sayfada hem sponsorlu hem organik cikabilir; kelime
      // ortusmesi BENZERSIZ sorgu sayisidir, gorulme sayisi degil.
      if (!cur.seen_for.includes(q)) cur.seen_for.push(q);
      cur.ranks.push(i + 1);
      if (r.is_sponsored) cur.sponsored_count++;
      // Eksik alanlari sonraki gorulmede tamamla
      if (!cur.price && r.price) cur.price = r.price;
      if (!cur.review_count && r.review_count) cur.review_count = r.review_count;
      if (!cur.rating && r.rating) cur.rating = r.rating;
      if (!cur.bought_past_month && r.bought_past_month) cur.bought_past_month = r.bought_past_month;
      if (!cur.image && r.image) cur.image = r.image;
      agg.set(r.asin, cur);
    });
    await new Promise(r => setTimeout(r, 400));
  }

  const comps = Array.from(agg.values()).map(c => {
    const avgRank = c.ranks.reduce((a, b) => a + b, 0) / c.ranks.length;
    return {
      asin: c.asin, title: c.title, price: c.price, image: c.image,
      rating: c.rating, review_count: c.review_count,
      bought_past_month: c.bought_past_month || 0,
      keyword_overlap: c.seen_for.length,       // kac kelimede cikti
      avg_rank: Math.round(avgRank * 10) / 10,  // ortalama siralama
      seen_for: c.seen_for,
      is_sponsored: c.sponsored_count > 0,
      // Kesif skoru: cok kelimede + ust siralarda olan gercek rakiptir
      discovery_score: Math.round(c.seen_for.length * 100 - avgRank * 2),
    };
  });
  comps.sort((a, b) => b.discovery_score - a.discovery_score);
  return { competitors: comps.slice(0, 25), queries, errors };
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
  if (msg.type === 'DISCOVER_COMPETITORS') {
    discoverCompetitors(msg.title, msg.asin, msg.keywords)
      .then(sendResponse)
      .catch(e => sendResponse({ competitors: [], queries: [], errors: [String(e)] }));
    return true; // async
  }
  if (msg.type === 'FETCH_SUGGESTIONS') {
    fetchSearchSuggestions(msg.keyword).then(s => sendResponse({suggestions: s}));
    return true; // async
  }
  return true;
});
