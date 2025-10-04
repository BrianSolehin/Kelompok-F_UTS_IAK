# orders.py
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, session

orders_bp = Blueprint("orders", __name__)

# ====== CONFIG ======
WEBHOOK_TOKEN = "sama-token-di-kedua-sisi"

SUPPLIER_URLS = {
    1: "http://192.168.0.29:8000/api/orders",
    2: "http://192.168.0.214:8000/api/orders"
}

# helper untuk push order ke supplier
def _push(url, payload):
    try:
        r = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json", "X-Webhook-Token": WEBHOOK_TOKEN},
            timeout=5
        )
        print("[PUSH]", url, r.status_code)
        return r.json() if r.ok else {"error": r.text}
    except Exception as e:
        print("[ERR PUSH]", url, e)
        return {"error": str(e)}

# ====== ENDPOINT CHECKOUT ======
@orders_bp.post("/checkout")
def checkout_cart():
    data = request.get_json(force=True) or {}
    id_retail   = data.get("id_retail")
    id_supplier = data.get("id_supplier")
    items       = data.get("items", [])

    if not id_retail or not id_supplier:
        return jsonify({"error": "missing id_retail or id_supplier"}), 400
    if not items:
        return jsonify({"error": "cart_empty"}), 400

    # buat order baru
    order_id = session.get("order_seq", 0) + 1
    session["order_seq"] = order_id

    callback_url = request.host_url.rstrip("/") + "/api/orders/callback"

    record = {
        "order_id": order_id,
        "id_retail": id_retail,
        "id_supplier": id_supplier,
        "items": items,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "CREATED",
        "callback_url": callback_url
    }

    # simpan ke session (sementara jadi DB)
    orders = session.get("orders", [])
    orders.append(record)
    session["orders"] = orders

    # push ke supplier
    sup_url = SUPPLIER_URLS.get(int(id_supplier))
    if sup_url:
        _push(sup_url, record)

    return jsonify({"ok": True, "order": record}), 201

# ====== ENDPOINT CALLBACK (supplier nembak balik ke sini) ======
@orders_bp.post("/callback")
def supplier_callback():
    token = request.headers.get("X-Webhook-Token")
    if token != WEBHOOK_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True) or {}
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": "missing order_id"}), 400

    orders = session.get("orders", [])
    updated = False
    for o in orders:
        if o.get("order_id") == order_id:
            o.update(data)   # merge data callback ke order
            updated = True
            break

    if not updated:
        # kalau belum ada ordernya, simpan baru
        orders.append(data)

    session["orders"] = orders
    print("📦 Callback dari Supplier diterima:", data)
    return jsonify({"ok": True, "stored": True})

# ====== ENDPOINT GET ORDER ======
@orders_bp.get("/<int:order_id>")
def get_order(order_id):
    orders = session.get("orders", [])
    for o in orders:
        if o.get("order_id") == order_id:
            return jsonify(o)
    return jsonify({"error": "not_found"}), 404

# ====== ENDPOINT LIST ORDER ======
@orders_bp.get("/")
def list_orders():
    return jsonify(session.get("orders", []))
