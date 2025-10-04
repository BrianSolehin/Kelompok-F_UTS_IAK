# supplier2.py
import requests
from flask import Blueprint, jsonify

supplier2_bp = Blueprint("supplier2", __name__)

SUPPLIER2_URL = "http://192.168.100.193:5000/api/products"

def _to_int(v):
    try:
        return int(float(v))
    except Exception:
        return 0

def _normalize_item(x: dict) -> dict:
    return {
        "id_product":   x.get("id_product") or x.get("id") or x.get("product_id") or "",
        "nama_product": x.get("nama_product") or x.get("name") or x.get("product_name") or "",
        "harga":        _to_int(x.get("harga") or x.get("price") or x.get("harga_beli") or 0),
        "stok":         _to_int(x.get("stok") or x.get("stock") or x.get("qty") or 0),
        "expired_date": x.get("expired_date") or x.get("expired") or x.get("expiry") or "-",
        "kategori":     x.get("kategori") or "-",
        "deskripsi":    x.get("deskripsi") or "-",
        "_source":      "supplier2",
    }

@supplier2_bp.get("/products")
def products_proxy_supplier2():
    try:
        r = requests.get(SUPPLIER2_URL, timeout=8)
        r.raise_for_status()
        raw = r.json()
        items = raw if isinstance(raw, list) else (raw.get("data") or raw.get("items") or raw.get("result") or raw.get("products") or [])
        if not isinstance(items, list):
            items = []
        normalized = [_normalize_item(it or {}) for it in items]
        return jsonify(normalized)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "upstream_error", "detail": str(e)}), 502
    except ValueError as e:
        return jsonify({"error": "invalid_json_from_upstream", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "unknown_proxy_error", "detail": str(e)}), 500
