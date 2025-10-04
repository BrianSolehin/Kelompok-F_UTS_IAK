# distributor.py
from flask import Blueprint, jsonify

distributor_bp = Blueprint("distributor", __name__)

@distributor_bp.get("/ping")
def ping_distributor():
    return jsonify({"ok": True, "source": "distributor"})
