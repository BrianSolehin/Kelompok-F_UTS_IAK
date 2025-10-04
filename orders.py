# orders.py
import requests
from flask import Blueprint, request, jsonify, session

orders_bp = Blueprint("orders", __name__)

# === KONFIG API UPSTREAM (supplier) ===
SUPPLIER_RETAIL_URL = "http://192.168.100.193:5000/api/pesanan_retail"         # POST kirim pesanan
SUPPLIER_CHOOSE_DISTRIBUTOR_URL = "http://192.168.100.193:5000/api/pesanan_distributor"  # POST pilih distributor

# === STATE SEDERHANA (in-memory) ===
# Simpan callback draft dari supplier: { id_order: payload_callback }
ORDER_DRAFTS = {}

# =========================
# A) CHECKOUT: kirim keranjang ke supplier
# =========================
@orders_bp.post("/checkout")
def checkout_order():
    data = request.get_json(silent=True) or {}
    id_retail = int(data.get("id_retail") or 1)
    id_supplier = int(data.get("id_supplier") or 0)
    if not id_supplier:
        return jsonify({"error": "id_supplier wajib"}), 400

    cart = session.get("cart", [])
    if not cart:
        return jsonify({"error": "Cart kosong"}), 400

    items = [{"id_product": it["id_product"], "qty": it["qty"]} for it in cart]
    payload = {"id_retail": id_retail, "id_supplier": id_supplier, "items": items}

    print("[checkout] -> supplier URL:", SUPPLIER_RETAIL_URL)
    print("[checkout] payload:", payload)
    try:
        r = requests.post(SUPPLIER_RETAIL_URL, json=payload, timeout=15)
        print("[checkout] upstream status:", r.status_code)
        print("[checkout] upstream body:", (r.text or "")[:1000])
        r.raise_for_status()

        try:
            resp = r.json()
        except ValueError:
            resp = {"message": "OK"}

        # upstream sukses -> kosongkan cart
        session["cart"] = []
        session.modified = True
        return jsonify({"message": "Pesanan dikirim ke supplier", "order": resp}), 200

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else None
        body = e.response.text[:1000] if (e.response and e.response.text) else ""
        print("[checkout][HTTPError]", status, body)
        return jsonify({"error": "upstream_http_error", "status": status, "body": body}), 502
    except requests.exceptions.ConnectionError as e:
        print("[checkout][ConnectionError]", repr(e))
        return jsonify({"error": "connection_error", "detail": str(e)}), 502
    except requests.exceptions.Timeout as e:
        print("[checkout][Timeout]", repr(e))
        return jsonify({"error": "timeout", "detail": "supplier timeout"}), 502
    except Exception as e:
        print("[checkout][UnknownError]", repr(e))
        return jsonify({"error": "unknown_upstream_error", "detail": str(e)}), 502
    """
    Body:
    {
      "id_retail": 1,
      "id_supplier": 2
    }
    Keranjang diambil dari session["cart"] (diisi via /api/cart/*).
    """
    data = request.get_json(silent=True) or {}
    id_retail = int(data.get("id_retail") or 1)
    id_supplier = int(data.get("id_supplier") or 0)
    if not id_supplier:
        return jsonify({"error": "id_supplier wajib"}), 400

    cart = session.get("cart", [])
    if not cart:
        return jsonify({"error": "Cart kosong"}), 400

    items = [{"id_product": it["id_product"], "qty": it["qty"]} for it in cart]
    payload = {
        "id_retail": id_retail,
        "id_supplier": id_supplier,
        "items": items
    }

    try:
        r = requests.post(SUPPLIER_RETAIL_URL, json=payload, timeout=15)
        r.raise_for_status()
        # supplier boleh balas json (mis. {id_order:56}) atau kosong
        try:
            resp = r.json()
        except ValueError:
            resp = {"message": "OK"}
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "upstream_error", "detail": str(e)}), 502

    # bersihkan keranjang
    session["cart"] = []
    session.modified = True

    return jsonify({"message": "Pesanan dikirim ke supplier", "order": resp}), 200

