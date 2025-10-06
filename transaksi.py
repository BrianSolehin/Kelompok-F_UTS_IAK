# transaksi.py
# --- PATCH ANTI-DOUBLE-IMPORT (TIDAK UBAH app.py) ----------------------------
# Ketika menjalankan `python app.py`, modul aktif bernama "__main__".
# Baris di bawah memastikan modul yang sama bisa diimpor dengan nama "app",
# sehingga `from app import db` menunjuk ke instance yang sama (bukan salinan baru).
import sys as _sys
if "app" not in _sys.modules and "__main__" in _sys.modules:
    _sys.modules["app"] = _sys.modules["__main__"]
# -----------------------------------------------------------------------------

from flask import Blueprint, jsonify, request
from sqlalchemy import text
from app import db  # menggunakan instance SQLAlchemy dari app.py

# NOTE:
# - File ini hanya menangani API POS (tanpa UI route) untuk menghindari
#   bentrok dengan /ui/transaksi yang sudah didefinisikan di app.py.
# - Pastikan di app.py: from transaksi import pos_bp; app.register_blueprint(pos_bp)

pos_bp = Blueprint("pos", __name__)

# Tabel gudang yang dipakai untuk cek/kurangi stok
TABLE_BARANG = "barang"


def _map_metode(v: str) -> str:
    v = (v or "").strip().upper()
    return {"CASH": "cash", "QRIS": "qris", "CARD": "card"}.get(v, "cash")


# ===================== API: LIST TRANSAKSI (BARU) =====================
@pos_bp.get("/api/pos")
def pos_list():
    """
    Query params (opsional):
      - status: OPEN | PAID | VOID
      - q: cari id / customer
      - limit: default 50
    """
    status = (request.args.get("status") or "").strip().upper()
    q      = (request.args.get("q") or "").strip()
    limit  = int(request.args.get("limit") or 50)

    conds = []
    params = {"limit": limit}
    if status in {"OPEN", "PAID", "VOID"}:
        conds.append("status = :status")
        params["status"] = status
    if q:
        conds.append("(CAST(id_transaksi AS CHAR) LIKE :q OR customer_id LIKE :q)")
        params["q"] = f"%{q}%"

    where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""
    rows = db.session.execute(text(f"""
        SELECT id_transaksi, customer_id, total_harga, metode_bayar, status, tanggal
        FROM transaksi
        {where_sql}
        ORDER BY tanggal DESC, id_transaksi DESC
        LIMIT :limit
    """), params).mappings().all()

    return jsonify({"items": [dict(r) for r in rows]}), 200


# ===================== API: BUKA TRANSAKSI =====================
@pos_bp.post("/api/pos/open")
def pos_open():
    """
    Body JSON (opsional):
      { "pelanggan": "Umum", "metode": "CASH" | "QRIS" | "CARD" }
    """
    data = request.get_json(silent=True) or {}
    customer_id = (data.get("pelanggan") or "Umum").strip()
    metode_bayar = _map_metode(data.get("metode") or "CASH")

    r = db.session.execute(
        text("""
            INSERT INTO transaksi (customer_id, total_harga, metode_bayar, status)
            VALUES (:cust, 0, :metode, 'OPEN')
        """),
        {"cust": customer_id, "metode": metode_bayar}
    )
    trx_id = r.lastrowid or db.session.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    db.session.commit()

    return jsonify({"ok": True, "id_transaksi": int(trx_id)}), 200


