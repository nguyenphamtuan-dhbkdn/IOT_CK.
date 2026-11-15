let allLogs = [];
let analyticsChart = null;
let todayTotalInspections = 0;

function vnd(n) {
  return new Intl.NumberFormat("vi-VN").format(n || 0) + " ₫";
}

function cssVar(name, fallback = "") {
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || fallback;
}

function getBadgeClass(status) {
  if (status === "PASS") return "pass";
  if (status === "FAIL") return "fail";
  return "mock";
}

function getDotClass(ok, mode) {
  if (mode === "mock") return "mock";
  return ok ? "online" : "offline";
}

function updateLiveScalePanel(grams, isStable, state, online, calibrated) {
  const wEl = document.getElementById("admin-live-weight");
  const stableEl = document.getElementById("admin-stable-badge");
  const stateEl = document.getElementById("admin-state-badge");
  const onlineEl = document.getElementById("admin-online-indicator");
  const calibEl = document.getElementById("admin-calib-status");

  if (wEl && typeof grams === "number") {
    wEl.textContent = Math.abs(Number(grams) || 0).toFixed(1);
  }
  if (stableEl && typeof isStable === "boolean") {
    stableEl.textContent = isStable ? "Ổn định" : "Chưa ổn định";
    stableEl.className = `pill ${isStable ? "active" : ""}`;
  }
  if (stateEl && state) {
    stateEl.textContent = state;
    stateEl.className = `pill ${state === "CHECKOUT" ? "active" : state === "STABILIZING" ? "warn" : ""}`;
  }
  if (onlineEl && typeof online === "boolean") {
    onlineEl.innerHTML = `<span class="status-dot ${online ? "online" : "offline"}"></span><span>${online ? "Online" : "Mất tín hiệu"}</span>`;
  }
  if (calibEl && typeof calibrated === "boolean") {
    calibEl.textContent = calibrated ? "Đã hiệu chuẩn" : "Chưa hiệu chuẩn";
  }
}

function updateKanbanState(activeState, weightGram, resultDoc) {
  const states = ["IDLE", "STABILIZING", "INSPECTING", "CHECKOUT"];
  states.forEach((st) => {
    const col = document.querySelector(`.kanban-col[data-kanban-state="${st}"]`);
    const countBadge = document.getElementById(`kanban-count-${st}`);
    const infoEl = document.getElementById(`kanban-info-${st}`);

    const isActive = st === activeState;
    if (col) {
      col.classList.toggle("is-active", isActive);
    }

    if (countBadge) {
      if (st === "CHECKOUT") {
        countBadge.textContent = String(todayTotalInspections);
      } else {
        countBadge.textContent = isActive ? "1" : "0";
      }
    }

    if (infoEl && isActive) {
      const wTxt = typeof weightGram === "number" ? `${Number(weightGram).toFixed(1)} g` : "—";
      if (st === "IDLE") {
        infoEl.innerHTML = `<strong>Trạng thái hiện tại</strong><span>Đang chờ đặt hàng (${wTxt})</span>`;
      } else if (st === "STABILIZING") {
        infoEl.innerHTML = `<strong>Đang cân ổn định</strong><span>Khối lượng: ${wTxt}</span>`;
      } else if (st === "INSPECTING") {
        infoEl.innerHTML = `<strong>Đang kiểm định AI</strong><span>Khối lượng: ${wTxt}</span>`;
      } else if (st === "CHECKOUT") {
        const prod = resultDoc?.product_name || "Hoàn tất phiên cân";
        const amt = resultDoc?.billing?.is_sellable ? vnd(resultDoc.billing.total_amount) : "Khóa thanh toán";
        infoEl.innerHTML = `<strong>${prod}</strong><span>${wTxt} · ${amt}</span>`;
      }
    } else if (infoEl && !isActive && st !== "CHECKOUT") {
      const defaults = {
        IDLE: "Chờ phiên mới",
        STABILIZING: "Chờ đặt vật >= 15g",
        INSPECTING: "Chờ cân ổn định",
      };
      infoEl.innerHTML = `<strong>Trạng thái</strong><span>${defaults[st]}</span>`;
    }
  });
}

