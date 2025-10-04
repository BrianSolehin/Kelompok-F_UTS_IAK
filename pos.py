# pos.py
from flask import Blueprint, jsonify

pos_bp = Blueprint("pos", __name__)

@pos_bp.get("/ping")
def ping_pos():
    return jsonify({"ok": True, "source": "pos"})
