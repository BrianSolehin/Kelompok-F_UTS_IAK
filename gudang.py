# gudang.py
from flask import Blueprint, request, jsonify
from sqlalchemy import text
from app import db  # memakai instance db dari app.py

gudang_bp = Blueprint("gudang", __name__)
TABLE = "barang"  # <- tabel rujukan

def _like(q: str) -> str:
    return f"%{q.strip()}%" if q else "%"

def _row_to_dict(row) -> dict:
    # row: sqlalchemy RowMapping -> dict + cast Decimal ke float/int
    d = dict(row)
    for k, v in list(d.items()):
        # cast Decimal -> float; int biarkan int
        try:
            from decimal import Decimal
            if isinstance(v, Decimal):
                d[k] = float(v)
        except Exception:
            pass
    return d

# =================== LIST + SEARCH ===================
# GET /api/gudang?q=ikan
@gudang_bp.get("/api/gudang")
def list_gudang():
    q = (request.args.get("q") or "").strip()
    rows = db.session.execute(
        text(f"""
            SELECT
                id_barang      AS sku,
                nama_barang    AS nama_product,
                id_supplier    AS id_supplier,
                quantity       AS stok,
                harga_jual     AS harga_jual,
                harga_supplier AS harga_supplier,
                berat          AS berat,
                updated_at     AS last_restock
            FROM {TABLE}
            WHERE (:q = '' OR id_barang LIKE :q_like OR nama_barang LIKE :q_like)
            ORDER BY nama_barang
        """),
        {"q": q, "q_like": _like(q)}
    ).mappings().all()
    items = [_row_to_dict(r) for r in rows]
    return jsonify({"items": items})

# =================== SUMMARY ===================
# GET /api/gudang/stats
@gudang_bp.get("/api/gudang/stats")
def gudang_stats():
    def scalar(sql, params=None):
        res = db.session.execute(text(sql), params or {})
        val = res.scalar()
        return int(val or 0)

    total_produk = scalar(f"SELECT COUNT(*) FROM {TABLE}")
    total_stok   = scalar(f"SELECT COALESCE(SUM(quantity),0) FROM {TABLE}")
    low_stok     = scalar(f"SELECT COUNT(*) FROM {TABLE} WHERE quantity < 10")

    return jsonify({
        "total_produk": total_produk,
        "total_stok": total_stok,
        "low_stok": low_stok,
    })

# =================== RESTOCK ===================
# POST /api/gudang/restock
# body: { "sku": "SY001", "qty": 10, "harga_jual": 26500 (opsional) }
@gudang_bp.post("/api/gudang/restock")
def restock_gudang():
    data = request.get_json(silent=True) or {}
    sku  = (data.get("sku") or data.get("id_barang") or "").strip()
    qty  = int(data.get("qty") or 0)
    harga_jual = data.get("harga_jual", None)

    if not sku or qty <= 0:
        return jsonify({"error": "sku dan qty>0 wajib"}), 400

    try:
        if harga_jual is None:
            sql = text(f"""
                UPDATE {TABLE}
                SET quantity = quantity + :qty,
                    updated_at = NOW()
                WHERE id_barang = :sku
            """)
            params = {"qty": qty, "sku": sku}
        else:
            sql = text(f"""
                UPDATE {TABLE}
                SET quantity = quantity + :qty,
                    harga_jual = :harga_jual,
                    updated_at = NOW()
                WHERE id_barang = :sku
            """)
            params = {"qty": qty, "sku": sku, "harga_jual": int(harga_jual)}

        res = db.session.execute(sql, params)
        db.session.commit()

        if res.rowcount == 0:
            return jsonify({"error": f"SKU {sku} tidak ditemukan"}), 404

        row = db.session.execute(
            text(f"""
                SELECT
                    id_barang AS sku, nama_barang AS nama_product, id_supplier,
                    quantity AS stok, harga_jual, harga_supplier, berat, updated_at AS last_restock
                FROM {TABLE}
                WHERE id_barang = :sku
            """),
            {"sku": sku}
        ).mappings().first()
        return jsonify({"updated": _row_to_dict(row)}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "gagal restock", "detail": str(e)}), 500

# =================== PATCH ===================
# PATCH /api/gudang/<sku>   (update sebagian kolom)
# contoh body: {"nama_barang":"Broccoli 1kg","quantity":520,"harga_jual":26500}
@gudang_bp.patch("/api/gudang/<string:sku>")
def patch_gudang(sku: str):
    data = request.get_json(silent=True) or {}
    fields, params = [], {"sku": sku}

    if "nama_barang" in data and data["nama_barang"]:
        fields.append("nama_barang = :nama_barang")
        params["nama_barang"] = data["nama_barang"]

    if "id_supplier" in data and data["id_supplier"] is not None:
        fields.append("id_supplier = :id_supplier")
        params["id_supplier"] = int(data["id_supplier"])

    if "harga_jual" in data and data["harga_jual"] is not None:
        fields.append("harga_jual = :harga_jual")
        params["harga_jual"] = int(data["harga_jual"])

    if "harga_supplier" in data and data["harga_supplier"] is not None:
        fields.append("harga_supplier = :harga_supplier")
        params["harga_supplier"] = int(data["harga_supplier"])

    if "quantity" in data and data["quantity"] is not None:
        fields.append("quantity = :quantity")
        params["quantity"] = int(data["quantity"])

    if "berat" in data and data["berat"] is not None:
        fields.append("berat = :berat")
        params["berat"] = float(data["berat"])

    if not fields:
        return jsonify({"error": "tidak ada field yang diupdate"}), 400

    try:
        sql = text(f"""
            UPDATE {TABLE}
            SET {', '.join(fields)}, updated_at = NOW()
            WHERE id_barang = :sku
        """)
        res = db.session.execute(sql, params)
        db.session.commit()

        if res.rowcount == 0:
            return jsonify({"error": f"SKU {sku} tidak ditemukan"}), 404

        row = db.session.execute(
            text(f"""
                SELECT
                    id_barang AS sku, nama_barang AS nama_product, id_supplier,
                    quantity AS stok, harga_jual, harga_supplier, berat, updated_at AS last_restock
                FROM {TABLE}
                WHERE id_barang = :sku
            """), {"sku": sku}
        ).mappings().first()
        return jsonify({"updated": _row_to_dict(row)}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "gagal update", "detail": str(e)}), 500
