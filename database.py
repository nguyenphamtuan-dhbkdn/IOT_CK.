"""Lớp dữ liệu SQLite, schema tương đương 3 collection MongoDB."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from config import DATABASE_PATH

_lock = threading.Lock()

VI_PRODUCE_MAP: dict[str, tuple[str, int]] = {
    "Apple": ("Táo Đỏ Nhập Khẩu", 65000),
    "Banana": ("Chuối Tiêu", 28000),
    "Orange": ("Cam Sành", 42000),
    "Mango": ("Xoài Cát Hòa Lộc", 55000),
    "Watermelon": ("Dưa Hấu Đỏ", 22000),
    "Dragon Fruit": ("Thanh Long Ruột Đỏ", 35000),
    "Tomato": ("Cà Chua Đà Lạt", 30000),
    "Potato": ("Khoai Tây Đà Lạt", 32000),
    "Carrot": ("Cà Rốt Đà Lạt", 25000),
    "Avocado": ("Bơ Sáp 034", 60000),
    "Grape": ("Nho Ninh Thuận", 85000),
    "Pineapple": ("Dứa (Thơm)", 20000),
    "Cucumber": ("Dưa Leo", 22000),
    "Cabbage": ("Bắp Cải Trắng", 18000),
    "Lemon": ("Chanh Vàng", 35000),
    "Lime": ("Chanh Tươi Không Hạt", 25000),
    "Guava": ("Ổi Nữ Hoàng", 25000),
    "Berry": ("Dâu Tây", 120000),
    "Strawberry": ("Dâu Tây Đà Lạt", 140000),
    "Lychee": ("Vải Thiều Lục Ngạn", 50000),
    "Peach": ("Đào Tươi", 60000),
    "Pear": ("Lê Đường", 50000),
    "Corn": ("Ngô / Bắp Mỹ", 22000),
    "Mushroom": ("Nấm Tươi", 65000),
    "Red Onion": ("Hành Tím", 45000),
    "White Onion": ("Hành Tây Trắng", 28000),
    "Garlic": ("Tỏi Cô Đơn", 75000),
    "Ginger": ("Gừng Tươi", 45000),
    "Eggplant": ("Cà Tím", 24000),
    "Sweet Potato": ("Khoai Lang Mật", 30000),
    "Bell Pepper": ("Ớt Chuông Đà Lạt", 55000),
    "Cherry": ("Cherry Đỏ", 320000),
    "Cherry Tomato": ("Cà Chua Bi", 45000),
    "Coconut": ("Dừa Xiêm Bến Tre", 25000),
    "Grapefruit": ("Bưởi Da Xanh", 55000),
    "Kiwi": ("Kiwi Xanh", 110000),
    "Mangosteen": ("Măng Cụt", 75000),
    "Passion Fruit": ("Chanh Dây (Chanh Leo)", 35000),
    "Pomegranate": ("Lựu Đỏ", 65000),
    "Rambutan": ("Chôm Chôm", 40000),
    "Star Fruit": ("Khế Ngọt", 25000),
    "Zucchini": ("Bí Ngòi Xanh", 35000),
}

SEED_PRODUCTS = [
    {
        "_id": "prod_apple_01",
        "code": "APPLE",
        "name_vi": "Táo Đỏ Nhập Khẩu",
        "fresh_label": "Apple",
        "rotten_label": "Rotten_Apple",
        "price_per_kg": 65000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_banana_01",
        "code": "BANANA",
        "name_vi": "Chuối Tiêu",
        "fresh_label": "Banana",
        "rotten_label": "Rotten_Banana",
        "price_per_kg": 28000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_orange_01",
        "code": "ORANGE",
        "name_vi": "Cam Sành",
        "fresh_label": "Orange",
        "rotten_label": "Rotten_Orange",
        "price_per_kg": 42000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_mango_01",
        "code": "MANGO",
        "name_vi": "Xoài Cát Hòa Lộc",
        "fresh_label": "Mango",
        "rotten_label": "Rotten_Mango",
        "price_per_kg": 55000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_watermelon_01",
        "code": "WATERMELON",
        "name_vi": "Dưa Hấu Đỏ",
        "fresh_label": "Watermelon",
        "rotten_label": "Rotten_Watermelon",
        "price_per_kg": 22000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_tomato_01",
        "code": "TOMATO",
        "name_vi": "Cà Chua Đà Lạt",
        "fresh_label": "Tomato",
        "rotten_label": "Rotten_Tomato",
        "price_per_kg": 30000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_potato_01",
        "code": "POTATO",
        "name_vi": "Khoai Tây Đà Lạt",
        "fresh_label": "Potato",
        "rotten_label": "Rotten_Potato",
        "price_per_kg": 32000,
        "currency": "VND",
        "is_active": True,
    },
    {
        "_id": "prod_dragon_fruit_01",
        "code": "DRAGON_FRUIT",
        "name_vi": "Thanh Long Ruột Đỏ",
        "fresh_label": "Dragon Fruit",
        "rotten_label": "Rotten_Dragon Fruit",
        "price_per_kg": 35000,
        "currency": "VND",
        "is_active": True,
    },
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "_id": row["id"],
        "code": row["code"],
        "name_vi": row["name_vi"],
        "fresh_label": row["fresh_label"],
        "rotten_label": row["rotten_label"],
        "price_per_kg": row["price_per_kg"],
        "currency": row["currency"],
        "is_active": bool(row["is_active"]),
        "updated_at": row["updated_at"],
    }


@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _lock, get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name_vi TEXT NOT NULL,
                fresh_label TEXT NOT NULL,
                rotten_label TEXT NOT NULL,
                price_per_kg INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'VND',
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS weighing_logs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                product_code TEXT,
                product_name TEXT,
                weight_gram REAL NOT NULL,
                ai_result TEXT NOT NULL,
                billing TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_analytics (
                id TEXT PRIMARY KEY,
                date TEXT UNIQUE NOT NULL,
                total_inspections INTEGER NOT NULL DEFAULT 0,
                fresh_count INTEGER NOT NULL DEFAULT 0,
                rotten_count INTEGER NOT NULL DEFAULT 0,
                total_weight_kg REAL NOT NULL DEFAULT 0,
                total_revenue_vnd INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        now = utc_now_iso()
        for p in SEED_PRODUCTS:
            conn.execute(
                """
                INSERT OR IGNORE INTO products
                (id, code, name_vi, fresh_label, rotten_label, price_per_kg, currency, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p["_id"],
                    p["code"],
                    p["name_vi"],
                    p["fresh_label"],
                    p["rotten_label"],
                    p["price_per_kg"],
                    p["currency"],
                    1 if p["is_active"] else 0,
                    now,
                ),
            )


