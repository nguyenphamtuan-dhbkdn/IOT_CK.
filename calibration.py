"""Chương trình hiệu chuẩn cảm biến tải trọng Load Cell & ADC HX711 trên Raspberry Pi 4.

Dùng chung driver ScaleManager với hệ thống chính:
- Tare 21 mẫu, kiểm tra độ lệch ≈ 0.
- Lấy trung vị 31 mẫu khi đặt vật mẫu đã biết khối lượng.
- Kiểm tra |delta| >= 500.
- Có tùy chọn đảo dấu (scale_ratio = -scale_ratio) nếu cân bị âm.
- Lưu kết quả vào calibration.json định dạng {"scale_ratio": <float>}.
"""

from __future__ import annotations

import sys
import time

from config import CALIBRATION_FILE, HARDWARE_MODE
from hardware.scale_hx711 import ScaleManager


def main() -> None:
    print("=" * 65)
    print("   CHƯƠNG TRÌNH HIỆU CHUẨN CẢM BIẾN TẢI TRỌNG LOAD CELL & HX711   ")
    print("=" * 65)

    scale = ScaleManager()

    if scale.hardware_mode == "real" and not scale.hardware_available:
        print("\n[LỖI NGHIÊM TRỌNG] Không thể kết nối phần cứng HX711!")
        print(f"Chi tiết: {scale.last_error}")
        print("Vui lòng kiểm tra lại dây DT=GPIO5, SCK=GPIO6, nguồn 3.3V/GND.")
        sys.exit(1)

    print(f"\n+ File lưu hiệu chuẩn: {CALIBRATION_FILE}")
    print(f"+ Hệ số hiện tại     : {scale.scale_ratio:.4f} ({'ĐÃ HIỆU CHUẨN' if scale.calibrated else 'CHƯA HIỆU CHUẨN'})")
    print(f"+ Chế độ hoạt động   : {scale.hardware_mode.upper()}")

    print("\n-----------------------------------------------------------------")
    print("BƯỚC 1: LẤY ĐIỂM 0 (TARE)")
    print("Đảm bảo đĩa cân đang TRỐNG HOÀN TOÀN, không chạm vào cân.")
    input(">> Nhấn Enter để bắt đầu Tare... ")

    ok = scale.tare(samples=21)
    if not ok:
        print("[LỖI] Tare thất bại. Dừng chương trình.")
        sys.exit(1)

    print("\n-----------------------------------------------------------------")
    print("BƯỚC 2: ĐO VẬT MẪU ĐÃ BIẾT TRƯỚC KHỐI LƯỢNG")
    try:
        known_str = input(">> Nhập khối lượng vật mẫu (gram, ví dụ 500): ").strip()
        known_weight = float(known_str) if known_str else 500.0
    except ValueError:
        print("[LỖI] Khối lượng không hợp lệ.")
        sys.exit(1)

    if known_weight <= 0:
        print("[LỖI] Khối lượng phải lớn hơn 0.")
        sys.exit(1)

    input(f">> Đặt vật mẫu {known_weight:.1f}g lên giữa đĩa cân, sau đó nhấn Enter để đo...")
    print(">> Đang thu thập trung vị 31 mẫu chịu tải...")

    try:
        raw_loaded = scale.read_average(samples=31)
    except Exception as exc:
        print(f"[LỖI] Không thể đọc tín hiệu HX711: {exc}")
        sys.exit(1)

    delta = raw_loaded - scale.offset
    print(f"   + Giá trị ADC thô: {raw_loaded:.0f}")
    print(f"   + Điểm 0 (offset): {scale.offset:.0f}")
    print(f"   + Độ lệch (Delta): {delta:.0f}")

    if abs(delta) < 500:
        print("\n[CẢNH BÁO] Độ lệch quá nhỏ (|delta| < 500)!")
        print("Kiểm tra lại: vật mẫu đã đặt lên chưa, cơ cấu cơ khí có bị kẹt chạm không.")
        sys.exit(1)

    scale_ratio = delta / known_weight
    print(f"\n-> Hệ số SCALE_RATIO tính toán được: {scale_ratio:.4f}")

    # Tùy chọn đảo dấu nếu vật nặng mà kết quả âm
    if scale_ratio < 0:
        print("\n[CHÚ Ý] Hệ số tính được mang dấu ÂM (do dây loadcell đấu ngược).")
        ans = input("Bạn có muốn đảo dấu lại thành DƯƠNG không? (Y/n): ").strip().lower()
        if ans != "n":
            scale_ratio = -scale_ratio
            print(f"-> Đã đảo dấu: scale_ratio = {scale_ratio:.4f}")
    else:
        ans = input("Kiểm tra chiều lực: Nhấn Enter để xác nhận, hoặc nhập '-' để đảo dấu: ").strip()
        if ans == "-":
            scale_ratio = -scale_ratio
            print(f"-> Đã đảo dấu: scale_ratio = {scale_ratio:.4f}")

    # Lưu vào calibration.json
    save_ok = scale.save_calibration(scale_ratio)
    if save_ok:
        print(f"\n[THÀNH CÔNG] Đã lưu scale_ratio={scale_ratio:.4f} vào {CALIBRATION_FILE.name}")
        print("Hệ thống chính và service sẽ tự động nạp thông số này khi khởi động!")
    else:
        print("[LỖI] Không thể lưu file calibration.json!")

    print("\n-----------------------------------------------------------------")
    print("BƯỚC 3: KIỂM TRA ĐỘ CHÍNH XÁC (ĐỌC LIÊN TỤC 10 LẦN)")
    print("-----------------------------------------------------------------")
    for i in range(1, 11):
        g = scale.get_grams(samples=9)
        print(f"  Mẫu {i:02d}: {g:7.1f} g  (Lệch so với chuẩn: {abs(g - known_weight):.1f} g)")
        time.sleep(0.2)

    print("\nHiệu chuẩn hoàn tất! Bạn có thể nhấc vật mẫu ra khỏi cân.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Đã hủy quá trình hiệu chuẩn.")
