"""PPC Asistan - Amazon reklam raporu analiz araci.
Calistir: .venv/bin/uvicorn app:app --port 8642
"""
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import parsers
import analysis
import ai_agent
import supervisor
import insights
import bulksheet
import chat as chat_mod

DB_PATH = Path(__file__).parent / "ppc.db"
app = FastAPI(title="PPC Asistan")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
            fba_fee REAL DEFAULT 0);
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
        ]:
            if col not in cols:
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
                "amazon_fee_pct,fba_fee) VALUES(?,?,?,?,?,?,?,?,?)",
                (body.name.strip(), body.target_acos, body.min_clicks_neg,
                 body.min_orders_harvest, body.bid_change_cap,
                 body.sell_price, body.cogs, body.amazon_fee_pct, body.fba_fee))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Bu isimde marka zaten var")
        return {"id": cur.lastrowid}


@app.put("/api/brands/{brand_id}")
def update_brand(brand_id: int, body: BrandIn):
    with db() as c:
        c.execute(
            "UPDATE brands SET name=?,target_acos=?,min_clicks_neg=?,"
            "min_orders_harvest=?,bid_change_cap=?,sell_price=?,cogs=?,"
            "amazon_fee_pct=?,fba_fee=? WHERE id=?",
            (body.name.strip(), body.target_acos, body.min_clicks_neg,
             body.min_orders_harvest, body.bid_change_cap,
             body.sell_price, body.cogs, body.amazon_fee_pct, body.fba_fee,
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
        recs = analysis.run_all(dict(brand), sts, tgs, plc)
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
            c.execute(
                "INSERT INTO recommendations(brand_id,type,campaign,ad_group,keyword,"
                "match_type,current_value,suggested_value,reason,metrics) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (brand_id, r["type"], r["campaign"], r["ad_group"], r["keyword"],
                 r["match_type"], r["current_value"], r["suggested_value"],
                 r["reason"], json.dumps(r["metrics"])))


@app.post("/api/brands/{brand_id}/upload")
async def upload(brand_id: int, files: list[UploadFile]):
    results = []
    with db() as c:
        if not c.execute("SELECT 1 FROM brands WHERE id=?", (brand_id,)).fetchone():
            raise HTTPException(404, "Marka bulunamadi")
        for f in files:
            content = await f.read()
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


# ---------- Amazon Bulksheet Export ----------

@app.get("/api/brands/{brand_id}/export-bulksheet")
def export_bulksheet(brand_id: int):
    with db() as c:
        brand = c.execute("SELECT name FROM brands WHERE id=?", (brand_id,)).fetchone()
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
    buf = bulksheet.build(recs, brand["name"])
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
