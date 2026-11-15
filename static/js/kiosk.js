const STATE_TEXT = {
  IDLE: "IDLE — chờ đặt hàng",
  STABILIZING: "STABILIZING — đang ổn định khối lượng",
  INSPECTING: "INSPECTING — đang kiểm định AI",
  CHECKOUT: "CHECKOUT — giữ hóa đơn, nhấc hàng để reset",
};

const STATE_ORDER = ["IDLE", "STABILIZING", "INSPECTING", "CHECKOUT"];

const liveEl = document.getElementById("live");
const camBadge = document.getElementById("cam-badge");
const weightEl = document.getElementById("weight");
const stateLabel = document.getElementById("state-label");
const stableLabel = document.getElementById("stable-label");
const pills = document.querySelectorAll(".pill[data-state]");
const resultCard = document.getElementById("result-card");
const waiting = document.getElementById("waiting");
const resultBody = document.getElementById("result-body");
const simRange = document.getElementById("sim-range");
const simVal = document.getElementById("sim-val");
const hwHint = document.getElementById("hw-hint");
const simBar = document.querySelector(".sim-bar");
const qrFrame = document.getElementById("qr-frame");
const scaleBanner = document.getElementById("scale-alert-banner");
const scaleBannerTitle = document.getElementById("scale-alert-title");
const scaleBannerText = document.getElementById("scale-alert-text");

let currentHardwareMode = "real";

function vnd(n) {
  return new Intl.NumberFormat("vi-VN").format(n || 0) + " ₫";
}

function setPills(state) {
  const activeIdx = STATE_ORDER.indexOf(state);
  pills.forEach((p) => {
    const pState = p.dataset.state;
    const idx = STATE_ORDER.indexOf(pState);
    p.classList.remove("active", "is-done", "idle", "warn", "inspect", "checkout");

    if (activeIdx !== -1 && idx !== -1 && idx < activeIdx) {
      p.classList.add("is-done");
    } else if (pState === state) {
      p.classList.add("active");
      if (state === "IDLE") p.classList.add("idle");
      if (state === "STABILIZING") p.classList.add("warn");
      if (state === "INSPECTING") p.classList.add("inspect");
      if (state === "CHECKOUT") p.classList.add("checkout");
    }
  });
}

function updateScaleBanner(online, calibrated, errorMsg) {
  if (!scaleBanner) return;

  if (currentHardwareMode !== "real") {
    scaleBanner.hidden = true;
    return;
  }

  if (online === false) {
    scaleBannerTitle.textContent = "Cảnh báo: Mất kết nối cân HX711";
    scaleBannerText.textContent =
      errorMsg || "Không nhận được tín hiệu từ Load Cell sau 2 giây. Vui lòng kiểm tra dây GPIO5/GPIO6 và nguồn 3.3V.";
    scaleBanner.hidden = false;
  } else if (calibrated === false) {
    scaleBannerTitle.textContent = "Cảnh báo: Cân chưa được hiệu chuẩn";
    scaleBannerText.textContent =
      "Chưa có calibration.json hợp lệ. Khối lượng đo có thể sai lệch, vui lòng chạy calibration.py.";
    scaleBanner.hidden = false;
  } else {
    scaleBanner.hidden = true;
  }
}

function renderResult(doc) {
  if (!doc || !doc.ai_result) {
    resultCard.className = "result-card";
    waiting.hidden = false;
    resultBody.hidden = true;
    return;
  }
  waiting.hidden = true;
  resultBody.hidden = false;
  const ai = doc.ai_result;
  const billing = doc.billing || {};
  const fresh = ai.quality_status === "FRESH";
  resultCard.className = "result-card " + (fresh ? "fresh" : "rotten");
  document.getElementById("quality-title").textContent = fresh
    ? "TƯƠI — ĐẠT CHUẨN"
    : "CẢNH BÁO HƯ HỎNG";
  document.getElementById("product-line").textContent =
    `${doc.product_name || "Không rõ"} · ${ai.detected_class} · ${(ai.confidence * 100).toFixed(0)}% · ${ai.inference_time_ms}ms`;
  document.getElementById("price-line").textContent = fresh ? vnd(billing.total_amount) : "KHÓA THANH TOÁN";

  const qr = document.getElementById("qr");
  if (billing.qr_payload && billing.is_sellable) {
    qr.src = billing.qr_payload;
    qr.hidden = false;
    if (qrFrame) qrFrame.hidden = false;
  } else {
    qr.hidden = true;
    if (qrFrame) qrFrame.hidden = true;
  }
  document.getElementById("msg").textContent = billing.message || (fresh ? "Quét VietQR để thanh toán." : "");
  if (ai.image_url) {
    liveEl.src = ai.image_url;
    camBadge.textContent = "ẢNH AI";
  }
}

