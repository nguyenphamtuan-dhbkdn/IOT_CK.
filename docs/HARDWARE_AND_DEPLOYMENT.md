# HƯỚNG DẪN ĐẤU NỐI PHẦN CỨNG & TRIỂN KHAI HỆ THỐNG TRÊN RASPBERRY PI 4

Tài liệu hướng dẫn chi tiết cách kết nối phần cứng thực tế, hiệu chuẩn, cấu hình dịch vụ nền (Systemd) và thiết lập chế độ tự khởi động Kiosk toàn màn hình cho trạm cân thông minh AI trên Raspberry Pi 4.

---

## 1. SƠ ĐỒ ĐẤU NỐI PHẦN CỨNG THẬT (HARDWARE WIRING)

Hệ thống sử dụng **Raspberry Pi 4 Model B (4GB/8GB)** kết nối với 3 khối ngoại vi:

### 1.1. Cảm biến tải trọng Loadcell + Module ADC 24-bit HX711 (Phương án B)
| Chân HX711 | Chân Vật lý trên Pi 4 (Board Pin) | Ký hiệu BCM (GPIO) | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- |
| **VCC** | Pin 1 ($3.3\text{V}$) | $3.3\text{V}$ Power | **Bắt buộc dùng 3.3V** để bảo vệ GPIO Pi 4 không bị quá áp $5\text{V}$ |
| **GND** | Pin 6 | Ground | Nối mass chung |
| **DT (DOUT)**| Pin 29 | **GPIO 5** | Đường truyền dữ liệu 24-bit bit-banging |
| **SCK (PD_SCK)**| Pin 31 | **GPIO 6** | Đường xung nhịp tạo xung đọc và reset chip |

*Đấu nối Loadcell 4 dây vào HX711:*
- Đỏ: $E+$ (Excitation +)
- Đen: $E-$ (Excitation -)
- Trắng: $A-$ (Signal -)
- Xanh lá: $A+$ (Signal +)

---

### 1.2. Màn hình hiển thị LCD 16x2 I2C (Module chuyển đổi PCF8574)
| Chân I2C PCF8574 | Chân Vật lý Pi 4 | Chân BCM | Chức năng |
| :--- | :--- | :--- | :--- |
| **GND** | Pin 9 | Ground | Mass chung |
| **VCC** | Pin 2 hoặc Pin 4 | $5\text{V}$ | Cấp nguồn cho đèn nền LCD hiển thị sắc nét |
| **SDA** | Pin 3 | **GPIO 2** (I2C1 SDA) | Tuyến truyền dữ liệu I2C |
| **SCL** | Pin 5 | **GPIO 3** (I2C1 SCL) | Tuyến xung nhịp I2C |

> **Địa chỉ I2C mặc định:** `0x27` (hoặc `0x3F` tùy lô chip PCF8574/PCF8574A). Cấu hình trong `.env` (`LCD_I2C_ADDRESS=0x27`).

---

### 1.3. Camera USB (UVC Camera)
- Cắm trực tiếp vào cổng **USB 3.0** (cổng màu xanh dương trên Raspberry Pi 4) để đạt băng thông tối đa.
- Thiết bị tự nhận diện tại `/dev/video0` (hoặc `/dev/video1`).
- Chuẩn giao tiếp: Video4Linux2 (`CAP_V4L2`), nén phần cứng `MJPG`, $640 \times 480$ pixels @ $30\text{ FPS}$, `BUFFERSIZE=1`.

---

## 2. CÀI ĐẶT MÔI TRƯỜNG & PHẦN MỀM TRÊN RASPBERRY PI OS

### Bước 2.1: Bật giao tiếp I2C và Camera trên Raspberry Pi OS
Chạy công cụ cấu hình hệ thống:
```bash
sudo raspi-config
```
1. Chọn **Interface Options** -> **I2C** -> Chọn **Yes** để kích hoạt.
2. Kiểm tra địa chỉ I2C của màn hình LCD:
   ```bash
   sudo apt install -y i2c-tools
   sudo i2cdetect -y 1
   ```
   *Kết quả sẽ hiển thị số `27` hoặc `3f` tại ma trận địa chỉ.*

