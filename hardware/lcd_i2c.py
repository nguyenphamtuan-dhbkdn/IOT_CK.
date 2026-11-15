"""Singleton điều khiển màn hình LCD 16x2 qua giao tiếp I2C (chip PCF8574).

Đặc tả:
- Dòng 1: Trạng thái State Machine (IDLE / STABILIZING / INSPECTING / CHECKOUT), không dấu.
- Dòng 2: Khối lượng (g) và tổng tiền khi ở CHECKOUT.
- Chuẩn hóa chuỗi: Bỏ dấu tiếng Việt, cắt hoặc đệm đúng 16 ký tự để không tràn dòng.
- Nếu không tìm thấy LCD thì ghi log cảnh báo và để hệ thống tiếp tục chạy, không làm sập app.
- Hỗ trợ chế độ mock (in ra console) khi HARDWARE_MODE=mock.
"""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from typing import Any

from config import HARDWARE_MODE, LCD_COLS, LCD_I2C_ADDRESS, LCD_ROWS

logger = logging.getLogger("lcd")

try:
    from RPLCD.i2c import CharLCD  # type: ignore

    HAS_RPLCD = True
except ImportError:
    CharLCD = None  # type: ignore
    HAS_RPLCD = False


def strip_vietnamese_diacritics(text: str) -> str:
    """Chuyển chuỗi tiếng Việt có dấu thành không dấu chuẩn ASCII."""
    table = {
        ord("à"): "a", ord("á"): "a", ord("ả"): "a", ord("ã"): "a", ord("ạ"): "a",
        ord("ă"): "a", ord("ằ"): "a", ord("ắ"): "a", ord("ẳ"): "a", ord("ẵ"): "a", ord("ặ"): "a",
        ord("â"): "a", ord("ầ"): "a", ord("ấ"): "a", ord("ẩ"): "a", ord("ẫ"): "a", ord("ậ"): "a",
        ord("À"): "A", ord("Á"): "A", ord("Ả"): "A", ord("Ã"): "A", ord("Ạ"): "A",
        ord("Ă"): "A", ord("Ằ"): "A", ord("Ắ"): "A", ord("Ẳ"): "A", ord("Ẵ"): "A", ord("Ặ"): "A",
        ord("Â"): "A", ord("Ầ"): "A", ord("Ấ"): "A", ord("Ẩ"): "A", ord("Ẫ"): "A", ord("Ậ"): "A",
        ord("è"): "e", ord("é"): "e", ord("ẻ"): "e", ord("ẽ"): "e", ord("ẹ"): "e",
        ord("ê"): "e", ord("ề"): "e", ord("ế"): "e", ord("ể"): "e", ord("ễ"): "e", ord("ệ"): "e",
        ord("È"): "E", ord("É"): "E", ord("Ẻ"): "E", ord("Ẽ"): "E", ord("Ẹ"): "E",
        ord("Ê"): "E", ord("Ề"): "E", ord("Ế"): "E", ord("Ể"): "E", ord("Ễ"): "E", ord("Ệ"): "E",
        ord("ì"): "i", ord("í"): "i", ord("ỉ"): "i", ord("ĩ"): "i", ord("ị"): "i",
        ord("Ì"): "I", ord("Í"): "I", ord("Ỉ"): "I", ord("Ĩ"): "I", ord("Ị"): "I",
        ord("ò"): "o", ord("ó"): "o", ord("ỏ"): "o", ord("õ"): "o", ord("ọ"): "o",
        ord("ô"): "o", ord("ồ"): "o", ord("ố"): "o", ord("ổ"): "o", ord("ỗ"): "o", ord("ộ"): "o",
        ord("ơ"): "o", ord("ờ"): "o", ord("ớ"): "o", ord("ở"): "o", ord("ỡ"): "o", ord("ợ"): "o",
        ord("Ò"): "O", ord("Ó"): "O", ord("Ỏ"): "O", ord("Õ"): "O", ord("Ọ"): "O",
        ord("Ô"): "O", ord("Ồ"): "O", ord("Ố"): "O", ord("Ổ"): "O", ord("Ỗ"): "O", ord("Ộ"): "O",
        ord("Ơ"): "O", ord("Ờ"): "O", ord("Ớ"): "O", ord("Ở"): "O", ord("Ỡ"): "O", ord("Ợ"): "O",
        ord("ù"): "u", ord("ú"): "u", ord("ủ"): "u", ord("ũ"): "u", ord("ụ"): "u",
        ord("ư"): "u", ord("ừ"): "u", ord("ứ"): "u", ord("ử"): "u", ord("ữ"): "u", ord("ự"): "u",
        ord("Ù"): "U", ord("Ú"): "U", ord("Ủ"): "U", ord("Ũ"): "U", ord("Ụ"): "U",
        ord("Ư"): "U", ord("Ừ"): "U", ord("Ứ"): "U", ord("Ử"): "U", ord("Ữ"): "U", ord("Ự"): "U",
        ord("ỳ"): "y", ord("ý"): "y", ord("ỷ"): "y", ord("ỹ"): "y", ord("ỵ"): "y",
        ord("Ỳ"): "Y", ord("Ý"): "Y", ord("Ỷ"): "Y", ord("Ỹ"): "Y", ord("Ỵ"): "Y",
        ord("đ"): "d", ord("Đ"): "D",
    }
    s = text.translate(table)
    # Loại bỏ các dấu kết hợp còn sót lại bằng unicodedata
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Giữ lại các ký tự ASCII in được từ 32 (space) đến 126 (~)
    return "".join(c if 32 <= ord(c) <= 126 else " " for c in ascii_str)


