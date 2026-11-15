#!/usr/bin/env python3
"""tests/test_ai.py — Kiểm thử toàn diện module AI (NCNN / ONNX / Mock).

Kiểm tra:
1. Đọc 3 file mô hình NCNN: model.ncnn.param, model.ncnn.bin, metadata.yaml.
2. Nạp danh sách 64 nhãn thực phẩm từ metadata.yaml.
3. Khởi tạo Strategy (NCNN / Ultralytics / Mock) không làm sập app.
4. Chạy suy luận thử nghiệm trên frame 640x480 và đo độ trễ (latency).
5. Ánh xạ nhãn phát hiện sang cơ sở dữ liệu sản phẩm (SQLite).
6. Tính toán đơn giá VietQR với khối lượng thử nghiệm.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Thêm thư mục gốc dự án vào PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import numpy as np

import config
from ai_engine.detector import (
    CLASS_NAMES,
    NCNNStrategy,
    build_ai_strategy,
    load_metadata_names,
    quality_from_label,
)
from core.pricing import select_pricing
from database import get_product_by_label, init_db

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def test_model_files() -> tuple[bool, str]:
    print(f"\n{BOLD}[1/6] Kiểm tra sự tồn tại của 3 file mô hình NCNN trong ai_engine/models/...{RESET}")
    param_ok = config.NCNN_PARAM_PATH.exists()
    bin_ok = config.NCNN_BIN_PATH.exists()
    meta_ok = config.NCNN_METADATA_PATH.exists()

    print(f"  - model.ncnn.param : {'OK' if param_ok else 'THIẾU'} ({config.NCNN_PARAM_PATH})")
    print(f"  - model.ncnn.bin   : {'OK' if bin_ok else 'THIẾU'} ({config.NCNN_BIN_PATH})")
    print(f"  - metadata.yaml    : {'OK' if meta_ok else 'THIẾU'} ({config.NCNN_METADATA_PATH})")

    if param_ok and bin_ok and meta_ok:
        bin_size_mb = config.NCNN_BIN_PATH.stat().st_size / (1024 * 1024)
        return True, f"Đầy đủ 3 file NCNN (model.ncnn.bin: {bin_size_mb:.2f} MB)"
    return False, "Thiếu ít nhất 1 file NCNN trong ai_engine/models/"


def test_metadata_classes() -> tuple[bool, str]:
    print(f"\n{BOLD}[2/6] Đọc danh sách nhãn lớp từ metadata.yaml...{RESET}")
    names = load_metadata_names(config.NCNN_METADATA_PATH)
    count = len(names)
    print(f"  -> Đã nạp {count} nhãn lớp.")
    sample = [names[i] for i in sorted(names.keys())[:5]]
    print(f"  -> 5 nhãn đầu tiên: {', '.join(sample)}")

    if count >= 60:
        return True, f"Đã nạp thành công {count} nhãn thực phẩm"
    return False, f"Số nhãn quá ít ({count} nhãn)"


def test_strategy_build() -> tuple[bool, str]:
    print(f"\n{BOLD}[3/6] Khởi tạo AI Strategy qua factory build_ai_strategy()...{RESET}")
    strat = build_ai_strategy()
    ready = strat.is_ready
    backend = getattr(strat, "backend", strat.name)
    print(f"  -> Strategy name : {strat.name}")
    print(f"  -> Backend       : {backend}")
    print(f"  -> Ready         : {ready}")

    return True, f"Strategy: {strat.name} (backend: {backend}, ready: {ready})"


def test_inference_pipeline() -> tuple[bool, str]:
    print(f"\n{BOLD}[4/6] Chạy thử suy luận AI trên khung hình 640x480...{RESET}")
    strat = build_ai_strategy()

    # Tạo frame giả lập 640x480
    frame = np.full((480, 640, 3), 200, dtype=np.uint8)

    started = time.perf_counter()
    result = strat.predict(frame, 450.0)
    latency_ms = int((time.perf_counter() - started) * 1000)

    print(f"  -> Lớp phát hiện  : {result.get('detected_class')}")
    print(f"  -> Trạng thái     : {result.get('quality_status')}")
    print(f"  -> Độ tin cậy     : {result.get('confidence')}")
    print(f"  -> Thời gian xử lý: {result.get('inference_time_ms')} ms (tổng: {latency_ms} ms)")
    print(f"  -> Chiến lược     : {result.get('strategy')}")

    required_keys = ["detected_class", "quality_status", "confidence", "inference_time_ms", "strategy"]
    if all(k in result for k in required_keys):
        return True, f"Suy luận thành công: {result['detected_class']} ({result['quality_status']}) trong {latency_ms}ms"
    return False, "Thiếu trường dữ liệu trong kết quả predict"


def test_db_product_mapping() -> tuple[bool, str]:
    print(f"\n{BOLD}[5/6] Kiểm tra ánh xạ nhãn AI sang cơ sở dữ liệu SQLite...{RESET}")
    init_db()

    test_labels = ["Apple", "Banana", "Orange", "Mango", "Watermelon"]
    matched = 0
    for lbl in test_labels:
        prod = get_product_by_label(lbl)
        if prod:
            matched += 1
            print(f"  - '{lbl}' -> [{prod['code']}] {prod['name_vi']} ({prod['price_per_kg']:,} đ/kg)")
        else:
            print(f"  - '{lbl}' -> {RED}Không tìm thấy{RESET}")

    if matched == len(test_labels):
        return True, f"Khớp toàn bộ {matched}/{len(test_labels)} nhãn mẫu"
    return False, f"Chỉ khớp {matched}/{len(test_labels)} nhãn mẫu"


def test_pricing_and_vietqr() -> tuple[bool, str]:
    print(f"\n{BOLD}[6/6] Kiểm tra tính tiền và tạo URL VietQR...{RESET}")
    weight_g = 500.0
    prod = get_product_by_label("Apple")
    price_kg = prod["price_per_kg"] if prod else 65000

    # Nhánh FRESH
    bill_fresh = select_pricing("FRESH", "Apple").quote(weight_g, price_kg, "APPLE")
    total_fresh = bill_fresh["total_amount"]
    qr_url = bill_fresh.get("qr_payload")
    print(f"  - [FRESH] Khối lượng {weight_g}g -> {total_fresh:,} đ (is_sellable={bill_fresh['is_sellable']})")
    print(f"    VietQR: {qr_url[:60]}...")

    # Nhánh ROTTEN
    bill_rotten = select_pricing("ROTTEN", "Rotten_Apple").quote(weight_g, price_kg, "APPLE")
    print(f"  - [ROTTEN] is_sellable={bill_rotten['is_sellable']}, payment_status={bill_rotten['payment_status']}")

    if bill_fresh["is_sellable"] and not bill_rotten["is_sellable"] and total_fresh > 0:
        return True, f"Tính giá chuẩn xác: {total_fresh:,} đ (FRESH), khóa thanh toán (ROTTEN)"
    return False, "Lỗi logic chính sách giá hoặc VietQR"


def main() -> int:
    print(f"{CYAN}{BOLD}======================================================================{RESET}")
    print(f"{CYAN}{BOLD}          KIỂM THỬ KẾT NỐI MÔ HÌNH AI NCNN VÀO DỰ ÁN TRẠM CÂN          {RESET}")
    print(f"{CYAN}{BOLD}======================================================================{RESET}")

    tests = [
        ("Tệp mô hình NCNN", test_model_files),
        ("Nhãn 64 lớp metadata", test_metadata_classes),
        ("Khởi tạo AI Strategy", test_strategy_build),
        ("Pipeline suy luận AI", test_inference_pipeline),
        ("Ánh xạ CSDL sản phẩm", test_db_product_mapping),
        ("Tính giá và VietQR", test_pricing_and_vietqr),
    ]

    results = []
    all_ok = True

    for name, func in tests:
        try:
            ok, msg = func()
            results.append((name, "PASS" if ok else "FAIL", msg))
            if not ok:
                all_ok = False
        except Exception as exc:
            results.append((name, "ERROR", str(exc)))
            all_ok = False

    print("\n" + "=" * 76)
    print(f"{BOLD}                    BẢNG TỔNG KẾT KIỂM THỬ AI                          {RESET}")
    print("=" * 76)
    print(f"| {'MỤC KIỂM TRA':<26} | {'KẾT QUẢ':<8} | {'CHI TIẾT':<34} |")
    print("+-" + "-" * 26 + "-+-" + "-" * 8 + "-+-" + "-" * 34 + "-+")
    for name, st, msg in results:
        badge = f"{GREEN}{BOLD} PASS {RESET}" if st == "PASS" else f"{RED}{BOLD} {st} {RESET}"
        msg_short = msg[:34]
        print(f"| {name:<26} | {badge:<17} | {msg_short:<34} |")
    print("=" * 76)

    if all_ok:
        print(f"\n{GREEN}{BOLD}[THÀNH CÔNG] Mô hình AI đã được tích hợp hoàn chỉnh vào dự án!{RESET}\n")
        return 0
    else:
        print(f"\n{YELLOW}{BOLD}[LƯU Ý] Có một số mục cần kiểm tra lại theo thông báo ở trên.{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
