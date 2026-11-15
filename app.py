"""Server Flask-SocketIO — REST + WebSocket + MJPEG + State Machine."""

from __future__ import annotations

import atexit
import signal
import sys
import time
from threading import Event, Thread

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO

import config
from ai_engine.detector import MockAIStrategy, build_ai_strategy
from core.state_machine import SmartScaleStateMachine
from database import init_db, list_analytics, list_logs, list_products, update_product
from hardware.camera_usb import CameraManager
from hardware.lcd_i2c import LCDManager
from hardware.scale_hx711 import ScaleManager

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = config.SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

init_db()
# Khởi tạo Singleton phần cứng duy nhất một lần
scale = ScaleManager()
camera = CameraManager()
lcd = LCDManager()
ai_strategy = build_ai_strategy()
stop_event = Event()


def _shutdown_handler(signum=None, frame=None) -> None:
    print(f"\n[APP] Nhận tín hiệu dừng (signal={signum}). Đang dọn dẹp tài nguyên phần cứng...")
    stop_event.set()
    scale.cleanup()
    camera.stop()
    sys.exit(0)


# Đăng ký cleanup tài nguyên GPIO khi thoát bình thường hoặc nhận tín hiệu SIGTERM/SIGINT
atexit.register(scale.cleanup)
try:
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)
except Exception:
    pass


def emit_event(event: str, payload: dict) -> None:
    socketio.emit(event, payload)


state_machine = SmartScaleStateMachine(scale, camera, ai_strategy.predict, on_event=emit_event, lcd=lcd)


def weight_producer() -> None:
    interval = 1.0 / config.WEIGHT_SAMPLE_HZ
    while not stop_event.is_set():
        started = time.time()
        state_machine.update()
        socketio.emit(
            "weight_update",
            {
                "weight_gram": abs(float(scale.current_weight)),
                "is_stable": scale.is_stable,
                "state": state_machine.state.value,
                "scale_online": scale.scale_online,
                "scale_calibrated": scale.calibrated,
                "ts": time.time(),
            },
        )
        elapsed = time.time() - started
        time.sleep(max(0.0, interval - elapsed))


@app.route("/")
def kiosk():
    return render_template("kiosk.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/video_feed")
def video_feed():
    def generate():
        while not stop_event.is_set():
            chunk = camera.mjpeg_bytes()
            if chunk:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + chunk + b"\r\n")
            time.sleep(1 / 25)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/state")
def api_state():
    return jsonify(state_machine.snapshot())


@app.route("/api/hardware/status")
def api_hardware_status():
    cam_status = camera.get_status()
    scale_status = scale.get_status()
    lcd_status = lcd.get_status()

    ai_ready = getattr(ai_strategy, "is_ready", True)
    ai_strategy_name = getattr(ai_strategy, "name", "mock")
    ai_backend = getattr(ai_strategy, "backend", ai_strategy_name)
    ai_classes_count = getattr(ai_strategy, "num_classes", len(ai_engine.detector.CLASS_NAMES))

    ai_status = {
        "strategy": ai_strategy_name,
        "backend": ai_backend,
        "is_ready": ai_ready,
        "classes_count": ai_classes_count,
        "status": "PASS" if ai_ready else "MOCK",
        "message": (
            f"Mô hình {ai_backend.upper()} sẵn sàng ({ai_classes_count} lớp)"
            if ai_ready
            else "Chạy Mock AI (chưa nạp ncnn/onnx runtime)"
        ),
        "files": {
            "ncnn_param": config.NCNN_PARAM_PATH.exists(),
            "ncnn_bin": config.NCNN_BIN_PATH.exists(),
            "metadata_yaml": config.NCNN_METADATA_PATH.exists(),
        },
    }

    # Xác định trạng thái tổng thể
    if config.HARDWARE_MODE == "real":
        all_pass = (
            cam_status["status"] == "PASS"
            and scale_status["status"] == "PASS"
            and lcd_status["status"] == "PASS"
        )
        overall = "PASS" if all_pass else "FAIL"
    else:
        overall = "PASS (MOCK)"

    return jsonify({
        "mode": config.HARDWARE_MODE,
        "overall": overall,
        "scale_online": scale.scale_online,
        "scale_calibrated": scale.calibrated,
        "last_grams": abs(float(scale.last_grams)),
        "camera": cam_status,
        "hx711": scale_status,
        "lcd": lcd_status,
        "ai": ai_status,
        "timestamp": time.time(),
    })


@app.route("/api/products", methods=["GET"])
def api_products():
    return jsonify(list_products())


@app.route("/api/products/<product_id>", methods=["PUT"])
def api_update_product(product_id: str):
    data = request.get_json(force=True, silent=True) or {}
    updated = update_product(product_id, data)
    if not updated:
        return jsonify({"error": "Không tìm thấy sản phẩm"}), 404
    return jsonify(updated)


@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 50))
    return jsonify(list_logs(limit=limit))


@app.route("/api/analytics")
def api_analytics():
    return jsonify(list_analytics())


@app.route("/api/scale/tare", methods=["POST"])
@app.route("/api/tare", methods=["POST"])
def api_tare():
    ok = scale.tare(samples=21)
    return jsonify({
        "ok": ok,
        "weight_gram": abs(float(scale.current_weight)),
        "scale_online": scale.scale_online,
        "scale_calibrated": scale.calibrated,
        "error": scale.last_error,
    })


@app.route("/api/simulate/weight", methods=["POST"])
def api_simulate_weight():
    data = request.get_json(force=True, silent=True) or {}
    grams = abs(float(data.get("weight_gram", 0)))
    scale.set_simulated_weight(grams)
    return jsonify({
        "ok": True,
        "weight_gram": abs(float(scale.current_weight)),
        "simulated": scale.hardware_mode == "mock",
        "mode": scale.hardware_mode,
    })


@app.route("/api/simulate/ai", methods=["POST"])
def api_simulate_ai():
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(ai_strategy, MockAIStrategy):
        return jsonify({"ok": False, "error": "Chỉ ép kết quả khi đang dùng MockAIStrategy"}), 400
    ai_strategy.force_next(label=data.get("label"), quality=data.get("quality"))
    return jsonify({"ok": True, "forced": data})


@app.route("/static/captures/<path:filename>")
def captures(filename: str):
    return send_from_directory(config.CAPTURE_DIR, filename)


@socketio.on("connect")
def on_connect():
    emit_event("state_change", state_machine.snapshot())


def start_background() -> None:
    camera.start()
    Thread(target=weight_producer, name="weight-producer", daemon=True).start()


if __name__ == "__main__":
    start_background()
    print(f"[APP] Kiosk http://127.0.0.1:{config.PORT}")
    print(f"[APP] Admin http://127.0.0.1:{config.PORT}/admin")
    print(f"[APP] Chế độ phần cứng: {config.HARDWARE_MODE.upper()}")
    print(f"[APP] AI strategy = {ai_strategy.name}")

    # Tuyệt đối không bật debug/reloader khi ở HARDWARE_MODE=real để tránh 2 tiến trình tranh chấp GPIO
    if config.HARDWARE_MODE == "real":
        run_debug = False
        run_reloader = False
    else:
        run_debug = config.DEBUG
        run_reloader = False

    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=run_debug,
        use_reloader=run_reloader,
        allow_unsafe_werkzeug=True,
    )
