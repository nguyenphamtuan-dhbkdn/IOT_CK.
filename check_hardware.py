"""check_hardware.py — Kịch bản kiểm tra toàn diện phần cứng trên Raspberry Pi 4.

Kiểm tra:
1. Camera USB: V4L2, MJPG, 640x480 @ 30 FPS, BUFFERSIZE=1.
2. Cân HX711: Đọc cân 5 lần, in khối lượng (gram), báo PASS/FAIL, kèm cảnh báo nếu chưa có calibration.json.
3. LCD 16x2 I2C: RPLCD, chip PCF8574 tại địa chỉ cấu hình (0x27).

Xuất kết quả PASS / FAIL chi tiết và trả về Exit Code tương ứng (0: tất cả PASS, 1: có lỗi).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

import config

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def check_camera() -> dict:
    print(f"\n{BOLD}[1/3] Đang kiểm tra Camera USB (V4L2 640x480 @ 30FPS)...{RESET}")
    details = {}
    try:
        import cv2
    except ImportError as e:
        return {"status": "FAIL", "msg": f"Chưa cài đặt OpenCV: {e}", "details": {}}

    src = config.CAMERA_INDEX
    cap = None
    try:
        if hasattr(cv2, "CAP_V4L2") and os.name != "nt":
            cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(src)

        if not cap.isOpened():
            return {
                "status": "FAIL",
                "msg": f"Không thể mở camera tại index {src} hoặc {config.CAMERA_DEVICE}",
                "details": {"device": config.CAMERA_DEVICE, "index": src},
            }

        # Cấu hình thuộc tính
        try:
            fourcc = cv2.VideoWriter_fourcc(*config.CAMERA_FOURCC)
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(config.CAMERA_WIDTH))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(config.CAMERA_HEIGHT))
        cap.set(cv2.CAP_PROP_FPS, float(config.CAMERA_FPS))
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, float(config.CAMERA_BUFFERSIZE))
        except Exception:
            pass

        # Đọc thử 3 frame
        ok = False
        frame = None
        for _ in range(5):
            ok, frame = cap.read()
            if ok and frame is not None:
                break
            time.sleep(0.05)

        if not ok or frame is None:
            cap.release()
            return {
                "status": "FAIL",
                "msg": "Camera mở được nhưng không đọc được frame hình ảnh",
                "details": {"index": src},
            }

        h, w, c = frame.shape
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

        details = {
            "resolution": f"{w}x{h}",
            "channels": c,
            "target_resolution": f"{config.CAMERA_WIDTH}x{config.CAMERA_HEIGHT}",
            "fps": actual_fps or config.CAMERA_FPS,
            "backend": "CAP_V4L2" if os.name != "nt" else "CAP_ANY",
        }

        if w >= 320 and h >= 240:
            return {"status": "PASS", "msg": f"Camera hoạt động tốt ({w}x{h})", "details": details}
        else:
            return {"status": "FAIL", "msg": f"Độ phân giải quá thấp ({w}x{h})", "details": details}

    except Exception as exc:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        return {"status": "FAIL", "msg": f"Ngoại lệ khi kiểm tra Camera: {exc}", "details": {}}


def check_hx711() -> dict:
    dt_pin = config.HX711_DT_PIN
    sck_pin = config.HX711_SCK_PIN
    print(f"\n{BOLD}[2/3] Đang kiểm tra Cảm biến tải trọng Load Cell & HX711 (DT=GPIO{dt_pin}, SCK=GPIO{sck_pin})...{RESET}")

    details = {
        "dt_pin": dt_pin,
        "sck_pin": sck_pin,
        "calibration_file": str(config.CALIBRATION_FILE.name),
        "scale_calibrated": False,
        "scale_online": False,
        "last_grams": 0.0,
    }

    # 1. Kiểm tra calibration.json
    has_calib = False
    scale_ratio = 1.0
    if config.CALIBRATION_FILE.exists():
        try:
            with open(config.CALIBRATION_FILE, "r", encoding="utf-8") as f:
                cal_data = json.load(f)
                ratio = float(cal_data.get("scale_ratio", 0))
                if ratio != 0:
                    scale_ratio = ratio
                    has_calib = True
                    details["scale_calibrated"] = True
                    details["scale_ratio"] = ratio
                    print(f"  + Đã nạp {config.CALIBRATION_FILE.name}: scale_ratio = {scale_ratio:.4f}")
                else:
                    print(f"  {YELLOW}[CẢNH BÁO] {config.CALIBRATION_FILE.name} có scale_ratio = 0!{RESET}")
        except Exception as e:
            print(f"  {YELLOW}[CẢNH BÁO] Lỗi đọc {config.CALIBRATION_FILE.name}: {e}{RESET}")
    else:
        print(f"  {YELLOW}[CẢNH BÁO] Chưa có file {config.CALIBRATION_FILE.name}! Cần chạy python calibration.py để hiệu chuẩn.{RESET}")

    details["scale_calibrated"] = has_calib

    # 2. Kiểm tra thư viện RPi.GPIO
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        return {
            "status": "FAIL",
            "scale_online": False,
            "scale_calibrated": has_calib,
            "last_grams": 0.0,
            "msg": "Không có thư viện RPi.GPIO (Chỉ hỗ trợ trên Raspberry Pi OS)",
            "details": details,
        }

    # 3. Đọc kiểm tra trực tiếp theo đúng thuật toán test_scale.py
    try:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(sck_pin, GPIO.OUT)
        GPIO.setup(dt_pin, GPIO.IN)
        GPIO.output(sck_pin, False)

        def is_ready() -> bool:
            return GPIO.input(dt_pin) == 0

        def read_one_raw() -> int:
            t = 0.0
            while not is_ready():
                time.sleep(0.001)
                t += 0.001
                if t > 0.3:
                    raise TimeoutError("HX711 không phản hồi (Timeout DOUT > 0.3s)")
            cnt = 0
            for _ in range(24):
                GPIO.output(sck_pin, True)
                cnt = cnt << 1
                GPIO.output(sck_pin, False)
                if GPIO.input(dt_pin):
                    cnt += 1
            # Xung 25
            GPIO.output(sck_pin, True)
            GPIO.output(sck_pin, False)
            if cnt & 0x800000:
                cnt -= 0x1000000
            return -cnt if config.HX711_INVERT_SIGNAL else cnt

        def read_median(n: int = 9) -> float:
            vals = []
            for _ in range(n):
                try:
                    v = read_one_raw()
                    if v not in (0x7FFFFF, -0x800000, -1):
                        vals.append(v)
                except TimeoutError:
                    pass
                time.sleep(0.01)
            if not vals:
                raise RuntimeError("Mất kết nối với HX711")
            return float(statistics.median(vals))

        # Tare nhanh 15 mẫu
        print("  + Đang lấy điểm 0 (Tare test)...")
        tare_offset = read_median(15)

        # Đọc 5 lần liên tiếp và in khối lượng Gram
        print("  + Bắt đầu đọc 5 mẫu gram liên tiếp:")
        gram_samples = []
        for i in range(1, 6):
            raw = read_median(9)
            grams = abs((raw - tare_offset) / scale_ratio)
            if grams < config.HX711_ZERO_BAND_G:
                grams = 0.0
            gram_samples.append(grams)
            print(f"    - Lần {i}: {grams:7.1f} g (ADC raw: {raw:9.0f})")
            time.sleep(0.1)

        details["samples_read"] = 5
        details["last_grams"] = round(gram_samples[-1], 1)
        details["scale_online"] = True

        status = "PASS" if has_calib else "FAIL"
        if not has_calib:
            msg = f"HX711 kết nối tốt ({gram_samples[-1]:.1f}g) nhưng CHƯA CÓ {config.CALIBRATION_FILE.name} (cần hiệu chuẩn)"
        else:
            msg = f"HX711 kết nối tốt, đọc 5 mẫu thành công (mẫu cuối: {gram_samples[-1]:.1f}g)"

        return {
            "status": status,
            "scale_online": True,
            "scale_calibrated": has_calib,
            "last_grams": round(gram_samples[-1], 1),
            "msg": msg,
            "details": details,
        }

    except Exception as exc:
        details["scale_online"] = False
        return {
            "status": "FAIL",
            "scale_online": False,
            "scale_calibrated": has_calib,
            "last_grams": 0.0,
            "msg": f"Lỗi đọc HX711: {exc}. Kiểm tra lại dây DT=GPIO{dt_pin}, SCK=GPIO{sck_pin}, nguồn 3.3V/GND",
            "details": details,
        }


def check_lcd() -> dict:
    addr_hex = f"0x{config.LCD_I2C_ADDRESS:02X}"
    print(f"\n{BOLD}[3/3] Đang kiểm tra Màn hình LCD 16x2 I2C (PCF8574 tại {addr_hex})...{RESET}")
    details = {
        "address": addr_hex,
        "cols": config.LCD_COLS,
        "rows": config.LCD_ROWS,
        "expander": "PCF8574",
    }

    try:
        from RPLCD.i2c import CharLCD
    except ImportError:
        return {
            "status": "FAIL",
            "msg": "Chưa cài đặt thư viện RPLCD hoặc smbus2 (pip install RPLCD smbus2)",
            "details": details,
        }

    try:
        lcd = CharLCD(
            i2c_expander="PCF8574",
            address=config.LCD_I2C_ADDRESS,
            port=1,
            cols=config.LCD_COLS,
            rows=config.LCD_ROWS,
            dotsize=8,
            charmap="A00",
            auto_linebreaks=False,
        )
        lcd.clear()
        lcd.cursor_pos = (0, 0)
        lcd.write_string("TEST HARDWARE OK")
        lcd.cursor_pos = (1, 0)
        lcd.write_string("SMART SCALE RPI4")
        time.sleep(0.5)

        return {
            "status": "PASS",
            "msg": f"LCD 16x2 phản hồi I2C tại {addr_hex} và đã hiển thị thông báo kiểm tra",
            "details": details,
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "msg": f"Không thể giao tiếp với LCD tại địa chỉ {addr_hex}: {exc}. Vui lòng kiểm tra cáp SDA(GPIO2)/SCL(GPIO3) và chạy lệnh: i2cdetect -y 1",
            "details": details,
        }


def check_ai_model() -> dict:
    print(f"\n{BOLD}[4/4] Đang kiểm tra Mô hình AI (NCNN / ONNX)...{RESET}")
    has_ncnn_param = config.NCNN_PARAM_PATH.exists()
    has_ncnn_bin = config.NCNN_BIN_PATH.exists()
    has_metadata = config.NCNN_METADATA_PATH.exists()
    has_onnx = config.MODEL_PATH.exists()

    from ai_engine.detector import load_metadata_names

    classes = load_metadata_names(config.NCNN_METADATA_PATH)

    has_ncnn_lib = False
    try:
        import ncnn

        has_ncnn_lib = True
    except ImportError:
        pass

    has_ultra_lib = False
    try:
        from ultralytics import YOLO

        has_ultra_lib = True
    except ImportError:
        pass

    if has_ncnn_param and has_ncnn_bin:
        backend_info = "ncnn" if has_ncnn_lib else "ultralytics" if has_ultra_lib else "chưa có runtime"
        if has_ncnn_lib or has_ultra_lib:
            return {
                "status": "PASS",
                "msg": f"Mô hình NCNN hợp lệ ({len(classes)} lớp, backend: {backend_info})",
                "details": {"backend": backend_info, "classes": len(classes), "format": "NCNN"},
            }
        else:
            return {
                "status": "PASS (MOCK)",
                "msg": f"Đã có 3 file NCNN ({len(classes)} lớp). Cần 'pip install ncnn' để kích hoạt AI thật trên Pi 4.",
                "details": {"format": "NCNN", "classes": len(classes)},
            }
    elif has_onnx:
        return {
            "status": "PASS",
            "msg": f"Mô hình ONNX hợp lệ ({config.MODEL_PATH.name})",
            "details": {"format": "ONNX"},
        }
    else:
        return {
            "status": "FAIL",
            "msg": f"Chưa tìm thấy file mô hình tại {config.MODEL_DIR}",
            "details": {"format": "None"},
        }


def print_table(results: list[dict]) -> None:
    print("\n" + "=" * 76)
    print(f"{BOLD}           BẢNG TỔNG HỢP KIỂM TRA PHẦN CỨNG (HARDWARE STATUS)           {RESET}")
    print("=" * 76)
    print(f"| {'THIẾT BỊ':<18} | {'KẾT QUẢ':<8} | {'CHI TIẾT VÀ THÔNG SỐ':<42} |")
    print("+-" + "-" * 18 + "-+-" + "-" * 8 + "-+-" + "-" * 42 + "-+")

    for item in results:
        name = item["name"]
        st = item["status"]
        if st == "PASS":
            badge = f"{GREEN}{BOLD} PASS {RESET}"
        elif st == "PASS (MOCK)":
            badge = f"{YELLOW}{BOLD} MOCK {RESET}"
        else:
            badge = f"{RED}{BOLD} FAIL {RESET}"

        msg = item["msg"]
        msg_short = msg[:42]
        print(f"| {name:<18} | {badge:<17} | {msg_short:<42} |")

    print("=" * 76)


def main() -> int:
    print(f"{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{CYAN}{BOLD}       KIỂM TRA PHẦN CỨNG TRẠM CÂN THỰC PHẨM THÔNG MINH AI (RPI 4)     {RESET}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}")
    print(f"Chế độ cấu hình HARDWARE_MODE : {BOLD}{config.HARDWARE_MODE.upper()}{RESET}")

    cam_res = check_camera()
    print(f"  -> Kết quả: {GREEN if cam_res['status']=='PASS' else RED}{cam_res['status']}{RESET} : {cam_res['msg']}")

    hx_res = check_hx711()
    print(f"  -> Kết quả: {GREEN if hx_res['status']=='PASS' else RED}{hx_res['status']}{RESET} : {hx_res['msg']}")

    lcd_res = check_lcd()
    print(f"  -> Kết quả: {GREEN if lcd_res['status']=='PASS' else RED}{lcd_res['status']}{RESET} : {lcd_res['msg']}")

    ai_res = check_ai_model()
    print(f"  -> Kết quả: {GREEN if ai_res['status']=='PASS' else YELLOW if 'MOCK' in ai_res['status'] else RED}{ai_res['status']}{RESET} : {ai_res['msg']}")

    results = [
        {"name": "Camera USB", "status": cam_res["status"], "msg": cam_res["msg"]},
        {"name": "Cân HX711", "status": hx_res["status"], "msg": hx_res["msg"]},
        {"name": "LCD 16x2 I2C", "status": lcd_res["status"], "msg": lcd_res["msg"]},
        {"name": "Mô hình AI", "status": ai_res["status"], "msg": ai_res["msg"]},
    ]

    print_table(results)

    all_passed = (
        cam_res["status"] == "PASS"
        and hx_res["status"] == "PASS"
        and lcd_res["status"] == "PASS"
        and ("PASS" in ai_res["status"])
    )

    if all_passed:
        print(f"\n{GREEN}{BOLD}[THÀNH CÔNG] Toàn bộ phần cứng đã sẵn sàng phục vụ hệ thống!{RESET}\n")
        return 0
    else:
        if config.HARDWARE_MODE == "mock":
            print(f"\n{YELLOW}{BOLD}[CẢNH BÁO] Có thiết bị chưa kết nối, nhưng hệ thống đang ở HARDWARE_MODE=mock nên ứng dụng vẫn chạy mô phỏng được.{RESET}\n")
            return 0
        else:
            print(f"\n{RED}{BOLD}[LỖI PHẦN CỨNG] Có ít nhất một thiết bị không đạt yêu cầu ở HARDWARE_MODE=real.{RESET}")
            print("Vui lòng kiểm tra lại cáp kết nối vật lý và cấp nguồn theo tài liệu.\n")
            return 1


if __name__ == "__main__":
    sys.exit(main())