### Bước 2.2: Cài đặt các gói tối ưu phần cứng qua APT (Bắt buộc)
> **LƯU Ý:** Tuyệt đối không cài `opencv-python` và `numpy` bằng lệnh `pip` trên Pi vì sẽ bị biên dịch mã nguồn C++ mất hàng giờ và dễ tràn RAM gây treo máy. Hãy cài bản tiền biên dịch tối ưu cho chip ARM qua `apt`:

```bash
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-rpi.gpio python3-smbus i2c-tools git
```

### Bước 2.3: Cài đặt mã nguồn dự án & thư viện còn lại
```bash
cd /home/pi
# Clone hoặc copy thư mục IOT_CK
cd /home/pi/IOT_CK

# Tạo file cấu hình môi trường .env
cp .env.example .env

# Cài đặt các thư viện Python bổ trợ
pip install -r requirements.txt --break-system-packages
```

### Bước 2.4: Kích hoạt tăng tốc AI Model NCNN (Tencent NCNN trên ARM NEON)
Mô hình AI nhận diện thực phẩm được xuất dưới dạng **NCNN** gồm 3 file trong `ai_engine/models/`:
- `model.ncnn.param` (Cấu trúc mạng neural 416x416)
- `model.ncnn.bin` (Trọng số nhị phân ~9.6 MB)
- `metadata.yaml` (64 lớp nhãn thực phẩm: Táo, Chuối, Cam, Xoài, Dưa hấu, Cà chua,...)

Để chạy suy luận trực tiếp trên CPU ARM Cortex-A72 của Pi 4 với tốc độ cao nhất (không cần PyTorch nặng hàng GB):
```bash
pip install ncnn --break-system-packages
```

---

## 3. QUY TRÌNH HIỆU CHUẨN CÂN & KIỂM TRA PHẦN CỨNG

### 3.1. Hiệu chuẩn cảm biến cân HX711 (`calibration.py`)
Chương trình sẽ tự động đọc mẫu thô, loại bỏ các gai nhiễu ngoại lai (MAD Outlier Filter), tính toán hệ số `SCALE_RATIO` và **tự động lưu vào file `calibration.json`**:
```bash
python3 calibration.py
```
- **Bước 1:** Bỏ trống bàn cân, nhấn `Enter` để hệ thống tự động Tare (lấy điểm 0).
- **Bước 2:** Đặt vật mẫu chuẩn (ví dụ chai nước 500g hoặc quả cân 500g), nhập khối lượng và nhấn `Enter`.
- Hệ số `SCALE_RATIO` mới sẽ được lưu vĩnh viễn vào `calibration.json` và tự nạp mỗi khi khởi động hệ thống.

### 3.2. Chạy kịch bản tự kiểm tra toàn diện phần cứng & AI (`check_hardware.py`)
Trước khi đưa vào vận hành, chạy kiểm tra tổng thể 4 khối thiết bị (Camera, Cân, LCD, Mô hình AI):
```bash
python3 check_hardware.py
```
Kết quả hiển thị trực quan:
```text
======================================================================
       BẢNG TỔNG HỢP KIỂM TRA PHẦN CỨNG (HARDWARE STATUS)           
======================================================================
| THIẾT BỊ           | KẾT QUẢ  | CHI TIẾT VÀ THÔNG SỐ                       |
+--------------------+----------+--------------------------------------------+
| Camera USB         |   PASS   | Camera hoạt động tốt (640x480 @ 30fps)     |
| Cân HX711          |   PASS   | DT=GPIO5, SCK=GPIO6, Ratio=420.00          |
| LCD 16x2 I2C       |   PASS   | LCD 16x2 phản hồi I2C tại 0x27             |
| Mô hình AI         |   PASS   | Mô hình NCNN hợp lệ (64 lớp, backend: ncnn)|
======================================================================
```

### 3.3. Kiểm thử riêng biệt module AI và cơ sở dữ liệu (`tests/test_ai.py`)
```bash
python3 tests/test_ai.py
```
Kịch bản sẽ tự động kiểm tra pipeline: nạp 3 file NCNN -> đọc 64 nhãn thực phẩm -> suy luận frame 640x480 -> đo độ trễ -> ánh xạ bảng giá CSDL SQLite -> tính tổng tiền và tạo URL VietQR.

