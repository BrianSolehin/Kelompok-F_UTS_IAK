# supplier2.py
import requests
from flask import Blueprint, jsonify

supplier2_bp = Blueprint("supplier2", __name__)

SUPPLIER2_URL = "http://192.168.0.29:5000/api/retail/products"

def _to_int(v):
    try:
        return int(float(v))
    except Exception:
        return 0

def _norm(x: dict) -> dict:
    return {
        "id_product":   x.get("id_product") or "",
        "nama_product": x.get("nama_product") or "",
        "harga":        _to_int(x.get("harga") or 0),
        "stok":         _to_int(x.get("stok") or 0),
        "kategori":     x.get("kategori") or "-",
        "deskripsi":    x.get("deskripsi") or "-",
        "expired_date": x.get("expired_date") or "-",
        "id_supplier":  x.get("id_supplier") or 1,   # ← tambah ini
        "_source":      "supplier2",
    }

@supplier2_bp.get("/products")
def products_proxy():
    try:
        r = requests.get(SUPPLIER2_URL, timeout=8)
        r.raise_for_status()
        raw = r.json() or {}
        items = raw.get("products") or raw.get("data") or []
        if not isinstance(items, list):
            items = []
        return jsonify([_norm(it or {}) for it in items])
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "supplier2_upstream_error", "detail": str(e)}), 502
    except ValueError as e:
        return jsonify({"error": "invalid_json_from_supplier2", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "unknown_supplier2_proxy_error", "detail": str(e)}), 500
