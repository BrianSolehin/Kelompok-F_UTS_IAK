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
        "checkout_url": "https://intervascular-harmony-unministrant.ngrok-free.dev/api/retail/orders",
        "choose_distributor_url": "https://intervascular-harmony-unministrant.ngrok-free.dev/api/retail/choose-distributor",
        "items_adapter": lambda cart: [
            {"product_id": int(it["id_product"]), "quantity": int(it["qty"])} for it in cart
        ],
        "payload_adapter": lambda id_retail, id_supplier, items: {
            "id_retail": str(id_retail),
            "id_supplier": int(id_supplier),
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


def _extract_distributor_options_from_payload(data: dict):
    """
    Terima bentuk data dari supplier:
      - Format baru: {"distributor_options": [{...}, {...}]}
      - Format lama: {"ongkir": {"1": {...}, "2": {...}}}
    Return list opsi distributor yang sudah dinormalisasi untuk UI.
    """
    options = []
    if not isinstance(data, dict):
        return options

    # -------- Format baru: langsung list ----------
    raw_opts = data.get("distributor_options")
    if isinstance(raw_opts, list) and raw_opts:
        for v in raw_opts:
            if not isinstance(v, dict):
                continue
            options.append({
                "id_distributor":   v.get("id_distributor"),
                "nama_distributor": v.get("nama_distributor") or v.get("name"),
                "harga_pengiriman": v.get("harga_pengiriman") or v.get("harga") or 0,
                "estimasi":         v.get("estimasi") or v.get("eta_text") or v.get("eta_delivery_date") or "-",
                "quote_url":        v.get("url"),
                "quote_id":         v.get("quote_id"),
            })

    # -------- Format lama: dict ongkir ----------
    if not options and isinstance(data.get("ongkir"), dict):
        ongkir = data["ongkir"]
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
            options.append({
                "id_distributor":   v.get("id_distributor") or rr.get("id_distributor"),
                "nama_distributor": v.get("nama_distributor") or rr.get("nama_distributor") or rr.get("distributor_name"),
                "harga_pengiriman": v.get("harga") or rr.get("harga_pengiriman") or 0,
                "estimasi":         estimasi,
                "quote_url":        v.get("url"),
                "quote_id":         rr.get("quote_id"),
            })
    return options


def _merge_resi_into_draft(id_order: int, upstream: dict):
    """
    Ambil info resi/total/ETA dari response supplier dan simpan ke draft.
    Dipakai saat choose_distributor (dan bisa dipakai saat checkout bila perlu).
    """
    oid = int(id_order)
    d = ORDER_DRAFTS.setdefault(oid, {})
    if not isinstance(upstream, dict):
        upstream = {}

    # Normalisasi berbagai kemungkinan nama field
    no_resi = (
        upstream.get("no_resi")
        or upstream.get("resi")
        or upstream.get("tracking_number")
        or upstream.get("trackingNo")
    )
    if no_resi:
        d["no_resi"] = no_resi

    total = upstream.get("total_pembayaran")
    if total is None:
        total = upstream.get("total") or upstream.get("amount")
    if total is not None:
        d["total_pembayaran"] = total

    eta = (
        upstream.get("eta_delivery_date")
        or upstream.get("eta_text")
        or upstream.get("eta")
        or upstream.get("estimated_delivery")
    )
    if eta:
        d["eta_delivery_date"] = eta

    # simpan raw untuk debug
    raw = d.get("_raw", {})
    raw["choose_resp"] = upstream
    d["_raw"] = raw


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
    base = request.host_url  # contoh: "127.0.0.1:5000/"
    payload["callback_url"] = urljoin(base, "/api/orders/order-callback")
    payload["resi_callback_url"] = urljoin(base, "/api/orders/resi")

    print("[checkout] supplier:", id_supplier)
    print("[checkout] ->", cfg["checkout_url"])
    print("[checkout] payload:", payload)

    upstream_resp = {}
    upstream_id = None
    try:
        r = requests.post(cfg["checkout_url"], json=payload, timeout=15)
        print("[checkout] upstream status:", r.status_code)
        print("[checkout] upstream body:", (r.text or "")[:1000])
        r.raise_for_status()
        try:
            upstream_resp = r.json()
        except ValueError:
            upstream_resp = {"message": "OK"}
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

    # ===== Merge draft lokal: isi opsi distributor (dan resi jika ada) dari response checkout
    try:
        upstream_id = (
            (upstream_resp or {}).get("id_order")
            or (upstream_resp or {}).get("order_id")
            or (upstream_resp or {}).get("id")
        )
        if upstream_id:
            upstream_id = int(upstream_id)

            # Ambil jika sudah ada (mis. sudah diisi callback sebelumnya)
            existing = ORDER_DRAFTS.get(upstream_id) or {}

            # Extract opsi distributor dari RESPON checkout (format lama/baru)
            extracted_opts = _extract_distributor_options_from_payload(upstream_resp)

            # Jika existing sudah punya opsi, merge tanpa duplikat
            existing_opts = existing.get("distributor_options") if isinstance(existing.get("distributor_options"), list) else []
            merged_opts = []
            seen = set()
            for opt in (existing_opts + extracted_opts):
                key = (opt.get("id_distributor"), opt.get("harga_pengiriman"), opt.get("estimasi"))
                if key in seen:
                    continue
                seen.add(key)
                merged_opts.append(opt)

            ORDER_DRAFTS[upstream_id] = {
                # preserve existing fields
                **existing,
                "id_order": upstream_id,
                "id_retail": existing.get("id_retail", id_retail),
                "id_supplier": existing.get("id_supplier", id_supplier),
                "message": existing.get("message", upstream_resp.get("message") or "Menunggu opsi distributor dari supplier…"),
                "jumlah_item": existing.get("jumlah_item", upstream_resp.get("jumlah_item")),
                "total_kuantitas": existing.get("total_kuantitas", upstream_resp.get("total_kuantitas")),
                "total_order": existing.get("total_order", upstream_resp.get("total_order")),
                "distributor_options": merged_opts,
                "_raw": {**existing.get("_raw", {}), "upstream_resp": upstream_resp, "source": "local_stub_after_checkout"},
            }

            # Kalau supplier mengembalikan resi sejak checkout (jarang), simpan juga
            _merge_resi_into_draft(upstream_id, upstream_resp)

            print(f"[checkout] local draft merged for order #{upstream_id} | opsi: {len(merged_opts)}")
    except Exception as e:
        print("[checkout] failed to create/merge local draft:", repr(e))

    # bersihkan keranjang bila sukses
    session["cart"] = []
    session.modified = True

    return jsonify({
        "message": "Pesanan dikirim ke supplier",
        "id_order": int(upstream_id) if upstream_id else None,
        "order": upstream_resp
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

    # Ambil draft lama kalau ada (supaya bisa fallback id_supplier)
    prev = ORDER_DRAFTS.get(id_order) or {}

    distributor_options = _extract_distributor_options_from_payload(data)

    normalized = {
        "id_order": id_order,
        "id_retail": data.get("id_retail") if data.get("id_retail") is not None else prev.get("id_retail"),
        "id_supplier": data.get("id_supplier") if data.get("id_supplier") is not None else prev.get("id_supplier"),
        "jumlah_item": data.get("jumlah_item") if data.get("jumlah_item") is not None else prev.get("jumlah_item"),
        "total_kuantitas": data.get("total_kuantitas") if data.get("total_kuantitas") is not None else prev.get("total_kuantitas"),
        "total_order": data.get("total_order") if data.get("total_order") is not None else prev.get("total_order"),
        "message": data.get("message") or prev.get("message"),
        "distributor_options": distributor_options if distributor_options else prev.get("distributor_options", []),
        "_raw": data,
    }
    ORDER_DRAFTS[id_order] = normalized

    print("\n=== CALLBACK NORMALIZED ===")
    print(f"Order: {id_order} | opsi: {len(normalized.get('distributor_options') or [])} | supplier: {normalized.get('id_supplier')}")
    for i, o in enumerate(normalized.get("distributor_options") or [], 1):
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

    # === simpan pilihan distributor
    d = ORDER_DRAFTS.setdefault(id_order, {})
    d["chosen_distributor"] = int(id_distributor)

    # === BARU: jika response sudah mengandung resi/total/eta → simpan ke draft
    _merge_resi_into_draft(id_order, data)

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