# ===================== API: GET DETAIL TRANSAKSI =====================
@pos_bp.get("/api/pos/<int:trx_id>")
def pos_get(trx_id):
    header = db.session.execute(
        text("""
            SELECT id_transaksi, customer_id, total_harga, metode_bayar, status, tanggal
            FROM transaksi
            WHERE id_transaksi = :id
        """),
        {"id": trx_id}
    ).mappings().first()
    if not header:
        return jsonify({"error": "transaksi tidak ditemukan"}), 404

    rows = db.session.execute(
        text(f"""
            SELECT
                k.id_barang      AS sku,
                b.nama_barang    AS nama,
                k.jumlah         AS qty,
                k.harga_satuan   AS harga,
                k.total_harga    AS subtotal,
                b.quantity       AS stok
            FROM keranjang k
            JOIN {TABLE_BARANG} b ON b.id_barang = k.id_barang
            WHERE k.id_transaksi = :id
            ORDER BY k.id_keranjang
        """),
        {"id": trx_id}
    ).mappings().all()

    items = [dict(r) for r in rows]
    subtotal = sum(int(i["qty"]) * float(i["harga"]) for i in items)
    ppn = int(round(subtotal * 0.10))
    total = subtotal + ppn

    return jsonify({
        "header": dict(header),
        "items": items,
        "calc": {"subtotal": subtotal, "ppn": ppn, "total": total}
    }), 200


# ===================== API: TAMBAH ITEM =====================
@pos_bp.post("/api/pos/<int:trx_id>/items")
def pos_add_item(trx_id):
    """
    Body JSON:
      { "sku": "P001", "qty": 2, "harga": 12000 }  # harga optional (default harga_jual)
    """
    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    qty = int(data.get("qty") or 0)
    harga = data.get("harga")  # None => harga_jual

    if not sku or qty <= 0:
        return jsonify({"error": "sku/qty tidak valid"}), 400

    st = db.session.execute(
        text("SELECT status FROM transaksi WHERE id_transaksi=:id"),
        {"id": trx_id}
    ).scalar()
    if not st:
        return jsonify({"error": "transaksi tidak ditemukan"}), 404
    if st != "OPEN":
        return jsonify({"error": "transaksi sudah tidak OPEN"}), 409

    row = db.session.execute(
        text(f"SELECT harga_jual FROM {TABLE_BARANG} WHERE id_barang=:sku"),
        {"sku": sku}
    ).mappings().first()
    if not row:
        return jsonify({"error": "SKU tidak ditemukan"}), 404

    hj = float(harga if harga is not None else row["harga_jual"] or 0)

    existing = db.session.execute(
        text("""
            SELECT id_keranjang, jumlah
            FROM keranjang
            WHERE id_transaksi=:trx AND id_barang=:sku
        """),
        {"trx": trx_id, "sku": sku}
    ).mappings().first()

    if existing:
        new_qty = int(existing["jumlah"]) + qty
        db.session.execute(
            text("""
                UPDATE keranjang
                SET jumlah=:q, total_harga=:q*harga_satuan
                WHERE id_keranjang=:idk
            """),
            {"q": new_qty, "idk": existing["id_keranjang"]}
        )
    else:
        db.session.execute(
            text("""
                INSERT INTO keranjang (id_transaksi, id_barang, jumlah, harga_satuan, total_harga)
                VALUES (:trx, :sku, :q, :h, :q*:h)
            """),
            {"trx": trx_id, "sku": sku, "q": qty, "h": hj}
        )

    db.session.commit()
    return jsonify({"ok": True}), 200


# ===================== API: UPDATE/HAPUS ITEM =====================
@pos_bp.patch("/api/pos/<int:trx_id>/items/<string:sku>")
def pos_update_item(trx_id, sku):
    """
    Body JSON:
      { "qty": 5 }    # qty=0 -> hapus baris
    """
    data = request.get_json(silent=True) or {}
    qty = int(data.get("qty") or 0)

    st = db.session.execute(
        text("SELECT status FROM transaksi WHERE id_transaksi=:id"),
        {"id": trx_id}
    ).scalar()
    if not st:
        return jsonify({"error": "transaksi tidak ditemukan"}), 404
    if st != "OPEN":
        return jsonify({"error": "transaksi sudah tidak OPEN"}), 409

    if qty <= 0:
        db.session.execute(
            text("""
                DELETE FROM keranjang
                WHERE id_transaksi=:trx AND id_barang=:sku
            """),
            {"trx": trx_id, "sku": sku}
        )
    else:
        db.session.execute(
            text("""
                UPDATE keranjang
                SET jumlah=:q, total_harga=:q*harga_satuan
                WHERE id_transaksi=:trx AND id_barang=:sku
            """),
            {"q": qty, "trx": trx_id, "sku": sku}
        )

    db.session.commit()
    return jsonify({"ok": True}), 200