async function loadHardwareStatus() {
  const btn = document.getElementById("btn-recheck-hw");
  if (btn) {
    const span = btn.querySelector("span");
    if (span) span.textContent = "Đang kiểm tra...";
  }

  try {
    const res = await fetch("/api/hardware/status");
    const data = await res.json();

    const modeBadge = document.getElementById("hw-mode-badge");
    if (modeBadge) {
      modeBadge.textContent = `MODE: ${(data.mode || "REAL").toUpperCase()}`;
      modeBadge.className = `pill ${data.mode === "mock" ? "warn" : "active"}`;
    }

    const updatedEl = document.getElementById("hw-last-updated");
    if (updatedEl) {
      updatedEl.textContent = "Cập nhật: " + new Date().toLocaleTimeString("vi-VN");
    }

    const cam = data.camera || {};
    const hx = data.hx711 || {};
    const lcd = data.lcd || {};

    const camDet = cam.details || {};
    const hxDet = hx.details || {};
    const lcdDet = lcd.details || {};

    const isCamOk = Boolean(cam.available);
    const isScaleOnline = data.scale_online ?? hx.scale_online ?? false;
    const isScaleCalib = data.scale_calibrated ?? hx.scale_calibrated ?? false;
    const lastGrams = data.last_grams ?? hx.last_grams ?? 0.0;
    const isLcdOk = Boolean(lcd.available);

    updateLiveScalePanel(lastGrams, hxDet.is_stable, null, isScaleOnline, isScaleCalib);

    const items = [
      {
        title: "Camera USB",
        icon: "ti-camera",
        dot: getDotClass(isCamOk, "real"),
        status: cam.status || "FAIL",
        msg: cam.message || "Chưa phát hiện thiết bị",
        meta: [
          ["Độ phân giải", camDet.resolution ? `${camDet.resolution} @ ${camDet.fps}fps` : "640x480 @ 30fps"],
          ["Định dạng", `${camDet.fourcc || "MJPG"} · Buf ${camDet.buffersize || 1}`],
          ["Thiết bị", camDet.device || `/dev/video${camDet.index ?? 0}`],
        ],
      },
      {
        title: "Cân HX711",
        icon: "ti-scale",
        dot: getDotClass(isScaleOnline, data.mode),
        status: isScaleOnline && isScaleCalib ? "PASS" : data.mode === "mock" ? "PASS (MOCK)" : "FAIL",
        msg: hx.message || (isScaleOnline ? "Cân hoạt động bình thường" : "Mất tín hiệu cân"),
        meta: [
          ["Tín hiệu", isScaleOnline ? "Online (< 2s)" : "Mất tín hiệu (> 2s)"],
          ["Hiệu chuẩn", isScaleCalib ? "Đã hiệu chuẩn" : "Chưa có calibration.json"],
          ["Khối lượng", `${Number(lastGrams).toFixed(1)} g`],
          ["Chân BCM", `DT=${hxDet.dt_pin ?? 5} · SCK=${hxDet.sck_pin ?? 6}`],
          ["scale_ratio", hxDet.scale_ratio ? Number(hxDet.scale_ratio).toFixed(4) : "Chưa có"],
        ],
      },
      {
        title: "LCD 16x2 I2C",
        icon: "ti-device-tv",
        dot: getDotClass(isLcdOk, data.mode),
        status: lcd.status || "FAIL",
        msg: lcd.message || "Chưa phát hiện thiết bị",
        meta: [
          ["I2C Bus", `${lcdDet.expander || "PCF8574"} @ ${lcdDet.address || "0x27"}`],
          ["Kích thước", `${lcdDet.cols || 16} x ${lcdDet.rows || 2}`],
          ["Hiển thị", lcdDet.line1 ? `"${lcdDet.line1.trim()}"` : "Sẵn sàng"],
        ],
      },
    ];

    const ai = data.ai || {};
    if (ai.strategy) {
      const isAiOk = Boolean(ai.is_ready);
      items.push({
        title: "Mô hình AI",
        icon: "ti-brain",
        dot: isAiOk ? "online" : data.mode === "mock" ? "mock" : "offline",
        status: isAiOk ? (ai.strategy === "ncnn" ? "PASS (NCNN)" : "PASS") : "MOCK",
        msg: ai.message || (isAiOk ? `Mô hình ${ai.strategy.toUpperCase()} sẵn sàng` : "Chạy Mock AI"),
        meta: [
          ["Chiến lược", `${(ai.strategy || "auto").toUpperCase()} (${ai.backend || "ncnn"})`],
          ["Số nhãn", `${ai.classes_count || 64} nhãn thực phẩm`],
          ["Mô hình", ai.files?.ncnn_param ? "model.ncnn (NEON)" : "Chưa có file"],
        ],
      });
    }

    document.getElementById("hw-grid").innerHTML = items
      .map(
        (it) => `
        <div class="hw-item">
          <div class="hw-header">
            <span class="hw-title">
              <span class="status-dot ${it.dot}"></span>
              <i class="ti ${it.icon}"></i>
              <span>${it.title}</span>
            </span>
            <span class="hw-badge ${getBadgeClass(it.status)}">${it.status}</span>
          </div>
          <div class="hw-msg">${it.msg}</div>
          <div class="hw-meta-list">
            ${it.meta
              .map(
                ([k, v]) => `
                <div class="hw-meta-row">
                  <span class="label">${k}</span>
                  <span class="val">${v}</span>
                </div>`
              )
              .join("")}
          </div>
        </div>`
      )
      .join("");
  } catch (err) {
    console.error("Lỗi khi tải trạng thái phần cứng:", err);
    document.getElementById("hw-grid").innerHTML = `
      <div class="alert alert-danger m-0" role="alert">
        Không thể kết nối API /api/hardware/status: ${err.message}
      </div>`;
  } finally {
    if (btn) {
      const span = btn.querySelector("span");
      if (span) span.textContent = "Kiểm tra lại";
    }
  }
}

