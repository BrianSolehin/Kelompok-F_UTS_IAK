# app.py
from flask import Flask, render_template
from flask_cors import CORS

from orders import orders_bp        # sudah ada
from supplier import supplier_bp    # <-- tambahkan import
from supplier2 import supplier2_bp  # <-- tambahkan import

app = Flask(__name__)
app.secret_key = "retail-secret-key"
CORS(app)

# REGISTER BLUEPRINTS
app.register_blueprint(orders_bp,   url_prefix="/api/orders")
app.register_blueprint(supplier_bp, url_prefix="/api/supplier")   # <-- penting
app.register_blueprint(supplier2_bp, url_prefix="/api/supplier2") # <-- penting

@app.get("/")
def index():
    return {"service": "retail", "status": "ok"}

# (opsional) route untuk menampilkan UI katalog
@app.get("/ui/supplier")
def supplier_ui():
    return render_template("supplier_ui.html")

# Debug: lihat semua route
@app.get("/__routes__")
def routes():
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