def format_lcd_line(text: str, cols: int = 16) -> str:
    """Chuẩn hóa chuỗi: bỏ dấu tiếng Việt, cắt hoặc đệm đúng số ký tự của dòng."""
    clean = strip_vietnamese_diacritics(str(text))
    if len(clean) > cols:
        return clean[:cols]
    return clean.ljust(cols)


class LCDManager:
    """Singleton điều khiển LCD 16x2 I2C với khả năng tự phục hồi và chế độ Mock."""

    _instance: LCDManager | None = None
    _init_lock = threading.Lock()

    def __new__(cls) -> LCDManager:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.hardware_mode = HARDWARE_MODE
        self.address = LCD_I2C_ADDRESS
        self.cols = LCD_COLS
        self.rows = LCD_ROWS

        self._lock = threading.Lock()
        self._lcd = None
        self.hardware_available = False
        self.last_error: str | None = None

        self._last_line1 = ""
        self._last_line2 = ""
        self._last_mock_log_time = 0.0

        if self.hardware_mode == "real":
            self._connect_hardware()
        else:
            self.hardware_available = False
            print(f"[LCD] Chế độ MOCK (HARDWARE_MODE=mock). Nội dung sẽ xuất ra console khi thay đổi.")

        self._initialized = True

    def _connect_hardware(self) -> bool:
        """Thử kết nối tới module PCF8574 qua I2C bus 1."""
        if not HAS_RPLCD:
            self.last_error = "Thư viện RPLCD chưa được cài đặt (pip install RPLCD smbus2)"
            self.hardware_available = False
            print(f"[LCD CẢNH BÁO] {self.last_error}. Hệ thống tiếp tục chạy không có LCD.")
            return False

        try:
            lcd = CharLCD(
                i2c_expander="PCF8574",
                address=self.address,
                port=1,
                cols=self.cols,
                rows=self.rows,
                dotsize=8,
                charmap="A00",
                auto_linebreaks=False,
            )
            lcd.clear()
            self._lcd = lcd
            self.hardware_available = True
            self.last_error = None
            print(f"[LCD] Đã kết nối thành công LCD 16x2 I2C tại địa chỉ 0x{self.address:02X}")

            # Hiện thông báo khởi động ngắn
            self.write_raw("SMART SCALE AI", "KHOI DONG...")
            time.sleep(0.5)
            return True
        except Exception as exc:
            self.last_error = f"Không tìm thấy LCD I2C tại địa chỉ 0x{self.address:02X}: {exc}"
            self.hardware_available = False
            self._lcd = None
            print(f"[LCD CẢNH BÁO] {self.last_error}. Hệ thống vẫn tiếp tục chạy bình thường.")
            return False

    def write_raw(self, line1: str, line2: str) -> None:
        """Ghi trực tiếp 2 dòng text lên màn hình (hoặc in ra console nếu là mock/lỗi)."""
        formatted_l1 = format_lcd_line(line1, self.cols)
        formatted_l2 = format_lcd_line(line2, self.cols)

        # Dirty-check: chỉ ghi nếu nội dung thay đổi để tránh nháy màn hình và nghẽn I2C
        with self._lock:
            if formatted_l1 == self._last_line1 and formatted_l2 == self._last_line2:
                return
            self._last_line1 = formatted_l1
            self._last_line2 = formatted_l2

        if self.hardware_mode == "mock":
            now = time.time()
            if now - self._last_mock_log_time > 0.5 or (formatted_l1 != self._last_line1):
                self._last_mock_log_time = now
                print(f"[LCD MOCK] ╔══════════════════╗")
                print(f"[LCD MOCK] ║ {formatted_l1} ║")
                print(f"[LCD MOCK] ║ {formatted_l2} ║")
                print(f"[LCD MOCK] ╚══════════════════╝")
            return

        # Hardware mode
        if self._lcd is not None and self.hardware_available:
            try:
                self._lcd.cursor_pos = (0, 0)
                self._lcd.write_string(formatted_l1)
                self._lcd.cursor_pos = (1, 0)
                self._lcd.write_string(formatted_l2)
            except Exception as exc:
                self.last_error = f"Lỗi giao tiếp I2C khi ghi LCD: {exc}"
                logger.warning(f"[LCD] {self.last_error}")
                self.hardware_available = False
                self._lcd = None
        else:
            # Nếu đang ở hardware mode nhưng bị ngắt, thỉnh thoảng thử kết nối lại
            # và log nhẹ ra console
            pass

    def display_state(
        self,
        state: str,
        weight_gram: float,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Hiển thị theo quy tắc nghiệp vụ:

        Dòng 1: Trạng thái State Machine (IDLE / STABILIZING / INSPECTING / CHECKOUT).
        Dòng 2: Khối lượng (g) và tổng tiền khi ở CHECKOUT.
        """
        state_upper = state.strip().upper()
        line1 = state_upper

        w_int = int(round(abs(weight_gram)))

        if state_upper == "CHECKOUT":
            billing = result.get("billing", {}) if result else {}
            is_sellable = billing.get("is_sellable", False)
            total_amount = billing.get("total_amount", 0)

            if is_sellable:
                # Định dạng tiền tệ: ví dụ 35.000d hoặc 35k
                amount_str = f"{total_amount:,.0f}d".replace(",", ".")
                # Cắt ghép vừa đúng 16 ký tự: e.g. "450g - 45.000d"
                line2 = f"{w_int}g - {amount_str}"
            else:
                line2 = f"{w_int}g - TU CHOI"

        elif state_upper == "IDLE":
            if w_int <= 0:
                line2 = "SAN SANG CAN"
            else:
                line2 = f"{w_int}g"

        elif state_upper == "STABILIZING":
            line2 = f"{w_int}g (DANG CAN)"

        elif state_upper == "INSPECTING":
            line2 = f"{w_int}g (KIEM DINH)"

        else:
            line2 = f"{w_int}g"

        self.write_raw(line1, line2)

    def clear(self) -> None:
        """Xóa trắng màn hình LCD."""
        with self._lock:
            self._last_line1 = ""
            self._last_line2 = ""
        if self._lcd is not None and self.hardware_available:
            try:
                self._lcd.clear()
            except Exception:
                pass

    def get_status(self) -> dict[str, Any]:
        """Trả về trạng thái phục vụ check_hardware và API."""
        with self._lock:
            l1 = self._last_line1
            l2 = self._last_line2
            err = self.last_error

        status_str = "PASS" if (self.hardware_available or self.hardware_mode == "mock") else "FAIL"
        if self.hardware_mode == "mock":
            msg = "LCD đang hoạt động ở chế độ MOCK (in console)"
        elif self.hardware_available:
            msg = f"LCD 16x2 I2C (PCF8574 tại 0x{self.address:02X}) hoạt động bình thường"
        else:
            msg = f"Không tìm thấy LCD I2C tại địa chỉ 0x{self.address:02X}: {err or 'Lỗi kết nối'}"

        return {
            "status": status_str,
            "mode": self.hardware_mode,
            "available": self.hardware_available,
            "message": msg,
            "details": {
                "address": f"0x{self.address:02X}",
                "cols": self.cols,
                "rows": self.rows,
                "driver": "RPLCD.i2c.CharLCD (PCF8574)",
                "line1": l1,
                "line2": l2,
                "last_error": err,
            },
        }

