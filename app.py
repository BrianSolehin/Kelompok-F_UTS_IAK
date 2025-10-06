# app.py
import os
import re
from decimal import Decimal
from functools import wraps

from flask import (
    Flask, render_template, jsonify, request,
    redirect, url_for, session
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

# --- satu-satunya instance SQLAlchemy ---
db = SQLAlchemy()

USER_TABLE = "`user`"  # pakai backtick karena nama tabel 'user' bisa reserved


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "retail-secret-key")

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

    # ================== UTIL DB: USER ==================
    def _row_to_dict(row) -> dict:
        d = dict(row)
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d

    def get_user_by_username(username: str):
        sql = text(
            f"SELECT id_user, username, password, role, created_at FROM {USER_TABLE} WHERE username = :u"
        )
        return db.session.execute(sql, {"u": username}).mappings().first()

    def count_users() -> int:
        return int(db.session.execute(text(f"SELECT COUNT(*) FROM {USER_TABLE}")).scalar() or 0)

    def create_user(username: str, password_plain: str, role: str = "admin"):
        if not username or not password_plain:
            raise ValueError("username/password wajib")
        if role not in ("admin",):  # enum kamu hanya 'admin'
            role = "admin"
        if get_user_by_username(username):
            raise ValueError("username sudah terpakai")

        pwd_hash = generate_password_hash(password_plain)
        sql = text(f"""
            INSERT INTO {USER_TABLE} (username, password, role)
            VALUES (:u, :p, :r)
        """)
        db.session.execute(sql, {"u": username, "p": pwd_hash, "r": role})
        db.session.commit()

    # ================== SEED ADMIN OPSIONAL ==================
    with app.app_context():
        try:
            if count_users() == 0:
                seed_user = os.getenv("ADMIN_USER", "admin")
                seed_pass = os.getenv("ADMIN_PASS", "admin123")
                create_user(seed_user, seed_pass, "admin")
                print(f"[SEED] admin default dibuat: {seed_user} / (hidden)")
        except Exception as e:
            print("[SEED] dilewati:", e)

    # ================== AUTH GUARD ==================
    def login_required(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                return redirect(url_for("login_page"))
            return view_func(*args, **kwargs)
        return wrapped

    # ================== LOGIN (SERVER-RENDER) ==================
    @app.get("/login")
    def login_page():
        if session.get("user"):
            return redirect(url_for("ui_home"))
        # bisa terima error via query ?error=...
        error = request.args.get("error")
        return render_template("login.html", error=error)

    @app.post("/login")
    def login_submit():
        """Menerima form POST seperti di HTML kamu: action='/login'."""
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        try:
            row = get_user_by_username(username)
            if not row:
                # render kembali dengan error
                return render_template("login.html", error="User tidak ditemukan"), 401

            if not check_password_hash(row["password"], password):
                return render_template("login.html", error="Password salah"), 401

            session["user"] = {
                "id_user": row["id_user"],
                "username": row["username"],
                "role": row["role"],
            }
            return redirect(url_for("ui_home"))
        except Exception as e:
            return render_template("login.html", error=f"Gagal login: {e}"), 500

    @app.post("/logout")
    def logout_submit():
        session.clear()
        return redirect(url_for("login_page"))

    # ================== REGISTER (SERVER-RENDER) ==================
    @app.get("/register")
    def register_page():
        if session.get("user"):
            return redirect(url_for("ui_home"))
        error = request.args.get("error")
        return render_template("register.html", error=error)

    @app.post("/register")
    def register_submit():
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        confirm  = (request.form.get("confirm")  or "").strip()

        if not username or not password:
            return render_template("register.html", error="Username & password wajib"), 400
        if password != confirm:
            return render_template("register.html", error="Konfirmasi password tidak cocok"), 400

        try:
            create_user(username, password, "admin")
            # setelah sukses, arahkan ke login
            return redirect(url_for("login_page"))
        except ValueError as ve:
            return render_template("register.html", error=str(ve)), 400
        except Exception as e:
            db.session.rollback()
            return render_template("register.html", error=f"Gagal register: {e}"), 500

    # ================= REGISTER BLUEPRINTS =================
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

    try:
        from transaksi import pos_bp
        app.register_blueprint(pos_bp)
    except Exception as e:
        print("WARN: gagal load pos_bp:", e)

    try:
        from get_product import receiver_bp
        app.register_blueprint(receiver_bp)
    except Exception as e:
        print("WARN: gagal load receiver_bp:", e)

    # ========================= ROOT / =========================
    @app.get("/")
    def root():
        # belum login -> ke /login, sudah -> /ui
        if not session.get("user"):
            return redirect(url_for("login_page"))
        return redirect(url_for("ui_home"))

    # ========================= UI ROUTES =========================
    @app.get("/ui")
    @login_required
    def ui_home():
        return render_template("supplier_ui.html")

    @app.get("/ui/supplier")
    @login_required
    def ui_supplier_alias():
        return render_template("supplier_ui.html")

    @app.get("/ui/gudang")
    @login_required
    def ui_gudang():
        return render_template("gudang.html")

    @app.get("/ui/transaksi")
    @login_required
    def ui_transaksi():
        return render_template("transaksi.html")

    @app.get("/ui/semua-transaksi")
    @login_required
    def ui_semua_transaksi():
        return render_template("pesanan.html")

    @app.get("/ui/pesanan")
    @login_required
    def ui_pesanan_alias():
        return render_template("pesanan.html")

    @app.get("/ui/history")
    @login_required
    def ui_history():
        return render_template("history.html")

    @app.get("/ui/<path:name>")
    @login_required
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

    # ===================== API GUDANG =====================
    TABLE = "barang"

    def _like(q: str) -> str:
        return f"%{q.strip()}%" if q else "%"

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

    # ===================== HISTORY =====================
    @app.get("/api/history/resi")
    def api_history_resi():
        rows = db.session.execute(text("""
            SELECT no_resi, id_barang, nama_barang, quantity, nama_supplier, nama_distributor, status, tanggal
            FROM resi
            WHERE status = 'DELIVERED'
            ORDER BY tanggal DESC
            LIMIT 100
        """)).mappings().all()
        return jsonify({"items": [dict(r) for r in rows]})

    @app.get("/api/history/transaksi")
    def api_history_transaksi():
        rows = db.session.execute(text("""
            SELECT id_transaksi, tanggal, customer_id, total_harga, metode_bayar, status, bayar, kembali
            FROM transaksi
            WHERE status = 'PAID'
            ORDER BY tanggal DESC
            LIMIT 100
        """)).mappings().all()
        return jsonify({"items": [dict(r) for r in rows]})

    # ===================== DEBUG =====================
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