def list_products(active_only: bool = False) -> list[dict[str, Any]]:
    with _lock, get_conn() as conn:
        sql = "SELECT * FROM products"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY code"
        return [_row_to_product(r) for r in conn.execute(sql)]


def get_product_by_code(code: str) -> dict[str, Any] | None:
    with _lock, get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE code = ?", (code,)).fetchone()
        return _row_to_product(row) if row else None


def get_product_by_label(label: str) -> dict[str, Any] | None:
    """Tìm sản phẩm theo nhãn AI phát hiện được (hỗ trợ cả Apple, Fresh_Apple, Rotten_Apple).
    Nếu sản phẩm thuộc 64 classes mà chưa có trong DB, tự động khởi tạo để trạm cân hoạt động ngay.
    """
    if not label or label in {"Unknown", "none", ""}:
        return None

    clean = label.replace("Fresh_", "").replace("Rotten_", "").replace("fresh_", "").replace("rotten_", "").strip()
    code_cand = clean.upper().replace(" ", "_")

    with _lock, get_conn() as conn:
        # 1. Khớp chính xác theo fresh_label, rotten_label, code hoặc tên
        row = conn.execute(
            """
            SELECT * FROM products
            WHERE fresh_label = ? OR rotten_label = ?
               OR code = ? OR code = ?
               OR LOWER(fresh_label) = LOWER(?)
               OR LOWER(code) = LOWER(?)
               OR LOWER(name_vi) = LOWER(?)
            LIMIT 1
            """,
            (label, label, label.upper(), code_cand, clean, clean, clean),
        ).fetchone()
        if row:
            return _row_to_product(row)

        # 2. Khớp nhãn dạng prefix / suffix (ví dụ: 'Apple' khớp 'Fresh_Apple')
        row = conn.execute(
            """
            SELECT * FROM products
            WHERE fresh_label LIKE ? OR rotten_label LIKE ? OR code LIKE ?
            LIMIT 1
            """,
            (f"%{clean}%", f"%{clean}%", f"%{code_cand}%"),
        ).fetchone()
        if row:
            return _row_to_product(row)

        # 3. Tự động thêm sản phẩm mới vào DB nếu là nhãn thực phẩm hợp lệ
        if clean and clean != "Unknown":
            new_id = f"prod_{code_cand.lower()}"
            name_vi, default_price = VI_PRODUCE_MAP.get(clean, (clean, 40000))
            now = utc_now_iso()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO products
                    (id, code, name_vi, fresh_label, rotten_label, price_per_kg, currency, is_active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (new_id, code_cand, name_vi, clean, f"Rotten_{clean}", default_price, "VND", now),
                )
                row = conn.execute("SELECT * FROM products WHERE id = ?", (new_id,)).fetchone()
                if row:
                    return _row_to_product(row)
            except Exception as e:
                print(f"[DB] Lỗi auto-insert product {clean}: {e}")

    return None


