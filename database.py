import os
import sqlite3
from dotenv import load_dotenv
from auth import hash_password, normalize_email, normalize_phone

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "isletme.db"))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(column[1] == column_name for column in cursor.fetchall())


def add_column_if_not_exists(cursor, table_name, column_name, column_definition):
    if not column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            phone TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'customer')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL,
            kategori TEXT NOT NULL,
            stok INTEGER NOT NULL DEFAULT 0 CHECK(stok >= 0),
            fiyat REAL NOT NULL DEFAULT 0 CHECK(fiyat >= 0),
            aciklama TEXT DEFAULT '',
            image_path TEXT DEFAULT '',
            tarih DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    add_column_if_not_exists(cursor, "urunler", "image_path", "TEXT DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS musteriler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            ad_soyad TEXT NOT NULL,
            telefon TEXT NOT NULL,
            email TEXT DEFAULT '',
            adres TEXT DEFAULT '',
            tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS siparisler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            musteri_id INTEGER NOT NULL,
            urunler_listesi TEXT NOT NULL,
            teslimat_adresi TEXT DEFAULT '',
            durum TEXT NOT NULL DEFAULT 'Hazırlanıyor'
                CHECK(durum IN ('Hazırlanıyor', 'Kargoya Verildi', 'Teslim Edildi', 'İptal Edildi')),
            toplam_tutar REAL NOT NULL DEFAULT 0 CHECK(toplam_tutar >= 0),
            tarih DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (musteri_id) REFERENCES musteriler(id) ON DELETE CASCADE
        )
    """)

    # Eski demo veritabanından gelen kolonları güvenli biçimde genişlet.
    add_column_if_not_exists(cursor, "musteriler", "user_id", "INTEGER")
    add_column_if_not_exists(cursor, "musteriler", "email", "TEXT DEFAULT ''")
    add_column_if_not_exists(cursor, "musteriler", "adres", "TEXT DEFAULT ''")
    add_column_if_not_exists(cursor, "musteriler", "tarih", "DATETIME DEFAULT CURRENT_TIMESTAMP")

    add_column_if_not_exists(cursor, "siparisler", "teslimat_adresi", "TEXT DEFAULT ''")
    add_column_if_not_exists(cursor, "siparisler", "durum", "TEXT DEFAULT 'Hazırlanıyor'")
    add_column_if_not_exists(cursor, "siparisler", "toplam_tutar", "REAL DEFAULT 0")
    add_column_if_not_exists(cursor, "siparisler", "odeme_tipi", "TEXT DEFAULT ''")
    add_column_if_not_exists(cursor, "siparisler", "tarih", "DATETIME DEFAULT CURRENT_TIMESTAMP")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_siparisler_musteri_id ON siparisler(musteri_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_siparisler_durum ON siparisler(durum)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_urunler_ad ON urunler(ad)")

    create_or_update_bootstrap_admin(cursor)
    migrate_legacy_customer_passwords(cursor)

    conn.commit()
    conn.close()
    print("✅ Üretime yakın veritabanı şeması hazırlandı.")


def create_or_update_bootstrap_admin(cursor):
    admin_email = normalize_email(os.getenv("ADMIN_EMAIL", "admin@kobi.com"))
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin12345!")

    cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    existing_admin = cursor.fetchone()

    if existing_admin:
        return

    cursor.execute("""
        INSERT INTO users (email, phone, password_hash, role, is_active)
        VALUES (?, NULL, ?, 'admin', 1)
    """, (admin_email, hash_password(admin_password)))


def migrate_legacy_customer_passwords(cursor):
    # Eski sürümde musteriler.sifre düz metin tutuluyordu. Kolon varsa hash'li users tablosuna taşır.
    if not column_exists(cursor, "musteriler", "sifre"):
        return

    cursor.execute("""
        SELECT id, ad_soyad, telefon, email, sifre, user_id
        FROM musteriler
        WHERE user_id IS NULL AND telefon IS NOT NULL AND telefon != ''
    """)
    rows = cursor.fetchall()

    for row in rows:
        phone = normalize_phone(row["telefon"])
        email = normalize_email(row["email"] or "") or None
        raw_password = row["sifre"] or "123456"

        cursor.execute("SELECT id FROM users WHERE phone = ?", (phone,))
        user = cursor.fetchone()

        if user:
            user_id = user["id"]
        else:
            cursor.execute("""
                INSERT INTO users (email, phone, password_hash, role, is_active)
                VALUES (?, ?, ?, 'customer', 1)
            """, (email, phone, hash_password(raw_password)))
            user_id = cursor.lastrowid

        cursor.execute("UPDATE musteriler SET user_id = ? WHERE id = ?", (user_id, row["id"]))


def seed_data():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM urunler")
    mevcut_urun_sayisi = cursor.fetchone()[0]

    if mevcut_urun_sayisi == 0:
        urunler = [
            ("Hatay Zeytinyağı", "Yağ", 20, 350, "Soğuk sıkım doğal zeytinyağı"),
            ("Nar Ekşisi", "Sos", 15, 150, "Katkısız ev yapımı nar ekşisi"),
            ("Biber Salçası", "Salça", 8, 120, "Acı biber salçası"),
            ("Domates Salçası", "Salça", 10, 110, "Ev yapımı domates salçası"),
            ("Defne Sabunu", "Kozmetik", 4, 80, "Doğal defne sabunu"),
            ("Künefe Peyniri", "Süt Ürünü", 6, 220, "Taze künefe peyniri"),
            ("Kurutulmuş Zahter", "Baharat", 3, 95, "Hatay usulü zahter"),
            ("Cevizli Sucuk", "Tatlı", 12, 180, "Doğal cevizli sucuk"),
            ("Kabak Tatlısı", "Tatlı", 5, 130, "Ev yapımı kabak tatlısı"),
            ("Kırma Zeytin", "Zeytin", 18, 160, "Hatay kırma yeşil zeytin")
        ]
        cursor.executemany("""
            INSERT INTO urunler (ad, kategori, stok, fiyat, aciklama)
            VALUES (?, ?, ?, ?, ?)
        """, urunler)

    conn.commit()
    conn.close()
    print("✅ Örnek ürün kontrolü tamamlandı.")


if __name__ == "__main__":
    init_db()
    seed_data()
