# app.py
import os
import re
from decimal import Decimal

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# --- satu-satunya instance SQLAlchemy ---
db = SQLAlchemy()


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "retail-secret-key"

    # CORS
    CORS(app, supports_credentials=True)

    # DB URI
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "FLASK_DB_URI",
        "mysql+pymysql://root:@127.0.0.1:3306/retail_db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init DB
    db.init_app(app)

    # ------------------ REGISTER BLUEPRINTS ------------------
    try:
        from orders import orders_bp
        app.register_blueprint(orders_bp, url_prefix="/api/orders")
    except Exception as e:
        print("WARN: gagal load orders_bp:", e)

    try:
        from cart import cart_bp
        app.register_blueprint(cart_bp, url_prefix="/api/cart")
    except Exception as e:
        print("WARN: gagal load cart_bp:", e)

    try:
        from supplier import supplier_bp
        app.register_blueprint(supplier_bp, url_prefix="/api/supplier")
    except Exception as e:
        print("WARN: gagal load supplier_bp:", e)

    try:
        from supplier2 import supplier2_bp
        app.register_blueprint(supplier2_bp, url_prefix="/api/supplier2")
    except Exception as e:
        print("WARN: gagal load supplier2_bp:", e)

    # === POS / TRANSAKSI API ===
    try:
        from transaksi import pos_bp
        app.register_blueprint(pos_bp)  # rute API lengkap di transaksi.py
    except Exception as e:
        print("WARN: gagal load pos_bp:", e)

    # (opsional) receiver untuk event distributor
    try:
        from get_product import receiver_bp
        app.register_blueprint(receiver_bp)   # /api/distributor-events
    except Exception as e:
        print("WARN: gagal load receiver_bp:", e)

    # ========================= UI ROUTES =========================
    @app.get("/")
    def index():
        return {"service": "retail", "status": "ok"}

    @app.get("/ui")
    def ui_home():
        return render_template("supplier_ui.html")

    @app.get("/ui/supplier")
    def ui_supplier_alias():
        return render_template("supplier_ui.html")

    @app.get("/ui/gudang")
    def ui_gudang():
        return render_template("gudang.html")

    # Satu-satunya endpoint UI POS
    @app.get("/ui/transaksi")
    def ui_transaksi():
        return render_template("transaksi.html")

    # ========== (BARU) UI: DAFTAR TRANSAKSI ==========
    @app.get("/ui/semua-transaksi")
    def ui_semua_transaksi():
        return render_template("pesanan.html")

    # Alias opsional
    @app.get("/ui/pesanan")
    def ui_pesanan_alias():
        return render_template("pesanan.html")

    # Catch-all untuk template lain
    @app.get("/ui/<path:name>")
    def ui_by_name(name: str):
        if not re.fullmatch(r"[a-zA-Z0-9_\-\/]+", name or ""):
            return jsonify({"error": "invalid template name"}), 400

        tpl_name = name if name.endswith(".html") else f"{name}.html"

        tpl_root = (
            app.jinja_loader.searchpath[0]
            if getattr(app, "jinja_loader", None) and app.jinja_loader.searchpath
            else os.path.join(app.root_path, "templates")
        )
        tpl_root_abs = os.path.abspath(tpl_root)
        full_path = os.path.normpath(os.path.join(tpl_root_abs, tpl_name))

        if not full_path.startswith(tpl_root_abs + os.sep):
            return jsonify({"error": "template out of scope"}), 400
        if not os.path.exists(full_path):
            return jsonify({"error": "template not found", "template": tpl_name}), 404

        return render_template(tpl_name)

    # ===================== API GUDANG (pakai tabel: barang) =====================
    TABLE = "barang"

    def _like(q: str) -> str:
        return f"%{q.strip()}%" if q else "%"

    def _row_to_dict(row) -> dict:
        d = dict(row)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d

    @app.get("/api/gudang")
    def api_gudang_list():
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

    @app.get("/api/gudang/stats")
    def api_gudang_stats():
        def scalar(sql, params=None):
            res = db.session.execute(text(sql), params or {})
            v = res.scalar()
            return int(v or 0)

        total_produk = scalar(f"SELECT COUNT(*) FROM {TABLE}")
        total_stok   = scalar(f"SELECT COALESCE(SUM(quantity),0) FROM {TABLE}")
        low_stok     = scalar(f"SELECT COUNT(*) FROM {TABLE} WHERE quantity < 10")

        return jsonify({
            "total_produk": total_produk,
            "total_stok": total_stok,
            "low_stok": low_stok,
        })

    @app.post("/api/gudang/restock")
    def api_gudang_restock():
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
                    SET quantity = quantity + :qty, updated_at = NOW()
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

    @app.patch("/api/gudang/<string:sku>")
    def api_gudang_patch(sku: str):
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

    # ===================== DEBUG / HEALTH =====================
    @app.get("/__routes__")
    def routes():
        return {"routes": sorted([str(r) for r in app.url_map.iter_rules()])}

    @app.get("/__db_ping__")
    def db_ping():
        try:
            val = db.session.execute(text("SELECT 1")).scalar()
            try:
                barang_rows = db.session.execute(text("SELECT COUNT(*) FROM barang")).scalar()
            except Exception:
                barang_rows = None
            return jsonify({"db": "ok", "select1": val, "barang_rows": barang_rows}), 200
        except Exception as e:
            return jsonify({"db": "error", "detail": str(e)}), 500

    @app.errorhandler(404)
    def not_found(err):
        return jsonify({"error": "not found", "detail": str(err)}), 404

    @app.errorhandler(500)
    def server_error(err):
        return jsonify({"error": "internal server error", "detail": str(err)}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