def update_product(product_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name_vi", "price_per_kg", "is_active"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_product_by_id(product_id)
    updates["updated_at"] = utc_now_iso()
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0
    assignments = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [product_id]
    with _lock, get_conn() as conn:
        conn.execute(f"UPDATE products SET {assignments} WHERE id = ?", values)
    return get_product_by_id(product_id)


def get_product_by_id(product_id: str) -> dict[str, Any] | None:
    with _lock, get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _row_to_product(row) if row else None


def insert_weighing_log(doc: dict[str, Any]) -> dict[str, Any]:
    with _lock, get_conn() as conn:
        conn.execute(
            """
            INSERT INTO weighing_logs
            (id, timestamp, product_code, product_name, weight_gram, ai_result, billing)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc["_id"],
                doc["timestamp"],
                doc.get("product_code"),
                doc.get("product_name"),
                doc["weight_gram"],
                json.dumps(doc["ai_result"], ensure_ascii=False),
                json.dumps(doc["billing"], ensure_ascii=False),
            ),
        )
    return doc


def list_logs(limit: int = 50) -> list[dict[str, Any]]:
    with _lock, get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM weighing_logs ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "_id": row["id"],
                "timestamp": row["timestamp"],
                "product_code": row["product_code"],
                "product_name": row["product_name"],
                "weight_gram": row["weight_gram"],
                "ai_result": json.loads(row["ai_result"]),
                "billing": json.loads(row["billing"]),
            }
        )
    return result


def upsert_daily_analytics(quality_status: str, weight_gram: float, revenue: int) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    stat_id = f"stat_{today.replace('-', '_')}"
    is_fresh = quality_status == "FRESH"
    with _lock, get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_analytics WHERE date = ?", (today,)).fetchone()
        if row is None:
            doc = {
                "_id": stat_id,
                "date": today,
                "total_inspections": 1,
                "fresh_count": 1 if is_fresh else 0,
                "rotten_count": 0 if is_fresh else 1,
                "total_weight_kg": round(weight_gram / 1000.0, 3),
                "total_revenue_vnd": revenue if is_fresh else 0,
            }
            conn.execute(
                """
                INSERT INTO daily_analytics
                (id, date, total_inspections, fresh_count, rotten_count, total_weight_kg, total_revenue_vnd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["_id"],
                    doc["date"],
                    doc["total_inspections"],
                    doc["fresh_count"],
                    doc["rotten_count"],
                    doc["total_weight_kg"],
                    doc["total_revenue_vnd"],
                ),
            )
            return doc

        fresh_count = row["fresh_count"] + (1 if is_fresh else 0)
        rotten_count = row["rotten_count"] + (0 if is_fresh else 1)
        total_weight = round(row["total_weight_kg"] + weight_gram / 1000.0, 3)
        revenue_vnd = row["total_revenue_vnd"] + (revenue if is_fresh else 0)
        conn.execute(
            """
            UPDATE daily_analytics
            SET total_inspections = ?, fresh_count = ?, rotten_count = ?,
                total_weight_kg = ?, total_revenue_vnd = ?
            WHERE date = ?
            """,
            (row["total_inspections"] + 1, fresh_count, rotten_count, total_weight, revenue_vnd, today),
        )
        return {
            "_id": row["id"],
            "date": today,
            "total_inspections": row["total_inspections"] + 1,
            "fresh_count": fresh_count,
            "rotten_count": rotten_count,
            "total_weight_kg": total_weight,
            "total_revenue_vnd": revenue_vnd,
        }


def list_analytics(limit: int = 14) -> list[dict[str, Any]]:
    with _lock, get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_analytics ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "_id": r["id"],
            "date": r["date"],
            "total_inspections": r["total_inspections"],
            "fresh_count": r["fresh_count"],
            "rotten_count": r["rotten_count"],
            "total_weight_kg": r["total_weight_kg"],
            "total_revenue_vnd": r["total_revenue_vnd"],
        }
        for r in rows
    ]


def next_log_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"log_{stamp}"
