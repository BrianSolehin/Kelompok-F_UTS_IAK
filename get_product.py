# get_product.py
from flask import Blueprint, request, jsonify
import json
from datetime import datetime
from sqlalchemy import text
from app import db

receiver_bp = Blueprint("receiver", __name__)

# =========================
#  A. Webhook dari distributor (event status pengiriman)
#  - Mencatat SEMUA status ke tabel `resi` (UPSERT berdasarkan no_resi+id_barang)
#  - Menambah stok barang HANYA saat status berubah menjadi DELIVERED
# =========================
@receiver_bp.route("/api/distributor-events", methods=["POST"])
def distributor_events():
    try:
        evt = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "invalid json"}), 400

    print("\n=== [EVENT RECEIVED] ===")
    try:
        print(json.dumps(evt, indent=2, ensure_ascii=False))
    except Exception:
        print(evt)
    print("========================\n")

    data = evt.get("data") or {}
    no_resi = (data.get("no_resi") or "").strip()
    status_now = (data.get("status_now") or "").upper().strip()
    order = data.get("order") or {}
    items = data.get("items") or []

    nama_supplier = order.get("supplier") or ""
    nama_distributor = order.get("distributor") or ""

    # safety: tanpa no_resi, kita tidak bisa tracking
    if not no_resi:
        return jsonify({"status": "ignored", "reason": "no_resi empty"}), 200

    # Proses setiap item di resi
    for it in items:
        id_barang = it["id_barang"]
        nama_barang = it["nama_barang"]
        qty = int(it["kuantitas"])

        # Ambil status sebelumnya (kalau ada) untuk deteksi transisi -> DELIVERED
        prev_status = db.session.execute(text("""
            SELECT status FROM resi
            WHERE no_resi = :no_resi AND id_barang = :id_barang
            LIMIT 1
        """), {"no_resi": no_resi, "id_barang": id_barang}).scalar()

        # UPSERT catatan tracking ke tabel resi
        db.session.execute(text("""
            INSERT INTO resi (
                no_resi, id_barang, nama_barang, quantity, nama_supplier, nama_distributor, status, tanggal
            ) VALUES (
                :no_resi, :id_barang, :nama_barang, :quantity, :nama_supplier, :nama_distributor, :status, NOW()
            )
            ON DUPLICATE KEY UPDATE
                nama_barang      = VALUES(nama_barang),
                quantity         = VALUES(quantity),
                nama_supplier    = VALUES(nama_supplier),
                nama_distributor = VALUES(nama_distributor),
                status           = VALUES(status),
                tanggal          = NOW()
        """), {
            "no_resi": no_resi,
            "id_barang": id_barang,
            "nama_barang": nama_barang,
            "quantity": qty,
            "nama_supplier": nama_supplier,
            "nama_distributor": nama_distributor,
            "status": status_now
        })

        # Tambah stok hanya sekali saat transisi ke DELIVERED
        if status_now == "DELIVERED" and (prev_status is None or prev_status != "DELIVERED"):
            db.session.execute(text("""
                UPDATE barang
                SET quantity = quantity + :q, updated_at = NOW()
                WHERE id_barang = :id_barang
            """), {"q": qty, "id_barang": id_barang})

    db.session.commit()

    ts = datetime.utcnow().isoformat()
    return jsonify({
        "status": "ok",
        "received_at": ts,
        "no_resi": no_resi,
        "status_now": status_now
    }), 200


# =========================
#  B. API untuk halaman Tracking (UI)
# =========================

# List resi aktif (semua yang belum DELIVERED)
@receiver_bp.get("/api/tracking/active")
def tracking_active():
    rows = db.session.execute(text("""
        SELECT no_resi, id_barang, nama_barang, quantity, nama_supplier, nama_distributor, status, tanggal
        FROM resi
        WHERE status <> 'DELIVERED'
        ORDER BY tanggal DESC
    """)).mappings().all()
    return jsonify({"items": [dict(r) for r in rows]}), 200


# Detail satu resi (untuk tombol "Cek Status")
@receiver_bp.get("/api/tracking/<string:no_resi>")
def tracking_detail(no_resi: str):
    rows = db.session.execute(text("""
        SELECT no_resi, id_barang, nama_barang, quantity, nama_supplier, nama_distributor, status, tanggal
        FROM resi
        WHERE no_resi = :no_resi
        ORDER BY tanggal DESC
    """), {"no_resi": no_resi}).mappings().all()
    return jsonify({"items": [dict(r) for r in rows]}), 200


# Tandai DELIVERED secara manual (untuk tombol "Tandai DELIVERED" / "Terima Barang")
@receiver_bp.post("/api/tracking/mark-delivered")
def tracking_mark_delivered():
    payload = request.get_json(silent=True) or {}
    no_resi = (payload.get("no_resi") or "").strip()
    if not no_resi:
        return jsonify({"error": "no_resi wajib"}), 400

    items = db.session.execute(text("""
        SELECT id_barang, quantity, status
        FROM resi
        WHERE no_resi = :no_resi
    """), {"no_resi": no_resi}).mappings().all()

    if not items:
        return jsonify({"error": "resi tidak ditemukan"}), 404

    # Update ke DELIVERED; tambah stok hanya untuk yang belum delivered
    for r in items:
        if r["status"] != "DELIVERED":
            db.session.execute(text("""
                UPDATE resi
                SET status = 'DELIVERED', tanggal = NOW()
                WHERE no_resi = :no_resi AND id_barang = :id_barang
            """), {"no_resi": no_resi, "id_barang": r["id_barang"]})

            db.session.execute(text("""
                UPDATE barang
                SET quantity = quantity + :q, updated_at = NOW()
                WHERE id_barang = :id_barang
            """), {"q": int(r["quantity"]), "id_barang": r["id_barang"]})

    db.session.commit()
    return jsonify({"status": "ok", "no_resi": no_resi}), 200
