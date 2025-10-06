# orders.py
import requests
from urllib.parse import urljoin
from flask import Blueprint, request, jsonify, session

orders_bp = Blueprint("orders", __name__)

# =========================
# KONFIG: endpoint & adapter per supplier
# =========================
SUPPLIERS = {
    1: {  # SUPPLIER 1 (LAN)
        "checkout_url": "http://10.16.126.119:5000/api/retail/orders",
        "choose_distributor_url": "http://10.16.126.119:5000/api/retail/choose-distributor",
        "items_adapter": lambda cart: [
            {"product_id": int(it["id_product"]), "quantity": int(it["qty"])} for it in cart
        ],
        "payload_adapter": lambda id_retail, id_supplier, items: {
            "id_retail": str(id_retail),
            "id_supplier": str(id_supplier),
            "items": items,
        },
        "choose_payload": lambda id_order, id_distributor: {
            "id_order": int(id_order),
            "id_distributor": int(id_distributor),
        },
    },
    2: {  # SUPPLIER 2 (ngrok)
        "checkout_url": "https://gamophyllous-margit-slipperily.ngrok-free.dev/api/pesanan_retail",
        "choose_distributor_url": "https://gamophyllous-margit-slipperily.ngrok-free.dev/api/pesanan_distributor",
        "items_adapter": lambda cart: [
            {"id_product": it["id_product"], "qty": int(it["qty"])} for it in cart
        ],
        "payload_adapter": lambda id_retail, id_supplier, items: {
            "id_retail": int(id_retail),
            "id_supplier": int(id_supplier),
            "items": items,
        },
        "choose_payload": lambda id_order, id_distributor: {
            "id_order": int(id_order),
            "id_distributor": int(id_distributor),
        },
    },
}

# state sederhana untuk simpan draft callback supplier
ORDER_DRAFTS = {}  # { id_order: normalized_callback_dict }


def _get_supplier_cfg(id_supplier: int):
    cfg = SUPPLIERS.get(int(id_supplier))
    if not cfg:
        raise KeyError(f"id_supplier {id_supplier} belum dikonfigurasi")
    return cfg


# =========================
# A) CHECKOUT: kirim keranjang ke supplier
# =========================
@orders_bp.post("/checkout")
def checkout_order():
    """
    Body optional:
      {
        "id_retail": 1,          # default 1
        "id_supplier": 1 atau 2  # WAJIB
      }
    Keranjang diambil dari session["cart"] berupa list dict:
      [{"id_product": <str/int>, "qty": <int>}, ...]
    """
    data = request.get_json(silent=True) or {}
    id_retail = int(data.get("id_retail") or 1)
    id_supplier = int(data.get("id_supplier") or 0)
    if not id_supplier:
        return jsonify({"error": "id_supplier wajib"}), 400

    cart = session.get("cart", [])
    if not cart:
        return jsonify({"error": "Cart kosong"}), 400

    try:
        cfg = _get_supplier_cfg(id_supplier)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400

    # ---- Validasi khusus Supplier 1: id_product harus numerik
    if id_supplier == 1:
        for it in cart:
            try:
                int(it.get("id_product"))
                int(it.get("qty"))
            except Exception:
                return jsonify({
                    "error": "invalid_cart_for_supplier_1",
                    "detail": "Supplier 1 membutuhkan id_product numerik. Kosongkan keranjang atau pastikan semua produk dari sumber 'supplier'."
                }), 400

    items = cfg["items_adapter"](cart)
    payload = cfg["payload_adapter"](id_retail, id_supplier, items)

    # ===== Tambah callback URL supaya supplier tahu harus callback ke mana
    base = request.host_url  # contoh: "http://127.0.0.1:5000/"
    payload["callback_url"] = urljoin(base, "/api/orders/order-callback")
    payload["resi_callback_url"] = urljoin(base, "/api/orders/resi")

    print("[checkout] supplier:", id_supplier)
    print("[checkout] ->", cfg["checkout_url"])
    print("[checkout] payload:", payload)

    upstream_id = None
    try:
        r = requests.post(cfg["checkout_url"], json=payload, timeout=15)
        print("[checkout] upstream status:", r.status_code)
        print("[checkout] upstream body:", (r.text or "")[:1000])
        r.raise_for_status()
        try:
            resp = r.json()
        except ValueError:
            resp = {"message": "OK"}
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

    # ===== HOTFIX: buat/merge draft lokal jika upstream memberi id_order (PRESERVE existing)
    try:
        upstream_id = (
            (resp or {}).get("id_order")
            or (resp or {}).get("order_id")
            or (resp or {}).get("id")
        )
        if upstream_id:
            upstream_id = int(upstream_id)

            # Ambil jika sudah ada (mis. sudah diisi callback)
            existing = ORDER_DRAFTS.get(upstream_id) or {}

            # Pertahankan opsi distributor yang sudah ada (jangan direset)
            existing_opts = existing.get("distributor_options") if isinstance(existing.get("distributor_options"), list) else []

            # Merge aman: yang sudah ada dipertahankan
            ORDER_DRAFTS[upstream_id] = {
                # Prioritas data existing agar tidak hilang
                **existing,
                "id_order": upstream_id,
                "id_retail": existing.get("id_retail", id_retail),
                "id_supplier": existing.get("id_supplier", id_supplier),
                "message": existing.get("message", "Menunggu opsi distributor dari supplier…"),
                "distributor_options": existing_opts,
                "_raw": {**({"source": "local_stub_after_checkout"}), "upstream_resp": resp},
            }
            print(f"[checkout] local draft merged for order #{upstream_id}")
    except Exception as e:
        print("[checkout] failed to create/merge local draft:", repr(e))

    # bersihkan keranjang bila sukses
    session["cart"] = []
    session.modified = True

    return jsonify({
        "message": "Pesanan dikirim ke supplier",
        "id_order": int(upstream_id) if upstream_id else None,
        "order": resp
    }), 200