---

## 4. THIẾT LẬP DỊCH VỤ SYSTEMD CHO BACKEND (`smart-scale.service`)

Thiết lập ứng dụng chạy ngầm tự động cùng hệ điều hành, tự khởi động lại khi có sự cố.

### Bước 4.1: Đăng ký dịch vụ với systemd
```bash
sudo cp /home/pi/IOT_CK/smart-scale.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smart-scale.service
sudo systemctl start smart-scale.service
```

### Bước 4.2: Quản lý và xem log hoạt động
- Kiểm tra trạng thái dịch vụ:
  ```bash
  sudo systemctl status smart-scale.service
  ```
- Xem log thời gian thực:
  ```bash
  sudo journalctl -u smart-scale.service -f
  ```
- Khởi động lại dịch vụ:
  ```bash
  sudo systemctl restart smart-scale.service
  ```

---

## 5. THIẾT LẬP AUTOSTART KIOSK TRÊN RASPBERRY PI OS

Kiosk mode giúp Raspberry Pi tự động mở trình duyệt toàn màn hình truy cập trạm cân ngay khi cắm nguồn điện.

### Cách 1: Trên Raspberry Pi OS Bookworm (Mặc định dùng Wayland / Wayfire)
Chỉnh sửa file cấu hình Wayfire của người dùng:
```bash
nano ~/.config/wayfire.ini
```
Thêm vào cuối file khối cấu hình sau:
```ini
[autostart]
screensaver = false
dpms = false
kiosk = bash /home/pi/IOT_CK/scripts/autostart_kiosk.sh
```

### Cách 2: Trên Raspberry Pi OS Bullseye / Legacy (Dùng X11)
Chỉnh sửa file autostart của LXDE:
```bash
sudo nano /etc/xdg/lxsession/LXDE-pi/autostart
```
Thêm vào cuối file:
```bash
@xset s off
@xset -dpms
@xset s noblank
@bash /home/pi/IOT_CK/scripts/autostart_kiosk.sh
```

Cấp quyền thực thi cho script:
```bash
chmod +x /home/pi/IOT_CK/scripts/autostart_kiosk.sh
```

---

## 6. CƠ CHẾ TỰ ĐỘNG KẾT NỐI LẠI (PLUG & PLAY RECONNECTION)

Hệ thống được thiết kế khả năng chịu lỗi công nghiệp, tự phục hồi khi thiết bị bị rút đột ngột:

1. **Camera USB:**
   - Khi camera bị rút ra: Luồng đọc nền phát hiện mất khung hình, tự động giải phóng tài nguyên và chuyển giao diện sang khung hình chờ (Standby) có thông báo rõ ràng, không làm đơ Web UI hay sập app.
   - Khi cắm lại vào cổng USB: Thread nền tự động quét lại thiết bị mỗi 2 giây, khôi phục `CAP_V4L2`, tái kích hoạt `MJPG 640x480` và nối lại luồng `/video_feed` mượt mà.

2. **Cảm biến HX711:**
   - Khi cáp tín hiệu GPIO bị lỏng hoặc chân DOUT bị treo mức cao: Trình điều khiển gửi xung kích reset chip phần cứng theo datasheet HX711 (kéo chân SCK lên HIGH $>60\mu\text{s}$ rồi hạ xuống LOW).
   - Tuyệt đối tuân thủ cấu hình `HARDWARE_MODE=real`: Nếu mất cân thật, hệ thống phát cảnh báo rõ ràng trên giao diện và API `/api/hardware/status`, **không tự ý chuyển sang mock**.

3. **Màn hình LCD 16x2 I2C:**
   - Bộ đệm dirty-check bảo vệ I2C: Chỉ truyền lệnh khi dữ liệu thực sự thay đổi, giảm $95\%$ tải trên bus I2C, loại bỏ hoàn toàn hiện tượng nháy chữ.
   - Nếu màn hình bị rút hoặc lỏng nguồn, các hàm ghi I2C tự động bắt lỗi an toàn (catch OSError), ghi log cảnh báo và tiếp tục duy trì hoạt động của toàn bộ trạm cân.

