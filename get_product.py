# get_product.py
from flask import Blueprint, request, jsonify
import json
from datetime import datetime

# Blueprint untuk menerima event dari distributor
receiver_bp = Blueprint("receiver", __name__)

@receiver_bp.route("/api/distributor-events", methods=["POST"])
def distributor_events():
   
    try:
        evt = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "invalid json"}), 400

    print("\n=== [EVENT RECEIVED] ===")
    try:
        print(json.dumps(evt, indent=2, ensure_ascii=False))
    except Exception:
        # fallback kalau ada objek tidak serializable
        print(evt)
    print("========================\n")

    ts = datetime.utcnow().isoformat()
    return jsonify({"status": "ok", "received_at": ts}), 200
