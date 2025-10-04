# orders.py
from flask import Blueprint, request, jsonify

# Nama blueprint "orders" akan membentuk endpoint prefix "orders.*"
orders_bp = Blueprint("orders", __name__)

# =========================
# 1) Callback dari Supplier (draft order & opsi distributor)
# =========================
@orders_bp.route('/order-callback', methods=['POST'])
def order_callback():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Tidak ada data diterima"}), 400

    # Log ringkas di console
    print("\n=== 📦 CALLBACK DITERIMA DARI SUPPLIER ===")
    print(f"ID Order Supplier : {data.get('id_order')}")
    print(f"ID Retail         : {data.get('id_retail')}")
    print(f"ID Supplier       : {data.get('id_supplier')}")
    print(f"Total Berat       : {data.get('total_berat')} kg")
    print(f"Jumlah Item       : {data.get('jumlah_item')}")
    print("Status Pesanan    :", data.get('message'))

    print("\nPilihan Distributor / Ekspedisi:")
    distributor_list = data.get('distributor_options', [])
    for i, dist in enumerate(distributor_list, start=1):
        print(
            f"  {i}. {dist.get('nama_distributor')} "
            f"(ID: {dist.get('id_distributor')}) - "
            f"Harga: Rp{dist.get('harga_pengiriman')} - "
            f"Estimasi: {dist.get('estimasi')}"
        )
    print("=========================================\n")

    # TODO: simpan draft/opsi distributor ke DB retail bila diperlukan

    return jsonify({
        "message": "Retail menerima callback dari supplier",
        "status": "success"
    }), 200


# =========================
# 2) Callback RESI dari Supplier (setelah distributor terpilih)
# =========================
@orders_bp.route('/resi', methods=['POST'])
def receive_resi_from_supplier():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Tidak ada data diterima"}), 400

    print("📦 Callback RESI diterima dari Supplier:")
    print(data)

    # Ambil data penting
    id_order = data.get('id_order')
    id_retail = data.get('id_retail')
    total_pembayaran = data.get('total_pembayaran')
    no_resi = data.get('no_resi')
    eta_delivery_date = data.get('eta_delivery_date')

    # Validasi minimal
    if not id_order or not no_resi:
        return jsonify({"error": "Data tidak lengkap (id_order/no_resi)"}), 400

    # TODO: update status order & simpan no_resi ke DB retail

    print(f"🧾 Order {id_order} - No Resi: {no_resi}")
    print(f"💰 Total Pembayaran: {total_pembayaran}")
    print(f"🚚 Estimasi Tiba: {eta_delivery_date}")

    return jsonify({
        "message": "Callback resi dari supplier berhasil diterima",
        "id_order": id_order,
        "id_retail": id_retail,
        "no_resi": no_resi,
        "total_pembayaran": total_pembayaran,
        "eta_delivery_date": eta_delivery_date
    }), 200