async function performTare(btnEl, defaultLabel) {
  const labelEl = btnEl?.querySelector("span") || btnEl;
  if (labelEl) labelEl.textContent = "Đang Tare...";
  try {
    const r = await fetch("/api/scale/tare", { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      if (labelEl) labelEl.textContent = "Đã về 0g!";
    } else {
      if (labelEl) labelEl.textContent = "Lỗi Tare";
      alert("Lỗi khi Tare: " + (d.error || "Không rõ"));
    }
  } catch {
    if (labelEl) labelEl.textContent = "Lỗi mạng";
  } finally {
    setTimeout(() => {
      if (labelEl) labelEl.textContent = defaultLabel;
      loadHardwareStatus();
    }, 1200);
  }
}

function renderLogs() {
  const searchVal = (document.getElementById("log-filter-search")?.value || "").trim().toLowerCase();
  const qualityVal = document.getElementById("log-filter-quality")?.value || "ALL";
  const productVal = document.getElementById("log-filter-product")?.value || "ALL";

  const filtered = allLogs.filter((l) => {
    const ai = l.ai_result || {};
    const q = ai.quality_status || "";
    const pCode = l.product_code || "";
    const pName = (l.product_name || "").toLowerCase();
    const cls = (ai.detected_class || "").toLowerCase();

    if (qualityVal !== "ALL" && q !== qualityVal) return false;
    if (productVal !== "ALL" && pCode !== productVal) return false;
    if (searchVal) {
      const hay = `${pName} ${pCode.toLowerCase()} ${cls}`;
      if (!hay.includes(searchVal)) return false;
    }
    return true;
  });

  const countEl = document.getElementById("log-filter-count");
  if (countEl) {
    countEl.textContent = `${filtered.length} / ${allLogs.length} giao dịch`;
  }

  if (filtered.length === 0) {
    document.getElementById("logs").innerHTML = `
      <tr>
        <td colspan="6" class="text-center text-muted py-4">Không có giao dịch nào khớp bộ lọc.</td>
      </tr>`;
    return;
  }

  document.getElementById("logs").innerHTML = filtered
    .map((l) => {
      const ai = l.ai_result || {};
      const bill = l.billing || {};
      const fresh = ai.quality_status === "FRESH";
      return `<tr>
        <td class="tabular-nums">${(l.timestamp || "").replace("T", " ").replace("Z", "")}</td>
        <td>${ai.image_url ? `<img class="thumb" src="${ai.image_url}" alt="Ảnh kiểm định" />` : "—"}</td>
        <td><strong>${l.product_name || "—"}</strong></td>
        <td class="tabular-nums">${Number(l.weight_gram || 0).toFixed(1)} g</td>
        <td>
          <span class="tag ${fresh ? "fresh" : "rotten"}">
            <i class="ti ${fresh ? "ti-check" : "ti-alert-circle"}"></i>
            ${ai.quality_status || "UNKNOWN"} · ${ai.detected_class || ""}
          </span>
        </td>
        <td class="tabular-nums"><strong>${bill.is_sellable ? vnd(bill.total_amount) : "Khóa thanh toán"}</strong></td>
      </tr>`;
    })
    .join("");
}

function renderChart(analytics) {
  const ctx = document.getElementById("chart");
  if (!ctx) return;

  const labels = analytics.slice().reverse().map((a) => a.date);
  const fresh = analytics.slice().reverse().map((a) => a.fresh_count);
  const rotten = analytics.slice().reverse().map((a) => a.rotten_count);

  const colorFresh = cssVar("--fresh");
  const colorRotten = cssVar("--rotten");
  const textColor = cssVar("--text-secondary");
  const gridColor = cssVar("--border-color");

  if (analyticsChart) {
    analyticsChart.destroy();
  }

  analyticsChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels.length ? labels : ["Chưa có dữ liệu"],
      datasets: [
        { label: "Tươi (Fresh)", data: fresh.length ? fresh : [0], backgroundColor: colorFresh, borderRadius: 6 },
        { label: "Hư hỏng (Rotten)", data: rotten.length ? rotten : [0], backgroundColor: colorRotten, borderRadius: 6 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: textColor, font: { family: cssVar("--font-sans", "sans-serif"), weight: "600" } },
        },
      },
      scales: {
        x: { ticks: { color: textColor }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, precision: 0 }, grid: { color: gridColor }, beginAtZero: true },
      },
    },
  });
}

