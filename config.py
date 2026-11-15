"""Cấu hình hệ thống trạm cân AI."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = BASE_DIR / "static" / "captures"
MODEL_DIR = BASE_DIR / "ai_engine" / "models"
if not (MODEL_DIR / "model.ncnn.param").exists() and (BASE_DIR / "models" / "model.ncnn.param").exists():
    MODEL_DIR = BASE_DIR / "models"

MODEL_PATH = MODEL_DIR / "best.onnx"
NCNN_PARAM_PATH = MODEL_DIR / "model.ncnn.param"
NCNN_BIN_PATH = MODEL_DIR / "model.ncnn.bin"
NCNN_METADATA_PATH = MODEL_DIR / "metadata.yaml"
DATABASE_PATH = BASE_DIR / "data" / "smart_scale.db"
CALIBRATION_FILE = BASE_DIR / "calibration.json"

CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# Chế độ phần cứng: 'real' (chạy phần cứng thật trên Pi) hoặc 'mock' (giả lập để test giao diện)
HARDWARE_MODE = os.getenv("HARDWARE_MODE", "real").strip().lower()

# Cảm biến tải trọng Loadcell (5kg) & ADC HX711 (BCM GPIO)
HX711_DT_PIN = int(os.getenv("HX711_DT_PIN", os.getenv("HX711_DOUT_PIN", "5")))
HX711_SCK_PIN = int(os.getenv("HX711_SCK_PIN", "6"))
HX711_INVERT_SIGNAL = os.getenv("HX711_INVERT_SIGNAL", "1") == "1"
HX711_ZERO_BAND_G = float(os.getenv("HX711_ZERO_BAND_G", "0.5"))
HX711_MEDIAN_SAMPLES = int(os.getenv("HX711_MEDIAN_SAMPLES", "9"))

# Tần số cập nhật vòng lặp
WEIGHT_SAMPLE_HZ = 10

# LCD 16x2 I2C (PCF8574)
LCD_I2C_ADDRESS_STR = os.getenv("LCD_I2C_ADDRESS", "0x27").strip()
try:
    LCD_I2C_ADDRESS = int(LCD_I2C_ADDRESS_STR, 16) if LCD_I2C_ADDRESS_STR.startswith(("0x", "0X")) else int(LCD_I2C_ADDRESS_STR)
except ValueError:
    LCD_I2C_ADDRESS = 0x27

LCD_COLS = int(os.getenv("LCD_COLS", "16"))
LCD_ROWS = int(os.getenv("LCD_ROWS", "2"))

# Ngưỡng State Machine (Đưa vào .env để dễ tinh chỉnh)
IDLE_WEIGHT_G = float(os.getenv("IDLE_WEIGHT_G", "10.0"))
DETECT_WEIGHT_G = float(os.getenv("DETECT_WEIGHT_G", "15.0"))
STABILITY_DELTA_G = float(os.getenv("STABILITY_DELTA_G", "2.0"))
STABILITY_HOLD_S = float(os.getenv("STABILITY_HOLD_S", "1.5"))

# Camera
CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "/dev/video0")
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_FOURCC = "MJPG"
CAMERA_BUFFERSIZE = 1

# AI
AI_STRATEGY = os.getenv("AI_STRATEGY", "auto").strip().lower()
AI_CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.50"))
AI_INPUT_SIZE = int(os.getenv("AI_INPUT_SIZE", "416"))
AI_NUM_THREADS = int(os.getenv("AI_NUM_THREADS", "4"))

# VietQR
VIETQR_BANK = os.getenv("VIETQR_BANK", "VCB")
VIETQR_ACCOUNT = os.getenv("VIETQR_ACCOUNT", "0123456789")
VIETQR_ACCOUNT_NAME = os.getenv("VIETQR_ACCOUNT_NAME", "TRAM CAN AI")

SECRET_KEY = os.getenv("SECRET_KEY", "smart-ai-scale-dev-key")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
DEBUG = os.getenv("DEBUG", "0") == "1"