# =========================
# B) CALLBACK dari Supplier (draft order & opsi distributor)
#   (format lama & baru tetap didukung)
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

    # Plan A: bentuk lama (ada "ongkir" dict)
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

    # Plan B: bentuk baru (langsung "distributor_options" list)
    if not distributor_options:
        raw_opts = data.get("distributor_options")
        if isinstance(raw_opts, list):
            for v in raw_opts:
                if not isinstance(v, dict):
                    continue
                distributor_options.append({
                    "id_distributor":  v.get("id_distributor"),
                    "nama_distributor": v.get("nama_distributor"),
                    "harga_pengiriman": v.get("harga_pengiriman") or v.get("harga") or 0,
                    "estimasi": v.get("estimasi") or "-",
                    "quote_url": v.get("url"),
                    "quote_id": v.get("quote_id"),
                })

    # Ambil draft lama kalau ada (supaya bisa fallback id_supplier)
    prev = ORDER_DRAFTS.get(id_order) or {}

    normalized = {
        "id_order": id_order,
        "id_retail": data.get("id_retail") if data.get("id_retail") is not None else prev.get("id_retail"),
        "id_supplier": data.get("id_supplier") if data.get("id_supplier") is not None else prev.get("id_supplier"),
        "jumlah_item": data.get("jumlah_item"),
        "total_kuantitas": data.get("total_kuantitas"),
        "total_order": data.get("total_order"),
        "message": data.get("message"),
        "distributor_options": distributor_options,
        "_raw": data,
    }
    ORDER_DRAFTS[id_order] = normalized

    print("\n=== CALLBACK NORMALIZED ===")
    print(f"Order: {id_order} | opsi: {len(distributor_options)} | supplier: {normalized.get('id_supplier')}")
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
    d = ORDER_DRAFTS[latest_id]
    return jsonify({"id_order": latest_id, **d}), 200


@orders_bp.get("/drafts/<int:id_order>")
def get_draft(id_order: int):
    d = ORDER_DRAFTS.get(id_order)
    if not d:
        return jsonify({"error": "draft tidak ditemukan"}), 404
    return jsonify({"id_order": id_order, **d}), 200


# =========================
# D) UI pilih distributor -> relay ke supplier terkait
# =========================
@orders_bp.post("/drafts/<int:id_order>/choose")
def choose_distributor(id_order: int):
    payload = request.get_json(silent=True) or {}
    id_distributor = payload.get("id_distributor")
    if not id_distributor:
        return jsonify({"error": "id_distributor wajib"}), 400

    draft = ORDER_DRAFTS.get(id_order) or {}
    id_supplier = draft.get("id_supplier") or payload.get("id_supplier")
    if not id_supplier:
        return jsonify({"error": "id_supplier tidak diketahui (tidak ada di draft & tidak dikirim di body)"}), 400

    try:
        cfg = _get_supplier_cfg(id_supplier)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400

    upstream_payload = cfg["choose_payload"](id_order, id_distributor)
    try:
        r = requests.post(cfg["choose_distributor_url"], json=upstream_payload, timeout=15)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            data = {"message": "OK"}
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "upstream_error", "detail": str(e)}), 502

    ORDER_DRAFTS.setdefault(id_order, {})["chosen_distributor"] = int(id_distributor)
    return jsonify({"status": "success", "upstream": data}), 200


# =========================
# E) CALLBACK RESI dari Supplier
# =========================
@orders_bp.post("/resi")
def receive_resi_from_supplier():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Tidak ada data diterima"}), 400

    id_order = data.get("id_order")
    no_resi = data.get("no_resi")
    if not id_order or not no_resi:
        return jsonify({"error": "Data tidak lengkap (id_order/no_resi)"}), 400

    oid = int(id_order)
    ORDER_DRAFTS.setdefault(oid, {})
    ORDER_DRAFTS[oid]["no_resi"] = no_resi
    ORDER_DRAFTS[oid]["eta_delivery_date"] = data.get("eta_delivery_date")
    ORDER_DRAFTS[oid]["total_pembayaran"] = data.get("total_pembayaran")

    print(f"🧾 Order {id_order} - No Resi: {no_resi}")
    return jsonify({"message": "Resi diterima", **data}), 200
