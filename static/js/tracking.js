// static/js/tracking.js
async function getJSON(url, opts={}) {
  const r = await fetch(url, { headers: { "Accept": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function badgeClass(status) {
  switch ((status||"").toUpperCase()) {
    case "CREATED": return "bg-gray-100 text-gray-700";
    case "ON_DELIVERY": return "bg-blue-100 text-blue-700";
    case "DELIVERED": return "bg-green-100 text-green-700";
    case "FAILED": return "bg-red-100 text-red-700";
    default: return "bg-gray-100 text-gray-700";
  }
}

async function refreshActive() {
  try {
    const j = await getJSON("/api/tracking/active");
    const box = document.getElementById("activeResiList");
    if (!j.items?.length) {
      box.innerHTML = `<div class="text-gray-500">Tidak ada resi aktif.</div>`;
      return;
    }
    box.innerHTML = j.items.map(it => `
      <div class="border rounded-lg p-3 flex items-center justify-between">
        <div>
          <div class="font-medium">${it.no_resi} • ${it.nama_barang} (x${it.quantity})</div>
          <div class="text-sm text-gray-500">${it.nama_supplier} → ${it.nama_distributor}</div>
        </div>
        <span class="px-3 py-1 rounded-full text-sm font-semibold ${badgeClass(it.status)}">${it.status}</span>
      </div>
    `).join("");
  } catch(e) {
    console.error(e);
  }
}

async function cekStatus() {
  const resi = document.getElementById("trackResi").value.trim();
  if (!resi) return;
  try {
    const j = await getJSON(`/api/tracking/${encodeURIComponent(resi)}`);
    const list = document.getElementById("historyList");
    const statusBox = document.getElementById("statusBox");
    const statusBadge = document.getElementById("statusBadge");

    if (!j.items?.length) {
      statusBox.classList.remove("hidden");
      statusBadge.textContent = "NOT FOUND";
      statusBadge.className = "px-3 py-1 rounded-full text-sm font-semibold bg-red-100 text-red-700";
      list.innerHTML = `<div class="text-gray-500">Resi tidak ditemukan.</div>`;
      return;
    }

    // Ambil status terbaru
    const latest = j.items[0];
    statusBadge.textContent = latest.status;
    statusBadge.className = `px-3 py-1 rounded-full text-sm font-semibold ${badgeClass(latest.status)}`;
    document.getElementById("etaText").textContent = "-";

    list.innerHTML = j.items.map(it => `
      <div class="border rounded-lg p-3 flex items-center justify-between">
        <div>
          <div class="font-medium">${it.nama_barang} (x${it.quantity})</div>
          <div class="text-sm text-gray-500">${new Date(it.tanggal).toLocaleString()}</div>
        </div>
        <span class="px-3 py-1 rounded-full text-sm font-semibold ${badgeClass(it.status)}">${it.status}</span>
      </div>
    `).join("");

    statusBox.classList.remove("hidden");
  } catch(e) {
    alert("Gagal cek status");
  }
}

async function markDelivered() {
  const resi = document.getElementById("trackResi").value.trim();
  if (!resi) return;
  try {
    await getJSON("/api/tracking/mark-delivered", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ no_resi: resi })
    });
    await cekStatus();
    await refreshActive();
    alert("Ditandai DELIVERED & stok ditambahkan.");
  } catch(e) {
    alert("Gagal tandai DELIVERED");
  }
}

document.getElementById("btnCekStatus")?.addEventListener("click", cekStatus);
document.getElementById("btnMarkDelivered")?.addEventListener("click", markDelivered);
document.getElementById("btnReceive")?.addEventListener("click", markDelivered);

refreshActive();