@orders_bp.get("/_ping_supplier")
def _ping_supplier():
    try:
        r = requests.get("http://192.168.100.193:5000/", timeout=5)
        return jsonify({"ok": True, "status": r.status_code}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502
        
        

# B) CALLBACK dari Supplier (draft order & opsi distributor)
# =========================
@orders_bp.post("/order-callback")
def order_callback():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Tidak ada data diterima"}), 400

    id_order = data.get("id_order")
    if id_order is None:
        return jsonify({"error": "Callback tanpa id_order"}), 400
    id_order = int(id_order)

    distributor_options = []

    # --- Plan A: bentuk lama -> dari 'ongkir' (dict) ---
    ongkir = data.get("ongkir") or {}
    if isinstance(ongkir, dict):
        for _, v in ongkir.items():
            if not isinstance(v, dict):
                continue
            rr = v.get("raw_response") or {}
            estimasi = (
                v.get("estimasi")
                or rr.get("eta_text")
                or (f"{rr.get('eta_days')} hari" if rr.get("eta_days") is not None else None)
                or rr.get("eta_delivery_date")
                or "-"
            )
            distributor_options.append({
                "id_distributor":  v.get("id_distributor") or rr.get("id_distributor"),
                "nama_distributor": v.get("nama_distributor") or rr.get("nama_distributor") or rr.get("distributor_name"),
                "harga_pengiriman": v.get("harga") or rr.get("harga_pengiriman"),
                "estimasi": estimasi,
                "quote_url": v.get("url"),
                "quote_id": rr.get("quote_id"),
            })

    # --- Plan B: bentuk baru -> supplier sudah kirim 'distributor_options' (list) ---
    if not distributor_options:
        raw_opts = data.get("distributor_options")
        if isinstance(raw_opts, list):
            for v in raw_opts:
                if not isinstance(v, dict):
                    continue
                # samakan key agar cocok dg UI
                distributor_options.append({
                    "id_distributor":  v.get("id_distributor"),
                    "nama_distributor": v.get("nama_distributor"),
                    "harga_pengiriman": v.get("harga_pengiriman") or v.get("harga") or 0,
                    "estimasi": v.get("estimasi") or "-",
                    # optional extras:
                    "quote_url": v.get("url"),
                    "quote_id": v.get("quote_id"),
                })

    normalized = {
        "id_order": id_order,
        "id_retail": data.get("id_retail"),
        "id_supplier": data.get("id_supplier"),
        "jumlah_item": data.get("jumlah_item"),
        "total_kuantitas": data.get("total_kuantitas"),
        "total_order": data.get("total_order"),
        "message": data.get("message"),
        "distributor_options": distributor_options,
        "_raw": data,  # simpan raw utk debug
    }
    ORDER_DRAFTS[id_order] = normalized

    print("\n=== CALLBACK NORMALIZED ===")
    print(f"Order: {id_order} | opsi: {len(distributor_options)}")
    for i, o in enumerate(distributor_options, 1):
        print(f"  {i}. {o.get('nama_distributor')} (ID {o.get('id_distributor')}) "
              f"- Rp{o.get('harga_pengiriman')} - {o.get('estimasi')}")
    print("===========================\n")

    return jsonify({"message": "Callback tersimpan", "status": "success"}), 200


# =========================
# C) ENDPOINT buat UI: ambil draft
# =========================
@orders_bp.get("/drafts")
def list_drafts():
    return jsonify(list(ORDER_DRAFTS.values())), 200

@orders_bp.get("/drafts/latest")
def latest_draft():
    if not ORDER_DRAFTS:
        return jsonify({"error": "belum ada draft"}), 404
    latest_id = max(ORDER_DRAFTS.keys())
    return jsonify({"id_order": latest_id, **ORDER_DRAFTS[latest_id]}), 200

@orders_bp.get("/drafts/<int:id_order>")
def get_draft(id_order: int):
    d = ORDER_DRAFTS.get(id_order)
    if not d:
        return jsonify({"error": "draft tidak ditemukan"}), 404
    # pastikan id_order ikut tampil
    return jsonify({"id_order": id_order, **d}), 200


# =========================
# D) UI pilih distributor -> relay ke supplier
# =========================
@orders_bp.post("/drafts/<int:id_order>/choose")
def choose_distributor(id_order: int):
    payload = request.get_json(silent=True) or {}
    id_distributor = payload.get('id_distributor')
    if not id_distributor:
        return jsonify({"error": "id_distributor wajib"}), 400

    upstream_payload = {"id_order": id_order, "id_distributor": int(id_distributor)}
    try:
        r = requests.post(SUPPLIER_CHOOSE_DISTRIBUTOR_URL,
                          json=upstream_payload, timeout=15)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            data = {"message": "OK"}
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "upstream_error", "detail": str(e)}), 502

    # tandai pilihan
    ORDER_DRAFTS.setdefault(id_order, {})["chosen_distributor"] = int(id_distributor)

    return jsonify({"status": "success", "upstream": data}), 200


# =========================
# E) CALLBACK RESI dari Supplier (setelah distributor terpilih)
# =========================
@orders_bp.post("/resi")
def receive_resi_from_supplier():
    """
    Supplier memanggil endpoint ini ketika resi sudah ada.
    Payload contoh:
    {
      "id_order": 56,
      "id_retail": 1,
      "no_resi": "RESI-001",
      "eta_delivery_date": "2025-10-06",
      "total_pembayaran": 90000
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Tidak ada data diterima"}), 400

    id_order = data.get('id_order')
    no_resi = data.get('no_resi')
    if not id_order or not no_resi:
        return jsonify({"error": "Data tidak lengkap (id_order/no_resi)"}), 400

    oid = int(id_order)
    ORDER_DRAFTS.setdefault(oid, {})
    ORDER_DRAFTS[oid]["no_resi"] = no_resi
    ORDER_DRAFTS[oid]["eta_delivery_date"] = data.get("eta_delivery_date")
    ORDER_DRAFTS[oid]["total_pembayaran"] = data.get("total_pembayaran")

    print(f"🧾 Order {id_order} - No Resi: {no_resi}")

    return jsonify({"message": "Resi diterima", **data}), 200
