"""PPC Asistan - Amazon reklam raporu analiz araci.
Calistir: .venv/bin/uvicorn app:app --port 8642
"""
import io
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

import parsers
import analysis
import ai_agent
import supervisor
import insights
import bulksheet
import launch as launch_mod
import chat as chat_mod
import market_intel
import brain

DB_PATH = Path(__file__).parent / "ppc.db"
app = FastAPI(title="PPC Asistan")

# Chrome uzantisi (content script + popup) backend'e erisebilsin diye.
# Uzanti origin'i chrome-extension://... olur; gelistirmede tumune izin veriyoruz.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS brands(
            id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
            target_acos REAL DEFAULT 0.30,
            min_clicks_neg INTEGER DEFAULT 8,
            min_orders_harvest INTEGER DEFAULT 2,
            bid_change_cap REAL DEFAULT 0.25,
            sell_price REAL DEFAULT 0,
            cogs REAL DEFAULT 0,
            amazon_fee_pct REAL DEFAULT 0.15,
            fba_fee REAL DEFAULT 0,
            harvest_campaign TEXT DEFAULT '',
            harvest_ad_group TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS uploads(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            filename TEXT, report_type TEXT, row_count INTEGER,
            uploaded_at TEXT);
        CREATE TABLE IF NOT EXISTS report_rows(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recommendations(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            type TEXT, campaign TEXT, ad_group TEXT, keyword TEXT,
            match_type TEXT, current_value REAL, suggested_value REAL,
            reason TEXT, metrics TEXT,
            confidence_score INTEGER DEFAULT 0,
            is_auto_applied INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS ai_strategies(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            created_at TEXT,
            strategy_json TEXT,
            review_json TEXT,
            approved INTEGER DEFAULT 0,
            safe_to_send INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS rec_history(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            rec_snapshot TEXT,
            new_status TEXT,
            old_status TEXT,
            acted_at TEXT);
        CREATE TABLE IF NOT EXISTS chat_messages(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            role TEXT, content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY,
            brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
            name TEXT, asin TEXT, sell_price REAL DEFAULT 0,
            cogs REAL DEFAULT 0, amazon_fee_pct REAL DEFAULT 0.15,
            fba_fee REAL DEFAULT 0, share_pct REAL DEFAULT 0);
        """)
        # ALTER TABLE - eski DB'lere yeni kolonlari ekle (yoksa)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(brands)")}
        for col, ddl in [
            ("sell_price", "ALTER TABLE brands ADD COLUMN sell_price REAL DEFAULT 0"),
            ("cogs", "ALTER TABLE brands ADD COLUMN cogs REAL DEFAULT 0"),
            ("amazon_fee_pct", "ALTER TABLE brands ADD COLUMN amazon_fee_pct REAL DEFAULT 0.15"),
            ("fba_fee", "ALTER TABLE brands ADD COLUMN fba_fee REAL DEFAULT 0"),
            ("harvest_campaign", "ALTER TABLE brands ADD COLUMN harvest_campaign TEXT DEFAULT ''"),
            ("harvest_ad_group", "ALTER TABLE brands ADD COLUMN harvest_ad_group TEXT DEFAULT ''"),
            # Rakip marka tespiti otomatik tahmindir; kullanici duzeltmesi burada saklanir
            ("competitor_brands", "ALTER TABLE brands ADD COLUMN competitor_brands TEXT DEFAULT ''"),
            ("not_brands", "ALTER TABLE brands ADD COLUMN not_brands TEXT DEFAULT ''"),
        ]:
            if col not in cols:
                c.execute(ddl)
                
        # ALTER TABLE recommendations
        rec_cols = {r["name"] for r in c.execute("PRAGMA table_info(recommendations)")}
        for col, ddl in [
            ("confidence_score", "ALTER TABLE recommendations ADD COLUMN confidence_score INTEGER DEFAULT 0"),
            ("is_auto_applied", "ALTER TABLE recommendations ADD COLUMN is_auto_applied INTEGER DEFAULT 0"),
        ]:
            if col not in rec_cols:
                c.execute(ddl)


init_db()


class BrandIn(BaseModel):
    name: str
    target_acos: float = 0.30
    min_clicks_neg: int = 8
    min_orders_harvest: int = 2
    bid_change_cap: float = 0.25
    sell_price: float = 0
    cogs: float = 0
    amazon_fee_pct: float = 0.15
    fba_fee: float = 0
    harvest_campaign: str = ""
    harvest_ad_group: str = ""
    competitor_brands: str = ""
    not_brands: str = ""


def _profit_calc_single(sp, cogs, fee_pct, fba):
    if sp <= 0:
        return None
    ref_fee = sp * fee_pct
    unit_profit = sp - cogs - ref_fee - fba
    be = unit_profit / sp if sp > 0 else 0
    return {
        "unit_profit_before_ads": round(unit_profit, 2),
        "break_even_acos_pct": round(be * 100, 1),
        "recommended_target_acos_pct": round(be * 0.7 * 100, 1),
        "margin_pct_before_ads": round(unit_profit / sp * 100, 1),
    }


def _profit_calc(b, products=None):
    """Break-even ve karli hedef ACOS. Coklu urun varsa agirlikli ortalama."""
    if products:
        # Agirlikli ortalama - share_pct kullan (yoksa esit paylas)
        total_share = sum((p.get("share_pct") or 0) for p in products)
        if total_share <= 0:
            weights = [1 / len(products)] * len(products)
        else:
            weights = [(p.get("share_pct") or 0) / total_share for p in products]
        agg_profit = 0
        agg_price = 0
        margins = []
        for p, w in zip(products, weights):
            sp = p.get("sell_price") or 0
            if sp <= 0:
                continue
            cogs = p.get("cogs") or 0
            fee = sp * (p.get("amazon_fee_pct") or 0.15)
            fba = p.get("fba_fee") or 0
            up = sp - cogs - fee - fba
            agg_profit += up * w
            agg_price += sp * w
            margins.append({"name": p.get("name") or p.get("asin") or "?",
                            "share_pct": round(w * 100, 1),
                            "unit_profit": round(up, 2),
                            "break_even_acos_pct": round(up / sp * 100, 1) if sp > 0 else 0})
        if agg_price <= 0:
            return None
        be = agg_profit / agg_price
        return {
            "unit_profit_before_ads": round(agg_profit, 2),
            "break_even_acos_pct": round(be * 100, 1),
            "recommended_target_acos_pct": round(be * 0.7 * 100, 1),
            "margin_pct_before_ads": round(agg_profit / agg_price * 100, 1),
            "product_count": len(products),
            "per_product": margins,
            "mode": "weighted",
        }
    # Tek urun (eski)
    sp = b.get("sell_price") or 0
    if sp <= 0:
        return None
    res = _profit_calc_single(sp, b.get("cogs") or 0,
                               b.get("amazon_fee_pct") or 0.15,
                               b.get("fba_fee") or 0)
    if res:
        res["mode"] = "single"
    return res


@app.get("/")
def index():
    return FileResponse(
        Path(__file__).parent / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Pragma": "no-cache", "Expires": "0"})


@app.get("/api/brands")
def list_brands():
    with db() as c:
        brands = [dict(r) for r in c.execute("SELECT * FROM brands ORDER BY name")]
        for b in brands:
            b["uploads"] = [dict(r) for r in c.execute(
                "SELECT filename, report_type, row_count, uploaded_at FROM uploads "
                "WHERE brand_id=? ORDER BY id DESC LIMIT 10", (b["id"],))]
            counts = c.execute(
                "SELECT status, COUNT(*) n FROM recommendations WHERE brand_id=? "
                "GROUP BY status", (b["id"],)).fetchall()
            b["rec_counts"] = {r["status"]: r["n"] for r in counts}
            prods = [dict(r) for r in c.execute(
                "SELECT id,name,asin,sell_price,cogs,amazon_fee_pct,fba_fee,share_pct "
                "FROM products WHERE brand_id=? ORDER BY id", (b["id"],))]
            b["products"] = prods
            b["profit"] = _profit_calc(b, prods if prods else None)
    return brands


@app.post("/api/brands")
def create_brand(body: BrandIn):
    with db() as c:
        try:
            cur = c.execute(
                "INSERT INTO brands(name,target_acos,min_clicks_neg,"
                "min_orders_harvest,bid_change_cap,sell_price,cogs,"
                "amazon_fee_pct,fba_fee,harvest_campaign,harvest_ad_group,"
                "competitor_brands,not_brands) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (body.name.strip(), body.target_acos, body.min_clicks_neg,
                 body.min_orders_harvest, body.bid_change_cap,
                 body.sell_price, body.cogs, body.amazon_fee_pct, body.fba_fee,
                 body.harvest_campaign.strip(), body.harvest_ad_group.strip(),
                 body.competitor_brands.strip(), body.not_brands.strip()))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Bu isimde marka zaten var")
        return {"id": cur.lastrowid}


@app.put("/api/brands/{brand_id}")
def update_brand(brand_id: int, body: BrandIn):
    with db() as c:
        c.execute(
            "UPDATE brands SET name=?,target_acos=?,min_clicks_neg=?,"
            "min_orders_harvest=?,bid_change_cap=?,sell_price=?,cogs=?,"
            "amazon_fee_pct=?,fba_fee=?,harvest_campaign=?,harvest_ad_group=?,"
            "competitor_brands=?,not_brands=? "
            "WHERE id=?",
            (body.name.strip(), body.target_acos, body.min_clicks_neg,
             body.min_orders_harvest, body.bid_change_cap,
             body.sell_price, body.cogs, body.amazon_fee_pct, body.fba_fee,
             body.harvest_campaign.strip(), body.harvest_ad_group.strip(),
             body.competitor_brands.strip(), body.not_brands.strip(),
             brand_id))
    _regenerate(brand_id)
    return {"ok": True}


@app.delete("/api/brands/{brand_id}")
def delete_brand(brand_id: int):
    with db() as c:
        c.execute("DELETE FROM brands WHERE id=?", (brand_id,))
    return {"ok": True}


def _load_rows(c, brand_id, rtype):
    return [json.loads(r["data"]) for r in c.execute(
        "SELECT data FROM report_rows WHERE brand_id=? AND report_type=?",
        (brand_id, rtype))]


def _regenerate(brand_id):
    """Marka verisinden onerileri yeniden uret (onaylanmis/reddedilmisler korunur)."""
    with db() as c:
        brand = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand:
            return
        sts = _load_rows(c, brand_id, "search_term")
        tgs = _load_rows(c, brand_id, "targeting")
        plc = _load_rows(c, brand_id, "placement")
        camps = _load_rows(c, brand_id, "campaign")
        recs = analysis.run_all(dict(brand), sts, tgs, plc, camps)
        # islenmis (approved/rejected) onerileri tekrar gosterme
        done = {(r["type"], r["campaign"], r["keyword"], r["match_type"])
                for r in c.execute(
                    "SELECT type,campaign,keyword,match_type FROM recommendations "
                    "WHERE brand_id=? AND status!='pending'", (brand_id,))}
        c.execute("DELETE FROM recommendations WHERE brand_id=? AND status='pending'",
                  (brand_id,))
        for r in recs:
            if (r["type"], r["campaign"], r["keyword"], r["match_type"]) in done:
                continue
            
            auto_apply = r.get("auto_apply", False)
            status = 'approved' if auto_apply else 'pending'
            
            c.execute(
                "INSERT INTO recommendations(brand_id,type,campaign,ad_group,keyword,"
                "match_type,current_value,suggested_value,reason,metrics,"
                "confidence_score,is_auto_applied,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (brand_id, r["type"], r["campaign"], r["ad_group"], r["keyword"],
                 r["match_type"], r["current_value"], r["suggested_value"],
                 r["reason"], json.dumps(r["metrics"]), 
                 r.get("confidence", 0), 1 if auto_apply else 0, status))


@app.post("/api/brands/{brand_id}/upload")
async def upload(brand_id: int, files: list[UploadFile]):
    results = []
    with db() as c:
        if not c.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,)).fetchone():
            raise HTTPException(404, "Marka bulunamadi")
        for f in files:
            content = await f.read()
            # Guvenlik: 100MB'tan buyuk dosyalari reddet (OOM koruması)
            if len(content) > 100 * 1024 * 1024:
                results.append({"file": f.filename, "ok": False,
                                "error": "Dosya çok büyük (max 100MB)"})
                continue
            try:
                rtype, rows = parsers.parse(f.filename, content)
            except Exception as e:
                results.append({"file": f.filename, "ok": False, "error": str(e)})
                continue
            if rows:
                # ayni tip eski veriyi degistir
                c.execute("DELETE FROM report_rows WHERE brand_id=? AND report_type=?",
                          (brand_id, rtype))
                c.executemany(
                    "INSERT INTO report_rows(brand_id,report_type,data) VALUES(?,?,?)",
                    [(brand_id, rtype, json.dumps(r)) for r in rows])
            c.execute(
                "INSERT INTO uploads(brand_id,filename,report_type,row_count,"
                "uploaded_at) VALUES(?,?,?,?,?)",
                (brand_id, f.filename, rtype, len(rows),
                 datetime.now().isoformat(timespec="seconds")))
            results.append({"file": f.filename, "ok": True,
                            "type": parsers.REPORT_LABELS.get(rtype, rtype),
                            "rows": len(rows)})
    _regenerate(brand_id)
    return results


@app.get("/api/brands/{brand_id}/recommendations")
def get_recs(brand_id: int, status: str = "pending"):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM recommendations WHERE brand_id=? AND status=? "
            "ORDER BY type, id", (brand_id, status)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics"] or "{}")
        out.append(d)
    return out


class RecAction(BaseModel):
    ids: list[int]
    status: str  # approved | rejected | pending


@app.post("/api/brands/{brand_id}/recommendations/action")
def rec_action(brand_id: int, body: RecAction):
    if body.status not in ("approved", "rejected", "pending"):
        raise HTTPException(400, "Gecersiz durum")
    with db() as c:
        # history icin snapshot
        rows = c.execute(
            "SELECT id,type,campaign,ad_group,keyword,match_type,current_value,"
            "suggested_value,reason,metrics,status FROM recommendations "
            f"WHERE brand_id=? AND id IN ({','.join('?'*len(body.ids))})",
            (brand_id, *body.ids)).fetchall()
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            c.execute(
                "INSERT INTO rec_history(brand_id,rec_snapshot,new_status,"
                "old_status,acted_at) VALUES(?,?,?,?,?)",
                (brand_id, json.dumps(dict(r)), body.status, r["status"], now))
        c.executemany(
            "UPDATE recommendations SET status=? WHERE id=? AND brand_id=?",
            [(body.status, i, brand_id) for i in body.ids])
    return {"ok": True}


@app.get("/api/brands/{brand_id}/history")
def get_history(brand_id: int, limit: int = 50):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM rec_history WHERE brand_id=? ORDER BY id DESC LIMIT ?",
            (brand_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["rec_snapshot"] = json.loads(d["rec_snapshot"])
        out.append(d)
    return out


class UndoBody(BaseModel):
    history_id: int


@app.post("/api/brands/{brand_id}/history/undo")
def undo_action(brand_id: int, body: UndoBody):
    with db() as c:
        h = c.execute(
            "SELECT * FROM rec_history WHERE id=? AND brand_id=?",
            (body.history_id, brand_id)).fetchone()
        if not h:
            raise HTTPException(404, "Geri alma kaydi bulunamadi")
        snap = json.loads(h["rec_snapshot"])
        c.execute(
            "UPDATE recommendations SET status=? WHERE id=? AND brand_id=?",
            (h["old_status"], snap["id"], brand_id))
        c.execute("DELETE FROM rec_history WHERE id=?", (h["id"],))
    return {"ok": True, "restored_to": h["old_status"]}


class BidEdit(BaseModel):
    suggested_value: float


@app.put("/api/recommendations/{rec_id}/bid")
def edit_bid(rec_id: int, body: BidEdit):
    with db() as c:
        c.execute("UPDATE recommendations SET suggested_value=? WHERE id=?",
                  (round(body.suggested_value, 2), rec_id))
    return {"ok": True}


@app.get("/api/brands/{brand_id}/summary")
def summary(brand_id: int):
    with db() as c:
        camps = _load_rows(c, brand_id, "campaign")
        sts = _load_rows(c, brand_id, "search_term")
    src = camps if camps else sts
    spend = sum(r["spend"] for r in src)
    sales = sum(r["sales"] for r in src)
    orders = sum(r["orders"] for r in src)
    clicks = sum(r["clicks"] for r in src)
    top = sorted(camps, key=lambda r: -r["spend"])[:15] if camps else []
    return {
        "spend": round(spend, 2), "sales": round(sales, 2),
        "orders": int(orders), "clicks": int(clicks),
        "acos": round(spend / sales * 100, 1) if sales else None,
        "source": "campaign" if camps else ("search_term" if sts else None),
        "top_campaigns": top,
    }


TYPE_SHEETS = [
    ("harvest", "Yeni Kelimeler"),
    ("harvest_pt", "Yeni Urun Hedefleri"),
    ("negative", "Negatifler"),
    ("bid_down", "Bid Dusur"),
    ("bid_up", "Bid Artir"),
    ("placement", "Placement Ayarlari"),
]


@app.get("/api/brands/{brand_id}/export")
def export(brand_id: int, status: str = "approved"):
    with db() as c:
        brand = c.execute("SELECT name FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand:
            raise HTTPException(404, "Marka bulunamadi")
        rows = c.execute(
            "SELECT * FROM recommendations WHERE brand_id=? AND status=? ORDER BY type",
            (brand_id, status)).fetchall()
    if not rows:
        raise HTTPException(400, "Aktarilacak onayli oneri yok")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F2937")
    # OKU_ONCE sheet - net rehber
    ws0 = wb.create_sheet("OKU_ONCE")
    from openpyxl.styles import Alignment
    lines = [
        (f"MARKA: {brand['name']}", True),
        (f"Uretilme: {datetime.now():%Y-%m-%d %H:%M}", False),
        ("", False),
        ("BU DOSYA NEDIR?", True),
        ("PPC asistan tarafindan onerilen ve senin onayladigin degisikliklerin listesi.", False),
        ("Her sheet bir kategori. Sirayla uygulanmasi tavsiye edilir:", False),
        ("", False),
        ("SIRA 1 - NEGATIFLER (kanamayi durdur)", True),
        ("Amazon Ads Console -> ilgili kampanya -> Negative targeting -> ekle.", False),
        ("Kelimeler icin 'Negative Exact', ASIN'ler icin 'Negative Product Targeting'.", False),
        ("DIKKAT: Negative phrase EKLEME - istemedigin varyasyonlari da keser.", False),
        ("", False),
        ("SIRA 2 - YENI KELIMELER (Kelime Avcisi / Harvest)", True),
        ("Onerilen kelimeleri Amazon'da EXACT kampanyaya ekle.", False),
        ("YOKSA yeni bir 'MarkaAdi - Exact - Kazananlar' kampanyasi ac.", False),
        ("ONEMLI: Ayni kelimeyi kaynak kampanyada NEGATIVE EXACT olarak ekle!", False),
        ("Bu 'traffic sculpting' - yoksa iki kampanyan birbirine acik artirmaya girer.", False),
        ("", False),
        ("SIRA 3 - YENI URUN HEDEFLERI (ASIN)", True),
        ("Product Targeting kampanyana ASIN'leri ekle.", False),
        ("Kaynak Auto kampanyada bu ASIN'leri negative product yap.", False),
        ("", False),
        ("SIRA 4 - BID DEGISIKLIKLERI", True),
        ("Amazon Ads -> kampanya -> Targeting sekmesi -> kelimeyi bul -> bid guncelle.", False),
        ("'Mevcut CPC' senin gercek bid'in degil - odedigin ortalama tik ucreti.", False),
        ("Bid genelde CPC'nin biraz uzerinde. Onerilen bid = hedef ACOS icin ideal.", False),
        ("", False),
        ("SIRA 5 - PLACEMENT AYARLARI", True),
        ("Amazon Ads -> kampanya -> Settings -> Adjust bids by placement.", False),
        ("Top of search / Product pages / Rest of search icin carpan guncelle.", False),
        ("", False),
        ("GENEL KURALLAR", True),
        ("- Bid degisikligi sonrasi 7-14 gun bekle. Attribution 2-3 gun eksik.", False),
        ("- Tek seferde max %25 bid degisikligi - fazlasi algoritmayi konfuze eder.", False),
        ("- Onayladigin her degisikligi Amazon'da uyguladiginda tik at (kendin icin).", False),
        ("", False),
        ("BULKSHEET INDIRDIYSEM NE OLACAK?", True),
        ("Bulksheet .xlsx dosyasi Amazon 'Bulk Operations' sayfasina direkt yuklenir.", False),
        ("Menudeki '📦 Bulksheet' butonu ile indir - saatlik is 5 dakikaya iner.", False),
    ]
    for i, (line, bold) in enumerate(lines, 1):
        cell = ws0.cell(row=i, column=1, value=line)
        if bold:
            cell.font = Font(bold=True, size=12, color="F59E0B")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws0.column_dimensions["A"].width = 95

    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    for rtype, sheet_name in TYPE_SHEETS:
        items = by_type.get(rtype)
        if not items:
            continue
        ws = wb.create_sheet(sheet_name)
        headers = ["Kampanya", "Ad Group", "Kelime/Hedef", "Match Type",
                   "Mevcut CPC", "Onerilen Bid", "Tiklama", "Harcama",
                   "Satis", "Siparis", "ACOS %", "Aciklama"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = head_font, head_fill
        for it in items:
            m = json.loads(it["metrics"] or "{}")
            ws.append([it["campaign"], it["ad_group"], it["keyword"],
                       it["match_type"], it["current_value"],
                       it["suggested_value"], m.get("clicks"), m.get("spend"),
                       m.get("sales"), m.get("orders"), m.get("acos"),
                       it["reason"]])
        widths = [34, 24, 34, 16, 11, 13, 9, 10, 10, 9, 9, 60]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"{brand['name']}_ppc_aksiyon_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- AI Strateji + Denetci ----------

@app.post("/api/brands/{brand_id}/ai-strategy")
def ai_strategy(brand_id: int):
    """AI stratejisi uret + denetciden gecir. Sonucu DB'ye kaydet."""
    with db() as c:
        brand_row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand_row:
            raise HTTPException(404, "Marka bulunamadi")
        brand = dict(brand_row)
        sts = _load_rows(c, brand_id, "search_term")
        tgs = _load_rows(c, brand_id, "targeting")
        plc = _load_rows(c, brand_id, "placement")
        camps = _load_rows(c, brand_id, "campaign")
        rec_rows = c.execute(
            "SELECT type,campaign,ad_group,keyword,match_type,current_value,"
            "suggested_value,reason,metrics FROM recommendations "
            "WHERE brand_id=? AND status='pending'", (brand_id,)).fetchall()
    if not (sts or tgs):
        raise HTTPException(400, "Once rapor yukleyin")
    det_recs = []
    for r in rec_rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics"] or "{}")
        det_recs.append(d)

    try:
        payload = ai_agent.build_input(brand, sts, tgs, plc, camps, det_recs)
        strategy = ai_agent.generate_strategy(payload)
    except Exception as e:
        raise HTTPException(500, f"AI strateji hatasi: {e}")

    try:
        review = supervisor.review(strategy, det_recs, brand)
    except Exception as e:
        review = {
            "approved": False, "risk_level": "high",
            "summary": f"Denetci hata verdi: {e}",
            "issues": [{"severity": "critical", "location": "supervisor",
                        "problem": str(e), "fix": "Manuel incele"}],
            "safe_to_send_to_user": False,
        }

    with db() as c:
        cur = c.execute(
            "INSERT INTO ai_strategies(brand_id,created_at,strategy_json,"
            "review_json,approved,safe_to_send) VALUES(?,?,?,?,?,?)",
            (brand_id, datetime.now().isoformat(timespec="seconds"),
             json.dumps(strategy, ensure_ascii=False),
             json.dumps(review, ensure_ascii=False),
             1 if review.get("approved") else 0,
             1 if review.get("safe_to_send_to_user") else 0))
        sid = cur.lastrowid
    return {"id": sid, "strategy": strategy, "review": review}


@app.get("/api/brands/{brand_id}/ai-strategy/latest")
def ai_strategy_latest(brand_id: int):
    with db() as c:
        row = c.execute(
            "SELECT * FROM ai_strategies WHERE brand_id=? "
            "ORDER BY id DESC LIMIT 1", (brand_id,)).fetchone()
    if not row:
        return {"exists": False}
    return {
        "exists": True,
        "id": row["id"],
        "created_at": row["created_at"],
        "strategy": json.loads(row["strategy_json"]),
        "review": json.loads(row["review_json"]),
        "approved": bool(row["approved"]),
        "safe_to_send": bool(row["safe_to_send"]),
    }


@app.get("/api/brands/{brand_id}/ai-strategy/history")
def ai_strategy_history(brand_id: int):
    with db() as c:
        rows = c.execute(
            "SELECT id,created_at,approved,safe_to_send FROM ai_strategies "
            "WHERE brand_id=? ORDER BY id DESC LIMIT 20", (brand_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------- Insights (dashboard) ----------

@app.get("/api/brands/{brand_id}/bulk-readiness")
def bulk_readiness(brand_id: int):
    """Bulk indirmeye hazir miyiz kontrol et."""
    with db() as c:
        brand_row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand_row:
            raise HTTPException(404, "Marka bulunamadi")
        all_rows = []
        for rtype in ("search_term", "targeting", "campaign", "placement", "bulk_ids"):
            all_rows.extend(_load_rows(c, brand_id, rtype))
        approved_cnt = c.execute(
            "SELECT COUNT(*) c FROM recommendations WHERE brand_id=? AND status='approved'",
            (brand_id,)).fetchone()["c"]
    has_ids = any(r.get("campaign_id") for r in all_rows)
    id_coverage = 0
    if all_rows:
        with_id = sum(1 for r in all_rows if r.get("campaign_id"))
        id_coverage = round(with_id / len(all_rows) * 100, 1)
    return {
        "approved_count": approved_cnt,
        "has_campaign_ids": has_ids,
        "id_coverage_pct": id_coverage,
        "harvest_campaign_set": bool(brand_row["harvest_campaign"]),
        "ready": has_ids and approved_cnt > 0,
        "message": (
            "Hazir" if has_ids and approved_cnt > 0 else
            "Onay yok - once oneri onayla" if not approved_cnt else
            "Campaign ID yok - Amazon Ads Console > Bulk Operations > Download "
            "spreadsheet ile ID dosyasini indirip PPC Asistan'a yukle "
            "(normal performans raporlarinda ID bulunmaz, kac kere indirsen fark etmez)"
        ),
    }


@app.get("/api/brands/{brand_id}/campaign-ad-groups")
def campaign_ad_groups(brand_id: int):
    """Bulk Operations ID dosyasindan gercek kampanya/ad-group isim listesi.

    Harvest hedefi secerken kullanici elle yazip yazim hatasi yapmasin diye -
    burada donen her (kampanya, ad group) cifti garanti ID'si cozulebilir
    olandir (ayni report_rows kaynagindan geliyor, bulksheet.py'nin ID
    haritasiyla birebir tutarli)."""
    with db() as c:
        if not c.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,)).fetchone():
            raise HTTPException(404, "Marka bulunamadi")
        bulk_ids = _load_rows(c, brand_id, "bulk_ids")
    pairs = set()
    for row in bulk_ids:
        camp = (row.get("campaign") or "").strip()
        ag = (row.get("ad_group") or "").strip()
        if camp and ag and row.get("campaign_id") and row.get("ad_group_id"):
            pairs.add((camp, ag))
    by_camp = {}
    for camp, ag in sorted(pairs):
        by_camp.setdefault(camp, []).append(ag)
    return [{"campaign": c, "ad_groups": sorted(set(ags))}
            for c, ags in sorted(by_camp.items())]


@app.get("/api/brands/{brand_id}/insights")
def get_insights(brand_id: int):
    with db() as c:
        brand_row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand_row:
            raise HTTPException(404, "Marka bulunamadi")
        brand = dict(brand_row)
        sts = _load_rows(c, brand_id, "search_term")
        tgs = _load_rows(c, brand_id, "targeting")
        plc = _load_rows(c, brand_id, "placement")
        camps = _load_rows(c, brand_id, "campaign")
        uploads = [dict(r) for r in c.execute(
            "SELECT filename,report_type,row_count,uploaded_at FROM uploads "
            "WHERE brand_id=? ORDER BY id DESC LIMIT 20", (brand_id,))]
        rec_rows = c.execute(
            "SELECT type,campaign,keyword,match_type,current_value,suggested_value "
            "FROM recommendations WHERE brand_id=? AND status='pending'",
            (brand_id,)).fetchall()
    if not (sts or tgs):
        return {"empty": True}
    det_recs = [dict(r) for r in rec_rows]
    with db() as c:
        prods = [dict(r) for r in c.execute(
            "SELECT * FROM products WHERE brand_id=?", (brand_id,))]
    data = insights.dashboard(brand, sts, tgs, plc, camps, det_recs, uploads)
    data["profit"] = _profit_calc(brand, prods if prods else None)
    data["products"] = prods
    return data


# ---------- Gunluk is listesi ("bugun ne yapmaliyim?") ----------

@app.get("/api/brands/{brand_id}/today")
def today(brand_id: int):
    """Tum motorlari okuyup tek oncelikli is listesi verir."""
    ctx = _market_context(brand_id)
    brand = ctx["brand"]
    profit = _profit_calc(brand, ctx["products"] or None)

    opp = None
    if ctx["queries"]:
        opp = market_intel.analyze(
            ctx["queries"], search_terms=ctx["search_terms"], catalog=ctx["catalog"],
            basket=ctx["basket"], brand_name=brand["name"], profit=profit,
            known_brands=_split_list(brand.get("competitor_brands")),
            not_brands=_split_list(brand.get("not_brands")))
        opp["period"] = ctx["period"]

    with db() as c:
        rec_rows = [dict(r) for r in c.execute(
            "SELECT type,campaign,keyword,current_value,suggested_value,metrics "
            "FROM recommendations WHERE brand_id=? AND status='pending'", (brand_id,))]
    for r in rec_rows:
        try:
            r["metrics"] = json.loads(r.get("metrics") or "{}")
        except Exception:
            r["metrics"] = {}

    return brain.today(recs=rec_rows, opp=opp, brand=brand, has={
        "ba_query": bool(ctx["queries"]),
        "ba_catalog": bool(ctx["catalog"]),
        "economics": bool(profit),
    })


# ---------- Firsat Radari (Brand Analytics) ----------

def _split_list(s):
    return [p.strip().lower() for p in str(s or "").replace("\n", ",").split(",")
            if p.strip()]


def _market_context(brand_id):
    """Firsat analizi icin gereken tum veriyi tek yerde toplar."""
    with db() as c:
        row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Marka bulunamadi")
        brand = dict(row)
        # Ceyreklik rapor daha genis veri tabanidir; yoksa aylik ile calis
        queries = _load_rows(c, brand_id, "ba_search_query")
        period = "quarterly"
        if not queries:
            queries = _load_rows(c, brand_id, "ba_search_query_month")
            period = "monthly"
        catalog = _load_rows(c, brand_id, "ba_catalog")
        basket = _load_rows(c, brand_id, "ba_market_basket")
        sts = _load_rows(c, brand_id, "search_term")
        prods = [dict(r) for r in c.execute(
            "SELECT * FROM products WHERE brand_id=?", (brand_id,))]
    return {"brand": brand, "queries": queries, "period": period,
            "catalog": catalog, "basket": basket, "search_terms": sts,
            "products": prods}


@app.get("/api/brands/{brand_id}/opportunities")
def get_opportunities(brand_id: int, min_volume: int = 200,
                      min_relevance: float = 0.34, limit: int = 50):
    ctx = _market_context(brand_id)
    if not ctx["queries"]:
        return {
            "empty": True,
            "message": ("Brand Analytics arama terimi raporu yuklenmemis. "
                        "Seller Central > Marka > Marka Analizi > Arama Terimi "
                        "Performansi (Marka Gorunumu) raporunu indirip normal "
                        "rapor gibi yukleyin."),
        }
    brand = ctx["brand"]
    profit = _profit_calc(brand, ctx["products"] or None)
    res = market_intel.analyze(
        ctx["queries"], search_terms=ctx["search_terms"], catalog=ctx["catalog"],
        basket=ctx["basket"], brand_name=brand["name"], profit=profit,
        min_volume=min_volume, min_relevance=min_relevance, limit_per_bucket=limit,
        known_brands=_split_list(brand.get("competitor_brands")),
        not_brands=_split_list(brand.get("not_brands")))
    res["period"] = ctx["period"]
    res["profit"] = profit
    res["has_ad_data"] = bool(ctx["search_terms"])
    res["brand_lists"] = {
        "competitor_brands": _split_list(brand.get("competitor_brands")),
        "not_brands": _split_list(brand.get("not_brands")),
    }
    return res


class BrandListIn(BaseModel):
    add: list[str] = []          # rakip marka olarak isaretle
    remove: list[str] = []       # "bu marka degil" olarak isaretle


@app.post("/api/brands/{brand_id}/competitor-brands")
def edit_competitor_brands(brand_id: int, body: BrandListIn):
    """Rakip marka listesini duzenler.

    Otomatik tespit guvenilir degil (hacim/sorgu sayisi markayi jenerikten
    ayiramiyor), bu yuzden kullanici duzeltmesi asil mekanizmadir.
    """
    with db() as c:
        row = c.execute("SELECT competitor_brands,not_brands FROM brands WHERE id=?",
                        (brand_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Marka bulunamadi")
        known = set(_split_list(row["competitor_brands"]))
        nots = set(_split_list(row["not_brands"]))
        for t in body.add:
            t = t.strip().lower()
            if t:
                known.add(t)
                nots.discard(t)
        for t in body.remove:
            t = t.strip().lower()
            if t:
                nots.add(t)
                known.discard(t)
        c.execute("UPDATE brands SET competitor_brands=?,not_brands=? WHERE id=?",
                  (",".join(sorted(known)), ",".join(sorted(nots)), brand_id))
    return {"ok": True, "competitor_brands": sorted(known), "not_brands": sorted(nots)}


class OppExport(BaseModel):
    queries: list[str] = []
    bucket: str = "WHITESPACE"
    match: str = "exact"
    asin: str = ""
    sku: str = ""
    tiers: int = 3


@app.post("/api/brands/{brand_id}/opportunities/plan")
def opportunities_plan(brand_id: int, body: OppExport):
    """Secilen firsat kelimelerinden kampanya plani uretir (indirmeden once onizleme)."""
    ctx = _market_context(brand_id)
    if not ctx["queries"]:
        raise HTTPException(400, "Brand Analytics raporu yuklenmemis")
    brand = ctx["brand"]
    res = market_intel.analyze(
        ctx["queries"], search_terms=ctx["search_terms"], catalog=ctx["catalog"],
        basket=ctx["basket"], brand_name=brand["name"],
        profit=_profit_calc(brand, ctx["products"] or None),
        limit_per_bucket=500,
        known_brands=_split_list(brand.get("competitor_brands")),
        not_brands=_split_list(brand.get("not_brands")))
    pool = res["buckets"].get(body.bucket.upper(), [])
    if body.queries:
        want = {q.strip().lower() for q in body.queries}
        pool = [o for o in pool if o["query"] in want]
    if not pool:
        raise HTTPException(400, "Secilen kelimeler bu kovada bulunamadi")

    asin = body.asin.strip().upper()
    if not asin and ctx["catalog"]:
        # En cok satan ASIN'i varsayilan yap
        asin = max(ctx["catalog"], key=lambda c: c.get("purchases") or 0).get("asin", "")
    plan = market_intel.build_campaign_plan(
        pool, asin=asin, sku=body.sku.strip(), period=ctx["period"],
        match=body.match.lower(), tiers=max(1, min(body.tiers, 6)),
        campaign_prefix=f"{body.bucket.upper()}",
        negatives=[n["query"] for n in res.get("negatives", [])])
    if not plan:
        raise HTTPException(400, "Gecerli bid hesaplanamadi - marka ekonomisini kontrol edin")
    return plan


@app.post("/api/brands/{brand_id}/opportunities/export")
def opportunities_export(brand_id: int, body: OppExport):
    """Secilen firsatlari Amazon'a yuklenebilir bulksheet olarak indirir."""
    plan = opportunities_plan(brand_id, body)
    buf = launch_mod.build_bulksheet(plan)
    with db() as c:
        name = c.execute("SELECT name FROM brands WHERE id=?", (brand_id,)).fetchone()[0]
    fname = f"{name}_firsat_{body.bucket.lower()}_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- Amazon Bulksheet Export ----------

@app.get("/api/brands/{brand_id}/export-bulksheet")
def export_bulksheet(brand_id: int):
    with db() as c:
        brand = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand:
            raise HTTPException(404, "Marka bulunamadi")
        rows = c.execute(
            "SELECT * FROM recommendations WHERE brand_id=? AND status='approved'",
            (brand_id,)).fetchall()
    if not rows:
        raise HTTPException(400, "Aktarilacak onayli oneri yok")
    recs = []
    for r in rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics"] or "{}")
        recs.append(d)
    # Raw report rows'i ID map icin gec
    with db() as c:
        all_rows = []
        for rtype in ("search_term", "targeting", "campaign", "placement", "bulk_ids"):
            all_rows.extend(_load_rows(c, brand_id, rtype))
    # Pre-flight: ID map var mi kontrol et
    has_ids = any(r.get("campaign_id") for r in all_rows)
    if not has_ids:
        raise HTTPException(400,
            "Campaign ID/Ad Group ID bulunamadi. Normal performans raporlari "
            "(Search Term, Targeting, Campaign, Placement) bu ID'leri HICBIR ZAMAN "
            "icermez - kac kere yeniden indirirseniz indirin degismez. "
            "COZUM: Amazon Ads Console > Bulk operations > 'Download spreadsheet' "
            "ile ID eslemesi iceren dosyayi indirin, PPC Asistan'a normal rapor "
            "gibi surukleyip yukleyin (otomatik taninir), sonra Bulksheet'i "
            "tekrar indirin.")
    buf = bulksheet.build(recs, brand["name"], dict(brand), report_rows=all_rows)
    fname = f"{brand['name']}_amazon_bulksheet_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- AI Chat ----------

class ChatIn(BaseModel):
    message: str


@app.post("/api/brands/{brand_id}/chat")
def chat_send(brand_id: int, body: ChatIn):
    with db() as c:
        brand_row = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
        if not brand_row:
            raise HTTPException(404, "Marka bulunamadi")
        brand = dict(brand_row)
        sts = _load_rows(c, brand_id, "search_term")
        tgs = _load_rows(c, brand_id, "targeting")
        camps = _load_rows(c, brand_id, "campaign")
        history = [dict(r) for r in c.execute(
            "SELECT role,content FROM chat_messages WHERE brand_id=? "
            "ORDER BY id ASC LIMIT 40", (brand_id,))]
        now = datetime.now().isoformat(timespec="seconds")
        c.execute(
            "INSERT INTO chat_messages(brand_id,role,content,created_at) "
            "VALUES(?,?,?,?)", (brand_id, "user", body.message, now))
    with db() as c:
        plc = _load_rows(c, brand_id, "placement")
    try:
        reply = chat_mod.reply(brand, sts, tgs, camps, history, body.message,
                                placements=plc)
    except Exception as e:
        raise HTTPException(500, f"Chat hatasi: {e}")
    with db() as c:
        c.execute(
            "INSERT INTO chat_messages(brand_id,role,content,created_at) "
            "VALUES(?,?,?,?)", (brand_id, "assistant", reply,
                                datetime.now().isoformat(timespec="seconds")))
    return {"reply": reply}


@app.get("/api/brands/{brand_id}/data-summary")
def data_summary(brand_id: int):
    """Chat'e 'elimdeki veri' ozetini vermek icin."""
    with db() as c:
        sts = _load_rows(c, brand_id, "search_term")
        tgs = _load_rows(c, brand_id, "targeting")
        camps = _load_rows(c, brand_id, "campaign")
        brand = c.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
    if not brand:
        raise HTTPException(404, "Marka bulunamadi")
    return chat_mod.data_summary(dict(brand), sts, tgs, camps)


@app.get("/api/brands/{brand_id}/chat")
def chat_history(brand_id: int):
    with db() as c:
        rows = c.execute(
            "SELECT role,content,created_at FROM chat_messages WHERE brand_id=? "
            "ORDER BY id ASC LIMIT 80", (brand_id,)).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/brands/{brand_id}/chat")
def chat_clear(brand_id: int):
    with db() as c:
        c.execute("DELETE FROM chat_messages WHERE brand_id=?", (brand_id,))
    return {"ok": True}


# ---------- Products (coklu urun kar hesabi) ----------

class ProductIn(BaseModel):
    name: str = ""
    asin: str = ""
    sell_price: float = 0
    cogs: float = 0
    amazon_fee_pct: float = 0.15
    fba_fee: float = 0
    share_pct: float = 0


@app.get("/api/brands/{brand_id}/products")
def get_products(brand_id: int):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM products WHERE brand_id=? ORDER BY id",
            (brand_id,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/brands/{brand_id}/products")
def add_product(brand_id: int, body: ProductIn):
    with db() as c:
        cur = c.execute(
            "INSERT INTO products(brand_id,name,asin,sell_price,cogs,"
            "amazon_fee_pct,fba_fee,share_pct) VALUES(?,?,?,?,?,?,?,?)",
            (brand_id, body.name.strip(), body.asin.strip().upper(),
             body.sell_price, body.cogs, body.amazon_fee_pct,
             body.fba_fee, body.share_pct))
    return {"id": cur.lastrowid}


@app.put("/api/products/{pid}")
def update_product(pid: int, body: ProductIn):
    with db() as c:
        c.execute(
            "UPDATE products SET name=?,asin=?,sell_price=?,cogs=?,"
            "amazon_fee_pct=?,fba_fee=?,share_pct=? WHERE id=?",
            (body.name.strip(), body.asin.strip().upper(),
             body.sell_price, body.cogs, body.amazon_fee_pct,
             body.fba_fee, body.share_pct, pid))
    return {"ok": True}


@app.delete("/api/products/{pid}")
def delete_product(pid: int):
    with db() as c:
        c.execute("DELETE FROM products WHERE id=?", (pid,))
    return {"ok": True}


# ======================= LAUNCH (sifir urun PPC) =======================
# Chrome uzantisi buraya baglanir: urunu tani -> keyword bul -> kampanya
# plani -> bulk sheet. Mevcut "marka/rapor" akisindan bagimsizdir.

def _loose_int(v):
    """Scraping'den '1,234' / 1234.0 / '' gibi degerler gelir; 422 yerine coerce."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = "".join(ch for ch in str(v) if ch.isdigit())
    return int(digits) if digits else None


def _loose_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    cleaned = "".join(ch for ch in str(v).replace(",", ".") if ch.isdigit() or ch == ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _loose_list(v):
    """None veya tek string gelirse listeye cevir."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return v


class CompetitorIn(BaseModel):
    asin: str | None = None
    title: str | None = None
    price: float | None = None
    rating: float | None = None
    review_count: int | None = None
    bsr_rank: int | None = None
    bullets: list[str] = []
    description: str | None = None
    is_best_seller: bool = False
    is_amazon_choice: bool = False
    # Otomatik kesiften gelen sinyaller (uzanti doldurur)
    bought_past_month: int | None = None   # satis hizi
    keyword_overlap: int | None = None     # kac ana kelimede siralaniyor
    avg_rank: float | None = None          # o kelimelerde ortalama sirasi

    _c_ints = field_validator("review_count", "bsr_rank", "bought_past_month",
                              "keyword_overlap", mode="before")(_loose_int)
    _c_floats = field_validator("price", "rating", "avg_rank",
                                mode="before")(_loose_float)
    _c_lists = field_validator("bullets", mode="before")(_loose_list)


class LaunchProductIn(BaseModel):
    title: str
    asin: str | None = None
    sku: str | None = None
    price: float | None = None
    brand: str | None = None
    cogs: float | None = None
    fba_fee: float | None = None
    fee_pct: float | None = 0.15
    bullets: list[str] = []
    description: str | None = None
    rating: float | None = None
    review_count: int | None = None
    bsr: dict | None = None
    competitors: list[CompetitorIn] = []
    search_suggestions: list[str] = []
    catalog_products: list[dict] = []
    use_ai: bool = True
    bid_strategy: str = "profit"   # profit | balanced | aggressive
    measured_cpc: float | None = None  # kendi raporundan gercek ortalama CPC
    brand_id: int | None = None        # varsa markanin olculmus verisi kullanilir

    _p_ints = field_validator("review_count", mode="before")(_loose_int)
    _p_floats = field_validator(
        "price", "cogs", "fba_fee", "fee_pct", "rating", "measured_cpc",
        mode="before")(_loose_float)
    _p_lists = field_validator(
        "bullets", "search_suggestions", "catalog_products", "competitors",
        mode="before")(_loose_list)

    @field_validator("bsr", mode="before")
    @classmethod
    def _p_bsr(cls, v):
        # Scraping bazen "#1,234 in Beauty" gibi duz string dondurur.
        if v is None or isinstance(v, dict):
            return v
        return {"raw": str(v)}


@app.post("/api/launch/analyze")
def launch_analyze(body: LaunchProductIn):
    """Urun + rakiplerden keyword + kampanya plani uretir (bulk sheet DEGIL)."""
    product = {
        "title": body.title, "asin": (body.asin or "").strip().upper(),
        "sku": body.sku, "price": body.price, "brand": body.brand,
        "cogs": body.cogs, "fba_fee": body.fba_fee, "fee_pct": body.fee_pct,
        "bullets": body.bullets, "description": body.description,
        "rating": body.rating, "review_count": body.review_count,
        "bsr": body.bsr,
        "search_suggestions": body.search_suggestions,
        "catalog_products": body.catalog_products
    }
    competitors = [c.model_dump() for c in body.competitors]
    try:
        # Marka verildiyse KENDI olculmus CPC/CVR'i esas alinir.
        report_rows = None
        if body.brand_id:
            with db() as c:
                rs = c.execute(
                    "SELECT data FROM report_rows WHERE brand_id=? AND report_type='targeting'",
                    (body.brand_id,)).fetchall()
            report_rows = [json.loads(r["data"]) for r in rs] or None
        plan = launch_mod.build_plan(product, competitors, use_ai=body.use_ai,
                                     bid_strategy=body.bid_strategy,
                                     measured_cpc=body.measured_cpc,
                                     report_rows=report_rows)
    except Exception as e:
        raise HTTPException(500, f"Plan uretilemedi: {e}")
    return plan


EXT_DIR = Path(__file__).parent / "extension"


@app.get("/api/extension/files")
def extension_files():
    """Uzanti klasorundeki dosyalarin listesi (arayuzde tek tek indirmek icin)."""
    if not EXT_DIR.is_dir():
        raise HTTPException(404, "extension/ klasoru bulunamadi")
    files = sorted(p for p in EXT_DIR.rglob("*") if p.is_file()
                   and not p.name.startswith("."))
    return {"files": [{"name": str(p.relative_to(EXT_DIR)), "bytes": p.stat().st_size}
                      for p in files]}


@app.get("/api/extension/file/{name:path}")
def extension_file(name: str):
    """Tek dosyayi indir. Path traversal'a karsi klasor disina cikilamaz."""
    if not EXT_DIR.is_dir():
        raise HTTPException(404, "extension/ klasoru bulunamadi")
    target = (EXT_DIR / name).resolve()
    if not str(target).startswith(str(EXT_DIR.resolve()) + "/") or not target.is_file():
        raise HTTPException(404, "Dosya bulunamadi")
    return FileResponse(target, media_type="text/plain", filename=target.name)


@app.get("/api/extension/download")
def extension_download():
    """Uzantiyi tek .zip olarak indir -> ac -> chrome://extensions 'Load unpacked'."""
    if not EXT_DIR.is_dir():
        raise HTTPException(404, "extension/ klasoru bulunamadi")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(EXT_DIR.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                z.write(p, Path("ppc-launch-extension") / p.relative_to(EXT_DIR))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="ppc-launch-extension.zip"'})


@app.post("/api/launch/bulksheet")
def launch_bulksheet(plan: dict):
    """Analyze'den donen plani (veya elle duzenlenmis halini) bulk sheet yapar."""
    if not plan.get("campaigns"):
        raise HTTPException(400, "Plan bos - once /api/launch/analyze cagir.")
    try:
        buf = launch_mod.build_bulksheet(plan)
    except Exception as e:
        raise HTTPException(500, f"Bulk sheet uretilemedi: {e}")
    title = (plan.get("product", {}).get("brand")
             or plan.get("product", {}).get("title", "launch"))
    safe = "".join(ch for ch in title[:24] if ch.isalnum() or ch in " -_").strip() or "launch"
    fname = f"{safe}_launch_bulksheet_{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument"
        ".spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