async function loadData() {
  const [products, logs, analytics] = await Promise.all([
    fetch("/api/products").then((r) => r.json()),
    fetch("/api/logs").then((r) => r.json()),
    fetch("/api/analytics").then((r) => r.json()),
  ]);

  const today = analytics[0] || {
    total_inspections: 0,
    fresh_count: 0,
    rotten_count: 0,
    total_weight_kg: 0,
    total_revenue_vnd: 0,
  };
  todayTotalInspections = today.total_inspections || 0;

  document.getElementById("cards").innerHTML = [
    ["Lượt kiểm định hôm nay", today.total_inspections],
    ["Đạt chuẩn (Fresh)", today.fresh_count],
    ["Hư hỏng (Rotten)", today.rotten_count],
    ["Doanh thu hôm nay", vnd(today.total_revenue_vnd)],
  ]
    .map(([k, v]) => `<div class="kpi-card"><div class="k">${k}</div><div class="v tabular-nums">${v}</div></div>`)
    .join("");

  document.getElementById("products").innerHTML = products
    .map(
      (p) => `
      <tr>
        <td><span class="pill">${p.code}</span></td>
        <td><strong>${p.name_vi}</strong></td>
        <td>
          <input
            type="number"
            min="0"
            step="500"
            class="form-control form-control-sm tabular-nums"
            style="width: 115px;"
            value="${p.price_per_kg}"
            data-id="${p._id}"
          />
        </td>
        <td><button type="button" class="btn btn-sm btn-primary" data-save="${p._id}">Lưu</button></td>
      </tr>`
    )
    .join("");

  document.querySelectorAll("[data-save]").forEach((btn) => {
    btn.onclick = async () => {
      const id = btn.getAttribute("data-save");
      const input = document.querySelector(`input[data-id="${id}"]`);
      await fetch(`/api/products/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ price_per_kg: Number(input.value) }),
      });
      btn.textContent = "Đã lưu";
      setTimeout(() => (btn.textContent = "Lưu"), 1200);
    };
  });

  // Nạp dropdown lọc theo sản phẩm
  const prodSelect = document.getElementById("log-filter-product");
  if (prodSelect) {
    const prevVal = prodSelect.value;
    prodSelect.innerHTML =
      `<option value="ALL">Tất cả sản phẩm</option>` +
      products.map((p) => `<option value="${p.code}">${p.name_vi} (${p.code})</option>`).join("");
    if ([...prodSelect.options].some((o) => o.value === prevVal)) {
      prodSelect.value = prevVal;
    }
  }

  allLogs = logs || [];
  renderLogs();
  renderChart(analytics);
}

function setupSidebarMobile() {
  const menuBtn = document.getElementById("btn-mobile-menu");
  const sidebar = document.getElementById("admin-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");

  const closeSidebar = () => {
    sidebar?.classList.remove("open");
    backdrop?.classList.remove("show");
  };

  if (menuBtn && sidebar && backdrop) {
    menuBtn.onclick = () => {
      sidebar.classList.toggle("open");
      backdrop.classList.toggle("show");
    };
    backdrop.onclick = closeSidebar;
    sidebar.querySelectorAll("a.sidebar-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (window.innerWidth < 992) closeSidebar();
      });
    });
  }
}

async function load() {
  setupSidebarMobile();

  const recheckBtn = document.getElementById("btn-recheck-hw");
  if (recheckBtn) recheckBtn.onclick = () => loadHardwareStatus();

  const tareBtn = document.getElementById("btn-tare-hw");
  if (tareBtn) tareBtn.onclick = () => performTare(tareBtn, "Tare (Về 0g)");

  const adminTareBtn = document.getElementById("btn-admin-tare");
  if (adminTareBtn) adminTareBtn.onclick = () => performTare(adminTareBtn, "Tare cân về 0g");

  document.getElementById("log-filter-search")?.addEventListener("input", renderLogs);
  document.getElementById("log-filter-quality")?.addEventListener("change", renderLogs);
  document.getElementById("log-filter-product")?.addEventListener("change", renderLogs);

  await Promise.all([loadHardwareStatus(), loadData()]);

  // Đồng bộ trạng thái ban đầu của State Machine
  fetch("/api/state")
    .then((r) => r.json())
    .then((snap) => {
      updateLiveScalePanel(snap.weight_gram, snap.is_stable, snap.state, snap.scale_online, snap.scale_calibrated);
      updateKanbanState(snap.state, snap.weight_gram, snap.result);
    })
    .catch(() => {});

  // Kết nối Socket.IO cho Admin realtime
  if (typeof io === "function") {
    const socket = io();
    socket.on("weight_update", (d) => {
      updateLiveScalePanel(d.weight_gram, d.is_stable, d.state, d.scale_online, d.scale_calibrated);
      updateKanbanState(d.state, d.weight_gram, null);
    });
    socket.on("state_change", (snap) => {
      updateLiveScalePanel(snap.weight_gram, snap.is_stable, snap.state, snap.scale_online, snap.scale_calibrated);
      updateKanbanState(snap.state, snap.weight_gram, snap.result);
    });
    socket.on("ai_result", (packed) => {
      loadData().then(() => {
        updateKanbanState("CHECKOUT", packed.weight_gram, packed);
      });
    });
  }
}

load();
