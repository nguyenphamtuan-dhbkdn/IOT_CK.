#!/bin/bash
# ==============================================================================
# Script tự động khởi chạy giao diện Kiosk toàn màn hình trên Raspberry Pi 4
# ==============================================================================

# Vô hiệu hóa tính năng tắt màn hình / màn hình chờ (Screen Blanking / DPMS)
if command -v xset &> /dev/null; then
    xset s noblank
    xset s off
    xset -dpms
fi

# Chờ dịch vụ Backend Flask sẵn sàng trước khi mở trình duyệt
TARGET_URL="http://localhost:5000"
echo "[KIOSK] Đang kiểm tra kết nối backend tại $TARGET_URL..."

for i in {1..30}; do
    if curl -s --head "$TARGET_URL" | grep "200 OK" > /dev/null; then
        echo "[KIOSK] Backend đã sẵn sàng sau $i giây."
        break
    fi
    sleep 1
done

# Xóa thông báo lỗi crash của Chromium trước khi mở
sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' ~/.config/chromium/Default/Preferences 2>/dev/null
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' ~/.config/chromium/Default/Preferences 2>/dev/null

# Khởi chạy Chromium ở chế độ Kiosk toàn màn hình
echo "[KIOSK] Khởi động Chromium Kiosk Mode..."
exec chromium-browser \
    --noerrdialogs \
    --disable-infobars \
    --kiosk \
    --incognito \
    --check-for-update-interval=31536000 \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --disable-translate \
    --disable-features=Translate \
    --autoplay-policy=no-user-gesture-required \
    "$TARGET_URL"

