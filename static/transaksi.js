// static/transaksi.js
(() => {
  // ====== STATE ======
  let TRX_ID = null; // id_transaksi aktif
  let CATALOG = [];  // cache katalog gudang

  // ====== ELEM ======
  const el = {
    search:      document.getElementById("searchProduct"),
    kategori:    document.getElementById("filterKategori"), // placeholder (tidak dipakai krn tabel barang tdk punya kategori)
    catalogBody: document.getElementById("catalogBody"),
    cartBody:    document.getElementById("cartBody"),
    pelanggan:   document.getElementById("pelanggan"),
    metode:      document.getElementById("metode"),
    tanggal:     document.getElementById("tanggal"),
    subtotal:    document.getElementById("subtotal"),
    ppn:         document.getElementById("ppn"),
    grand:       document.getElementById("grandTotal"),
    bayar:       document.getElementById("bayar"),
    kembali:     document.getElementById("kembali"),
    warnStock:   document.getElementById("warnStock"),
    btnVoid:     document.getElementById("btnVoid"),
    btnCheckout: document.getElementById("btnCheckout"),
  };

  // ====== UTIL ======
  const fmtRp = (v) => {
    const n = Number(v || 0);
    return n.toLocaleString("id-ID");
  };
  const nowText = () => {
    const d = new Date();
    return d.toLocaleString("id-ID");
  };
  const qsel = (q) => document.querySelector(q);

  // ====== API HELPERS ======
  async function apiGet(url) {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  async function apiJSON(method, url, body) {
    const r = await fetch(url, {
      method,
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const txt = await r.text();
    let json = null;
    try { json = txt ? JSON.parse(txt) : {}; } catch {}
    if (!r.ok) {
      const msg = (json && (json.error || json.message)) || txt || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return json || {};
  }

  async function ensureTrx() {
    if (TRX_ID) return TRX_ID;
    const payload = {
      pelanggan: el.pelanggan?.value || "Umum",
      metode: el.metode?.value || "CASH",
    };
    const res = await apiJSON("POST", "/api/pos/open", payload);
    TRX_ID = res.id_transaksi;
    return TRX_ID;
  }

  async function refreshTrxView() {
    if (!TRX_ID) {
      // kosongkan tampilan keranjang
      el.cartBody.innerHTML = `
        <tr><td colspan="7" class="p-4 text-center text-gray-500">Belum ada item</td></tr>
      `;
      el.subtotal.textContent = "0";
      el.ppn.textContent = "0";
      el.grand.textContent = "0";
      el.kembali.value = "0";
      return;
    }
    const data = await apiGet(`/api/pos/${TRX_ID}`);
    // header
    el.tanggal.value = new Date(data.header.tanggal).toLocaleString("id-ID");
    // items
    renderCart(data.items);
    // calc
    el.subtotal.textContent = fmtRp(data.calc.subtotal);
    el.ppn.textContent      = fmtRp(data.calc.ppn);
    el.grand.textContent    = fmtRp(data.calc.total);
    // kembalian preview
    const bayar = Number(el.bayar.value || 0);
    const kembali = Math.max(0, bayar - Number(data.calc.total || 0));
    el.kembali.value = fmtRp(kembali);
  }

  async function addItemToTrx(sku, qty, harga = null) {
    await ensureTrx();
    await apiJSON("POST", `/api/pos/${TRX_ID}/items`, { sku, qty, harga });
    await refreshTrxView();
  }

  async function updateQty(sku, qty) {
    if (!TRX_ID) return;
    await apiJSON("PATCH", `/api/pos/${TRX_ID}/items/${encodeURIComponent(sku)}`, { qty });
    await refreshTrxView();
  }

  async function payNow() {
    if (!TRX_ID) return;
    el.warnStock.textContent = "";
    try {
      const metode = el.metode.value || "CASH";
      const bayar  = Number(el.bayar.value || 0);
      const res = await apiJSON("POST", `/api/pos/${TRX_ID}/pay`, { metode, bayar });
      alert(`Pembayaran sukses!\nTotal: Rp ${fmtRp(res.total)}\nKembali: Rp ${fmtRp(res.kembali)}`);
      // reset transaksi
      TRX_ID = null;
      el.bayar.value = 0;
      el.kembali.value = "0";
      await refreshTrxView();
    } catch (e) {
      // stok kurang / bayar kurang / lain-lain
      try {
        const obj = JSON.parse(e.message);
        console.warn(obj);
      } catch {}
      if (e.message.includes("stok_kurang")) {
        el.warnStock.textContent = "Stok tidak mencukupi. Periksa kembali item di keranjang.";
      } else {
        alert(`Gagal bayar: ${e.message}`);
      }
    }
  }

  async function voidTrx() {
    if (!TRX_ID) return;
    try {
      await apiJSON("POST", `/api/pos/${TRX_ID}/void`, {});
      TRX_ID = null;
      await refreshTrxView();
    } catch (e) {
      alert(`Gagal batalkan: ${e.message}`);
    }
  }

  // ====== RENDERERS ======
  function renderCatalog(list) {
    el.catalogBody.innerHTML = "";
    if (!list || !list.length) {
      el.catalogBody.innerHTML = `
        <tr><td colspan="6" class="p-4 text-center text-gray-500">Tidak ada produk</td></tr>
      `;
      return;
    }
    for (const it of list) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="p-3">${it.sku}</td>
        <td class="p-3">${it.nama_product || "-"}</td>
        <td class="p-3 text-right">Rp ${fmtRp(it.harga_jual)}</td>
        <td class="p-3 text-right">${it.stok}</td>
        <td class="p-3 text-center">
          <input type="number" min="1" value="1" class="qty-input w-20 px-2 py-1 border rounded-lg text-right" />
        </td>
        <td class="p-3 text-center">
          <button class="add-btn px-3 py-1 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
            Tambah
          </button>
        </td>
      `;
      const qtyInput = tr.querySelector(".qty-input");
      const btn = tr.querySelector(".add-btn");
      btn.addEventListener("click", () => {
        const qty = Math.max(1, parseInt(qtyInput.value || "1", 10));
        addItemToTrx(it.sku, qty, null);
      });
      el.catalogBody.appendChild(tr);
    }
  }

  function renderCart(items) {
    el.cartBody.innerHTML = "";
    if (!items || !items.length) {
      el.cartBody.innerHTML = `
        <tr><td colspan="7" class="p-4 text-center text-gray-500">Belum ada item</td></tr>
      `;
      return;
    }
    items.forEach((it, idx) => {
      const subtotal = Number(it.qty || 0) * Number(it.harga || 0);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="p-3">${idx + 1}</td>
        <td class="p-3">${it.sku}</td>
        <td class="p-3">${it.nama}</td>
        <td class="p-3 text-right">Rp ${fmtRp(it.harga)}</td>
        <td class="p-3 text-center">
          <input type="number" min="0" value="${it.qty}" class="qty-cart w-20 px-2 py-1 border rounded-lg text-right" />
        </td>
        <td class="p-3 text-right">Rp ${fmtRp(subtotal)}</td>
        <td class="p-3 text-center">
          <button class="del-btn px-2 py-1 border rounded-lg hover:bg-gray-50">Hapus</button>
        </td>
      `;
      const qtyInput = tr.querySelector(".qty-cart");
      const delBtn   = tr.querySelector(".del-btn");
      qtyInput.addEventListener("change", () => {
        const q = Math.max(0, parseInt(qtyInput.value || "0", 10));
        updateQty(it.sku, q);
      });
      delBtn.addEventListener("click", () => updateQty(it.sku, 0));
      el.cartBody.appendChild(tr);
    });
  }

  // ====== INIT ======
  async function loadCatalog() {
    try {
      const q = (el.search.value || "").trim();
      const res = await apiGet(`/api/gudang${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      CATALOG = res.items || [];
      // (opsional) filter kategori: di DB tidak ada kolom kategori; kalau mau, bisa pakai id_supplier sebagai "kategori"
      renderCatalog(CATALOG);
    } catch (e) {
      el.catalogBody.innerHTML = `
        <tr><td colspan="6" class="p-4 text-center text-red-600">Gagal memuat katalog: ${e.message}</td></tr>
      `;
    }
  }

  function wireEvents() {
    el.tanggal.value = nowText();
    el.search.addEventListener("input", () => {
      const q = (el.search.value || "").toLowerCase();
      const filtered = CATALOG.filter(it =>
        (it.sku || "").toLowerCase().includes(q) ||
        (it.nama_product || "").toLowerCase().includes(q)
      );
      renderCatalog(filtered);
    });
    el.bayar.addEventListener("input", () => refreshTrxView());
    el.btnCheckout.addEventListener("click", payNow);
    el.btnVoid.addEventListener("click", voidTrx);
  }

  // Boot
  wireEvents();
  loadCatalog();
  refreshTrxView();
})();
