# app.py
from flask import Flask, render_template
from flask_cors import CORS

# Blueprints
from orders import orders_bp
from cart import cart_bp
from supplier import supplier_bp
from supplier2 import supplier2_bp

app = Flask(__name__, template_folder="templates")
app.secret_key = "retail-secret-key"  # wajib untuk session (keranjang)
CORS(app, supports_credentials=True)

# REGISTER BLUEPRINTS
app.register_blueprint(cart_bp,      url_prefix="/api/cart")      # <-- penting (keranjang)
app.register_blueprint(orders_bp,    url_prefix="/api/orders")
app.register_blueprint(supplier_bp,  url_prefix="/api/supplier")
app.register_blueprint(supplier2_bp, url_prefix="/api/supplier2")

@app.get("/")
def index():
    return {"service": "retail", "status": "ok"}

# UI katalog
@app.get("/ui/supplier")
def supplier_ui():
    return render_template("supplier_ui.html")

# Debug: lihat semua route
@app.get("/__routes__")
def routes():
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