# ===================== API: BAYAR (CHECKOUT) =====================
@pos_bp.post("/api/pos/<int:trx_id>/pay")
def pos_pay(trx_id):
    """
    Body JSON:
      { "metode": "CASH|QRIS|CARD", "bayar": 100000 }
    - Validasi stok
    - Hitung PPN 10%
    - Kurangi stok barang
    - Update transaksi jadi PAID + simpan bayar/kembali
    """
    data = request.get_json(silent=True) or {}
    metode = _map_metode(data.get("metode") or "CASH")
    bayar = float(data.get("bayar") or 0)

    st = db.session.execute(
        text("SELECT status FROM transaksi WHERE id_transaksi=:id"),
        {"id": trx_id}
    ).scalar()
    if not st:
        return jsonify({"error": "transaksi tidak ditemukan"}), 404
    if st != "OPEN":
        return jsonify({"error": "transaksi sudah tidak OPEN"}), 409

    items = db.session.execute(
        text(f"""
            SELECT
                k.id_barang AS sku,
                k.jumlah    AS qty,
                k.harga_satuan AS harga,
                b.quantity  AS stok
            FROM keranjang k
            JOIN {TABLE_BARANG} b ON b.id_barang = k.id_barang
            WHERE k.id_transaksi = :id
        """),
        {"id": trx_id}
    ).mappings().all()
    if not items:
        return jsonify({"error": "keranjang kosong"}), 400

    kurang = []
    subtotal = 0
    for it in items:
        qty = int(it["qty"])
        subtotal += qty * float(it["harga"])
        if int(it["stok"] or 0) < qty:
            kurang.append({"sku": it["sku"], "stok": int(it["stok"] or 0), "butuh": qty})
    if kurang:
        return jsonify({"error": "stok_kurang", "detail": kurang}), 409

    ppn = int(round(subtotal * 0.10))
    total = subtotal + ppn
    if bayar < total:
        return jsonify({"error": "bayar_kurang", "total": total}), 400
    kembali = bayar - total

    try:
        # Kurangi stok gudang
        for it in items:
            db.session.execute(
                text(f"""
                    UPDATE {TABLE_BARANG}
                    SET quantity = quantity - :q, updated_at = NOW()
                    WHERE id_barang = :sku
                """),
                {"q": int(it["qty"]), "sku": it["sku"]}
            )

        # Update header transaksi
        db.session.execute(
            text("""
                UPDATE transaksi
                SET total_harga=:total, metode_bayar=:met, status='PAID',
                    bayar=:bayar, kembali=:kembali
                WHERE id_transaksi=:id
            """),
            {"total": total, "met": metode, "bayar": bayar, "kembali": kembali, "id": trx_id}
        )

        db.session.commit()
        return jsonify({
            "ok": True,
            "id_transaksi": trx_id,
            "subtotal": subtotal,
            "ppn": ppn,
            "total": total,
            "kembali": kembali
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "gagal_checkout", "detail": str(e)}), 500


# ===================== API: VOID (BATALKAN) =====================
@pos_bp.post("/api/pos/<int:trx_id>/void")
def pos_void(trx_id):
    st = db.session.execute(
        text("SELECT status FROM transaksi WHERE id_transaksi=:id"),
        {"id": trx_id}
    ).scalar()
    if not st:
        return jsonify({"error": "transaksi tidak ditemukan"}), 404
    if st != "OPEN":
        return jsonify({"error": "hanya transaksi OPEN yang bisa dibatalkan"}), 409

    db.session.execute(
        text("UPDATE transaksi SET status='VOID' WHERE id_transaksi=:id"),
        {"id": trx_id}
    )
    db.session.commit()
    return jsonify({"ok": True}), 200
