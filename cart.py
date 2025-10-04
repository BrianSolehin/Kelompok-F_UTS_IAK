# cart.py
from flask import Blueprint, request, jsonify, session

cart_bp = Blueprint("cart", __name__)

# gunakan session untuk simpan keranjang (per user)
def _get_cart():
    return session.setdefault("cart", [])

def _save_cart(cart):
    session["cart"] = cart
    session.modified = True

@cart_bp.get("/")
def cart_view():
    cart = _get_cart()
    total = sum((it.get("harga", 0) or 0) * (it.get("qty", 1) or 0) for it in cart)
    return jsonify({"items": cart, "total": total})

@cart_bp.post("/add")
def cart_add():
    data = request.get_json(silent=True) or {}
    if not data.get("id_product"):
        return jsonify({"error": "id_product wajib"}), 400
    cart = _get_cart()

    # cek kalau barang sudah ada → update qty
    for it in cart:
        if str(it["id_product"]) == str(data["id_product"]):
            it["qty"] += int(data.get("qty", 1))
            _save_cart(cart)
            return jsonify({"message": "updated"}), 200

    cart.append({
        "id_product": data["id_product"],
        "nama_product": data.get("nama_product"),
        "harga": int(data.get("harga") or 0),
        "stok": int(data.get("stok") or 0),
        "qty": int(data.get("qty") or 1),
    })
    _save_cart(cart)
    return jsonify({"message": "added"}), 200

@cart_bp.post("/bulk_add")
def cart_bulk_add():
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    cart = _get_cart()
    for new_item in items:
        found = False
        for it in cart:
            if str(it["id_product"]) == str(new_item["id_product"]):
                it["qty"] += int(new_item.get("qty", 1))
                found = True
                break
        if not found:
            cart.append({
                "id_product": new_item.get("id_product"),
                "nama_product": new_item.get("nama_product"),
                "harga": int(new_item.get("harga") or 0),
                "stok": int(new_item.get("stok") or 0),
                "qty": int(new_item.get("qty") or 1),
            })
    _save_cart(cart)
    return jsonify({"message": "bulk added"}), 200

@cart_bp.post("/update")
def cart_update():
    data = request.get_json(silent=True) or {}
    id_product = data.get("id_product")
    qty = int(data.get("qty", 0))
    cart = _get_cart()
    for it in cart:
        if str(it["id_product"]) == str(id_product):
            if qty <= 0:
                cart.remove(it)
            else:
                it["qty"] = qty
            break
    _save_cart(cart)
    return jsonify({"message": "updated"}), 200

@cart_bp.post("/clear")
def cart_clear():
    _save_cart([])
    return jsonify({"message": "cleared"}), 200
