# app.py
import os
import re
from decimal import Decimal

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# --- Satu-satunya instance SQLAlchemy ---
db = SQLAlchemy()


def create_app():
    """
    Struktur direktori:
    iak/uts_asli/
    ├─ app.py
    ├─ templates/
    │  ├─ template.html        (disarankan punya {% block body_extra %}{% endblock %})
    │  ├─ supplier_ui.html
    │  └─ gudang.html
    └─ static/
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "retail-secret-key"

    # CORS
    CORS(app, supports_credentials=True)

    # === Database URI (MySQL/MariaDB) ===
    # Set ENV FLASK_DB_URI kalau perlu override.
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "FLASK_DB_URI",
        "mysql+pymysql://root:@127.0.0.1:3306/retail_db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init DB
    db.init_app(app)

    # ------------------ BLUEPRINT LAIN (opsional) ------------------
    try:
        from orders import orders_bp
        app.register_blueprint(orders_bp, url_prefix="/api/orders")
    except Exception:
        pass

    try:
        from cart import cart_bp
        app.register_blueprint(cart_bp, url_prefix="/api/cart")
    except Exception:
        pass

    try:
        from supplier import supplier_bp
        app.register_blueprint(supplier_bp, url_prefix="/api/supplier")
    except Exception:
        pass

    try:
        from supplier2 import supplier2_bp
        app.register_blueprint(supplier2_bp, url_prefix="/api/supplier2")
    except Exception:
        pass

    # ========================= UI ROUTES =========================
    @app.get("/")
    def index():
        return {"service": "retail", "status": "ok"}

    # Halaman supplier utama
    @app.get("/ui")
    def ui_home():
        return render_template("supplier_ui.html")

    # ALIAS supaya /ui/supplier tidak error "template not found"
    @app.get("/ui/supplier")
    def ui_supplier_alias():
        return render_template("supplier_ui.html")

    # Halaman gudang
    @app.get("/ui/gudang")
    def ui_gudang():
        return render_template("gudang.html")

    # Render template dinamis aman (mis. /ui/nama_lain -> templates/nama_lain.html)
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

    # ===================== HELPER & KONFIG GUDANG =====================
    TABLE = "barang"  # tabel sesuai skema MariaDB kamu

    def _like(q: str) -> str:
        return f"%{q.strip()}%" if q else "%"

    def _row_to_dict(row) -> dict:
        """Konversi RowMapping -> dict + Decimal -> float untuk jsonify."""
        d = dict(row)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d

    # ========================== API GUDANG ==========================
    # GET /api/gudang?q=ikan
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

    # GET /api/gudang/stats
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

    # POST /api/gudang/restock  -> {"sku":"BRG001","qty":10,"harga_jual":26500?}
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

    # PATCH /api/gudang/<sku>  (update sebagian kolom)
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

    # ===================== ERROR HANDLERS =====================
    @app.errorhandler(404)
    def not_found(err):
        return jsonify({"error": "not found", "detail": str(err)}), 404

    @app.errorhandler(500)
    def server_error(err):
        return jsonify({"error": "internal server error", "detail": str(err)}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    # Jalankan dari folder proyek (agar templates/ & static/ terbaca)
    app.run(host="0.0.0.0", port=5000, debug=True)
