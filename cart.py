# cart.py
from flask import Blueprint, jsonify, request, session

cart_bp = Blueprint("cart", __name__)

def _get_cart():
    return session.setdefault("cart", [])

def _save_cart(items):
    session["cart"] = items

@cart_bp.get("/")
def get_cart():
    items = _get_cart()
    total = sum((it.get("harga", 0) or 0) * (it.get("qty", 0) or 0) for it in items)
    return jsonify({"items": items, "total": int(total)})

@cart_bp.post("/add")
def add_to_cart():
    data = request.get_json(force=True) or {}
    pid = data.get("id_product")
    if pid is None:
        return jsonify({"error":"missing_id_product"}), 400
    qty = int(data.get("qty") or 1)
    if qty <= 0: qty = 1

    items = _get_cart()
    for it in items:
        if str(it.get("id_product")) == str(pid):
            it["qty"] = it.get("qty", 0) + qty
            _save_cart(items)
            return get_cart()

    items.append({
        "id_product": pid,
        "nama_product": data.get("nama_product") or "",
        "harga": int(float(data.get("harga") or 0)),
        "stok": int(data.get("stok") or 0),
        "qty": qty
    })
    _save_cart(items)
    return get_cart()

@cart_bp.post("/update")
def update_qty():
    data = request.get_json(force=True) or {}
    pid = data.get("id_product")
    qty = int(data.get("qty") or 0)

    items = _get_cart()
    new_items = []
    for it in items:
        if str(it.get("id_product")) == str(pid):
            if qty > 0:
                it["qty"] = qty
                new_items.append(it)
        else:
            new_items.append(it)
    _save_cart(new_items)
    return get_cart()

@cart_bp.post("/clear")
def clear_cart():
    _save_cart([])
    return jsonify({"ok": True})

@cart_bp.post("/bulk_add")
def bulk_add():
    """
    Body:
    {"items":[{"id_product":..,"nama_product":"..","harga":123,"stok":9,"qty":5}, ...]}
    """
    data = request.get_json(force=True) or {}
    items_in = data.get("items") or []
    if not isinstance(items_in, list) or not items_in:
        return jsonify({"error":"empty_items"}), 400

    cart = _get_cart()
    for x in items_in:
        pid = x.get("id_product")
        if pid is None:
            continue
        qty = int(x.get("qty") or 1)
        if qty <= 0:
            continue
        found = False
        for it in cart:
            if str(it.get("id_product")) == str(pid):
                it["qty"] = it.get("qty", 0) + qty
                found = True
                break
        if not found:
            cart.append({
                "id_product": pid,
                "nama_product": x.get("nama_product") or "",
                "harga": int(float(x.get("harga") or 0)),
                "stok": int(x.get("stok") or 0),
                "qty": qty
            })
    _save_cart(cart)
    return get_cart()