async function pushWeight(g) {
  const absG = Math.abs(Number(g) || 0);
  if (simVal) simVal.textContent = `${absG} g`;
  await fetch("/api/simulate/weight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weight_gram: absG }),
  });
}

if (simRange) {
  simRange.addEventListener("input", (e) => pushWeight(e.target.value));
}

const btnZero = document.getElementById("btn-zero");
if (btnZero) {
  btnZero.onclick = async () => {
    if (simRange) simRange.value = 0;
    await fetch("/api/tare", { method: "POST" });
    await pushWeight(0);
  };
}

const btnKioskTare = document.getElementById("btn-kiosk-tare");
if (btnKioskTare) {
  btnKioskTare.onclick = async () => {
    const labelSpan = btnKioskTare.querySelector("span");
    if (labelSpan) labelSpan.textContent = "Đang Tare...";
    try {
      if (simRange && currentHardwareMode === "mock") {
        simRange.value = 0;
        await pushWeight(0);
      }
      await fetch("/api/scale/tare", { method: "POST" });
      if (labelSpan) labelSpan.textContent = "Đã về 0g";
    } catch {
      if (labelSpan) labelSpan.textContent = "Lỗi Tare";
    } finally {
      setTimeout(() => {
        if (labelSpan) labelSpan.textContent = "Về 0g";
      }, 1200);
    }
  };
}

const btnFresh = document.getElementById("btn-fresh");
if (btnFresh) {
  btnFresh.onclick = () =>
    fetch("/api/simulate/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quality: "FRESH" }),
    });
}

const btnRotten = document.getElementById("btn-rotten");
if (btnRotten) {
  btnRotten.onclick = () =>
    fetch("/api/simulate/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quality: "ROTTEN" }),
    });
}

function updateHwHint(hw) {
  if (!hwHint || !hw) return;
  const s = hw.scale ? "HX711 OK" : "HX711 Lỗi";
  const c = hw.camera ? "Cam OK" : "Cam Standby";
  const l = hw.lcd ? "LCD OK" : "LCD Chờ";
  hwHint.textContent = `${c} · ${s} · ${l}`;
}

function checkHardwareBanner() {
  return fetch("/api/hardware/status")
    .then((r) => r.json())
    .then((hw) => {
      currentHardwareMode = hw.mode || "real";
      if (currentHardwareMode === "real" && simBar) {
        simBar.style.display = "none";
      }
      const hxMsg = hw.hx711 ? hw.hx711.message : null;
      updateScaleBanner(hw.scale_online, hw.scale_calibrated, hxMsg);
    })
    .catch(() => {});
}

const btnAlertRecheck = document.getElementById("btn-alert-recheck");
if (btnAlertRecheck) {
  btnAlertRecheck.onclick = () => checkHardwareBanner();
}

checkHardwareBanner();

const socket = io();
socket.on("weight_update", (d) => {
  const g = Math.abs(Number(d.weight_gram) || 0);
  weightEl.innerHTML = `${g.toFixed(1)}<span>g</span>`;
  stateLabel.textContent = STATE_TEXT[d.state] || d.state;
  stableLabel.textContent = d.is_stable ? "Ổn định Δm < 2g / 1.5s" : "Chưa ổn định";
  setPills(d.state);
  if (typeof d.scale_online === "boolean" || typeof d.scale_calibrated === "boolean") {
    updateScaleBanner(d.scale_online, d.scale_calibrated);
  }
});

socket.on("state_change", (snap) => {
  setPills(snap.state);
  updateHwHint(snap.hardware);
  if (typeof snap.scale_online === "boolean" || typeof snap.scale_calibrated === "boolean") {
    updateScaleBanner(snap.scale_online, snap.scale_calibrated);
  }
  if (snap.state === "IDLE") {
    liveEl.src = "/video_feed?" + Date.now();
    camBadge.textContent = "LIVE";
    renderResult(null);
  }
  if (snap.result) renderResult(snap.result);
});

socket.on("ai_result", renderResult);

fetch("/api/state")
  .then((r) => r.json())
  .then((snap) => {
    setPills(snap.state);
    if (snap.result) renderResult(snap.result);
    updateHwHint(snap.hardware);
    if (typeof snap.scale_online === "boolean" || typeof snap.scale_calibrated === "boolean") {
      updateScaleBanner(snap.scale_online, snap.scale_calibrated);
    }
  });
