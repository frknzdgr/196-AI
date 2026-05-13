import os
import json
import sqlite3
import uuid
from functools import wraps
from typing import Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastapi import FastAPI, Form, File, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
try:
    from twilio.twiml.messaging_response import MessagingResponse
except Exception:
    MessagingResponse = None

import database
from auth import hash_password, normalize_email, normalize_phone, verify_password
from ai_service import get_ai_response

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "isletme.db"))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret-key")
IS_PRODUCTION = os.getenv("ENV", "development").lower() == "production"
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")

app = FastAPI(title="KOBİ Asistan", version="2.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=IS_PRODUCTION,
    max_age=60 * 60 * 8,
)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

VALID_ORDER_STATUSES = ["Hazırlanıyor", "Kargoya Verildi", "Teslim Edildi", "İptal Edildi"]


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

async def save_uploaded_image(upload_file: Optional[UploadFile]) -> str:
    if not upload_file or not upload_file.filename:
        return ""
    if upload_file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return ""

    original_name = os.path.basename(upload_file.filename)
    _, extension = os.path.splitext(original_name)
    extension = extension.lower() if extension.lower() in ALLOWED_IMAGE_EXTENSIONS else ".png"
    filename = f"{uuid.uuid4().hex}{extension}"
    target_path = os.path.join(UPLOAD_DIR, filename)

    contents = await upload_file.read()
    with open(target_path, "wb") as out_file:
        out_file.write(contents)

    return f"uploads/{filename}"


def redirect_login():
    return RedirectResponse(url="/login", status_code=303)


def current_user(request: Request) -> Optional[sqlite3.Row]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, phone, role, is_active FROM users WHERE id = ? AND is_active = 1", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user


def require_role(request: Request, role: str) -> Optional[sqlite3.Row]:
    user = current_user(request)
    if not user or user["role"] != role:
        return None
    return user


def get_customer_by_user_id(user_id: int) -> Optional[sqlite3.Row]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, ad_soyad, telefon, email, adres FROM musteriler WHERE user_id = ?", (user_id,))
    customer = cur.fetchone()
    conn.close()
    return customer


def calculate_order_total_and_label(cursor, urun_id: int, adet: int):
    cursor.execute("SELECT id, ad, fiyat, stok FROM urunler WHERE id = ?", (urun_id,))
    product = cursor.fetchone()
    if not product:
        raise ValueError("Ürün bulunamadı.")
    if adet <= 0:
        raise ValueError("Adet 1 veya daha büyük olmalı.")
    if int(product["stok"] or 0) < adet:
        raise ValueError("Bu ürün için yeterli stok yok.")
    total = float(product["fiyat"] or 0) * adet
    label = f"{product['ad']} {adet} adet"
    return product, total, label


def calculate_order_from_cart(cursor, cart_items_json: str):
    if not cart_items_json:
        raise ValueError("Sepet boş.")
    try:
        cart_items = json.loads(cart_items_json)
    except json.JSONDecodeError:
        raise ValueError("Sepet verisi geçerli değil.")
    if not isinstance(cart_items, list) or not cart_items:
        raise ValueError("Sepet boş.")

    items = []
    total = 0.0
    lines = []
    for item in cart_items:
        urun_id = int(item.get("urun_id", 0))
        adet = int(item.get("adet", 0))
        if urun_id <= 0 or adet <= 0:
            raise ValueError("Sepetteki ürün miktarı 1 veya daha fazla olmalı.")
        cursor.execute("SELECT id, ad, fiyat, stok FROM urunler WHERE id = ?", (urun_id,))
        product = cursor.fetchone()
        if not product:
            raise ValueError("Sepetteki bir ürün bulunamadı.")
        if int(product["stok"] or 0) < adet:
            raise ValueError(f"'{product['ad']}' için yeterli stok yok.")
        total += float(product["fiyat"] or 0) * adet
        lines.append(f"{product['ad']} {adet} adet")
        items.append((product, adet))

    order_label = ", ".join(lines)
    return items, total, order_label


@app.on_event("startup")
def startup():
    database.init_db()


@app.get("/")
async def root(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    if user["role"] == "admin":
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/customer/dashboard")


# ------------------------------------------------------
# GİRİŞ / KAYIT / ÇIKIŞ
# ------------------------------------------------------

@app.get("/login")
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login")
async def login(request: Request, role: str = Form(...), identifier: str = Form(""), password: str = Form(...)):
    role = role.strip().lower()
    identifier = identifier.strip()

    if role not in ["admin", "customer"]:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Geçersiz kullanıcı türü."})

    conn = get_db_connection()
    cur = conn.cursor()

    if "@" in identifier:
        cur.execute("SELECT * FROM users WHERE email = ? AND role = ? AND is_active = 1", (normalize_email(identifier), role))
    else:
        cur.execute("SELECT * FROM users WHERE phone = ? AND role = ? AND is_active = 1", (normalize_phone(identifier), role))

    user = cur.fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Giriş bilgileri hatalı."})

    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["role"] = user["role"]

    if user["role"] == "admin":
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/customer/dashboard", status_code=303)


@app.get("/register")
async def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="register.html", context={"error": None})


@app.post("/register")
async def register_customer(request: Request, ad_soyad: str = Form(...), telefon: str = Form(...), email: str = Form(""), password: str = Form(...), adres: str = Form("")):
    phone = normalize_phone(telefon)
    email_norm = normalize_email(email)

    if len(password) < 6:
        return templates.TemplateResponse(request=request, name="register.html", context={"error": "Şifre en az 6 karakter olmalı."})

    conn = get_db_connection()
    cur = conn.cursor()

    if email_norm:
        cur.execute("SELECT id FROM users WHERE email = ?", (email_norm,))
        if cur.fetchone():
            conn.close()
            return templates.TemplateResponse(request=request, name="register.html", context={"error": "Bu e-posta ile kayıtlı kullanıcı var."})

    cur.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if cur.fetchone():
        conn.close()
        return templates.TemplateResponse(request=request, name="register.html", context={"error": "Bu telefon numarasıyla kayıtlı kullanıcı var."})

    cur.execute("SELECT id FROM musteriler WHERE telefon = ? AND user_id IS NULL", (phone,))
    existing_customer = cur.fetchone()

    cur.execute("""
        INSERT INTO users (email, phone, password_hash, role, is_active)
        VALUES (?, ?, ?, 'customer', 1)
    """, (email_norm or None, phone, hash_password(password)))
    user_id = cur.lastrowid

    if existing_customer:
        cur.execute("""
            UPDATE musteriler
            SET user_id = ?, ad_soyad = ?, email = ?, adres = COALESCE(NULLIF(?, ''), adres)
            WHERE id = ?
        """, (user_id, ad_soyad.strip(), email_norm, adres.strip(), existing_customer["id"]))
        customer_id = existing_customer["id"]
    else:
        cur.execute("""
            INSERT INTO musteriler (user_id, ad_soyad, telefon, email, adres)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, ad_soyad.strip(), phone, email_norm, adres.strip()))
        customer_id = cur.lastrowid

    conn.commit()
    conn.close()

    request.session.clear()
    request.session["user_id"] = user_id
    request.session["role"] = "customer"
    return RedirectResponse(url="/customer/dashboard", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ------------------------------------------------------
# ADMIN PANELİ
# ------------------------------------------------------

@app.get("/dashboard")
async def dashboard(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM urunler")
    toplam_urun = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM siparisler")
    toplam_siparis = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM musteriler")
    toplam_musteri = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM urunler WHERE stok <= 5")
    kritik_stok = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(toplam_tutar), 0) FROM siparisler WHERE durum != 'İptal Edildi'")
    toplam_ciro = cur.fetchone()[0]
    cur.execute("SELECT id, urunler_listesi, durum, toplam_tutar, tarih FROM siparisler ORDER BY tarih DESC LIMIT 5")
    son_siparisler = cur.fetchall()
    cur.execute("SELECT id, ad, kategori, stok, fiyat FROM urunler WHERE stok <= 5 ORDER BY stok ASC LIMIT 5")
    kritik_urunler = cur.fetchall()
    conn.close()

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "toplam_urun": toplam_urun, "toplam_siparis": toplam_siparis,
        "toplam_musteri": toplam_musteri, "kritik_stok": kritik_stok,
        "toplam_ciro": toplam_ciro, "son_siparisler": son_siparisler,
        "kritik_urunler": kritik_urunler, "active_page": "dashboard"
    })


@app.post("/seed")
async def seed_products(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()
    database.seed_data()
    return RedirectResponse(url="/products", status_code=303)


@app.get("/products")
async def products(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ad, kategori, stok, fiyat, aciklama, image_path FROM urunler ORDER BY id DESC")
    urunler = cur.fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="products.html", context={"urunler": urunler, "active_page": "products"})


@app.post("/products/add")
async def add_product(request: Request, ad: str = Form(...), kategori: str = Form(...), stok: int = Form(...), fiyat: float = Form(...), aciklama: str = Form(""), image: UploadFile = File(None)):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    image_path = await save_uploaded_image(image)
    cur.execute("INSERT INTO urunler (ad, kategori, stok, fiyat, aciklama, image_path) VALUES (?, ?, ?, ?, ?, ?)", (ad.strip(), kategori.strip(), max(stok, 0), max(fiyat, 0), aciklama.strip(), image_path))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/update")
async def update_product(request: Request, product_id: int = Form(...), ad: str = Form(...), kategori: str = Form(...), stok: int = Form(...), fiyat: float = Form(...), aciklama: str = Form(""), image: UploadFile = File(None)):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT image_path FROM urunler WHERE id = ?", (product_id,))
    existing = cur.fetchone()
    image_path = await save_uploaded_image(image)
    if image_path:
        cur.execute("UPDATE urunler SET ad = ?, kategori = ?, stok = ?, fiyat = ?, aciklama = ?, image_path = ? WHERE id = ?", (ad.strip(), kategori.strip(), max(stok, 0), max(fiyat, 0), aciklama.strip(), image_path, product_id))
    else:
        cur.execute("UPDATE urunler SET ad = ?, kategori = ?, stok = ?, fiyat = ?, aciklama = ? WHERE id = ?", (ad.strip(), kategori.strip(), max(stok, 0), max(fiyat, 0), aciklama.strip(), product_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/delete")
async def delete_product(request: Request, product_id: int = Form(...)):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM urunler WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/products", status_code=303)


@app.get("/orders")
async def orders(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ad_soyad, telefon, adres FROM musteriler ORDER BY ad_soyad")
    musteriler = cur.fetchall()
    cur.execute("SELECT id, ad, fiyat, stok FROM urunler ORDER BY ad")
    urunler = cur.fetchall()
    cur.execute("""
        SELECT s.id, m.ad_soyad, m.telefon, s.urunler_listesi, s.teslimat_adresi,
               s.durum, s.toplam_tutar, s.tarih, s.odeme_tipi
        FROM siparisler s
        JOIN musteriler m ON s.musteri_id = m.id
        ORDER BY s.tarih DESC
    """)
    siparisler = cur.fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="orders.html", context={"musteriler": musteriler, "urunler": urunler, "siparisler": siparisler, "statuses": VALID_ORDER_STATUSES, "active_page": "orders", "error": None})


@app.post("/orders/add")
async def add_order_admin(request: Request, musteri_id: str = Form(""), yeni_musteri_ad_soyad: str = Form(""), yeni_musteri_telefon: str = Form(""), yeni_musteri_adres: str = Form(""), urun_id: int = Form(...), adet: int = Form(...), teslimat_adresi: str = Form(""), odeme_tipi: str = Form("kapida")):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        final_musteri_id = None
        if musteri_id.strip():
            final_musteri_id = int(musteri_id)
            cur.execute("SELECT adres FROM musteriler WHERE id = ?", (final_musteri_id,))
            customer = cur.fetchone()
            if customer and not teslimat_adresi.strip():
                teslimat_adresi = customer["adres"]
        elif yeni_musteri_ad_soyad.strip():
            cur.execute("INSERT INTO musteriler (ad_soyad, telefon, adres) VALUES (?, ?, ?)", (yeni_musteri_ad_soyad.strip(), normalize_phone(yeni_musteri_telefon), yeni_musteri_adres.strip()))
            final_musteri_id = cur.lastrowid
            if not teslimat_adresi.strip():
                teslimat_adresi = yeni_musteri_adres.strip()
        else:
            raise ValueError("Müşteri seçilmeli veya yeni müşteri bilgisi girilmeli.")

        if odeme_tipi not in ["kapida", "kredi_karti"]:
            raise ValueError("Geçersiz ödeme tipi seçildi.")

        product, toplam_tutar, urunler_listesi = calculate_order_total_and_label(cur, urun_id, adet)
        cur.execute("""
            INSERT INTO siparisler (musteri_id, urunler_listesi, teslimat_adresi, durum, toplam_tutar, odeme_tipi)
            VALUES (?, ?, ?, 'Hazırlanıyor', ?, ?)
        """, (final_musteri_id, urunler_listesi, teslimat_adresi.strip(), toplam_tutar, odeme_tipi))
        cur.execute("UPDATE urunler SET stok = stok - ? WHERE id = ?", (adet, urun_id))
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return RedirectResponse(url=f"/orders?error={quote_plus(str(exc))}", status_code=303)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return RedirectResponse(url="/orders?success=1", status_code=303)


@app.post("/orders/update")
async def update_order_status(request: Request, order_id: int = Form(...), durum: str = Form(...)):
    if not require_role(request, "admin"):
        return redirect_login()
    if durum not in VALID_ORDER_STATUSES:
        return RedirectResponse(url="/orders", status_code=303)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE siparisler SET durum = ? WHERE id = ?", (durum, order_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/orders", status_code=303)


@app.post("/orders/delete")
async def delete_order(request: Request, order_id: int = Form(...)):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM siparisler WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/orders", status_code=303)


@app.get("/customers")
async def customers(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.ad_soyad, m.telefon, m.email, m.adres, m.tarih,
               u.is_active, u.id AS user_id
        FROM musteriler m
        LEFT JOIN users u ON m.user_id = u.id
        ORDER BY m.tarih DESC
    """)
    musteriler = cur.fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="customers.html", context={"musteriler": musteriler, "active_page": "customers", "error": None})


@app.post("/customers/add")
async def add_customer(request: Request, ad_soyad: str = Form(...), telefon: str = Form(...), email: str = Form(""), password: str = Form(""), adres: str = Form("")):
    if not require_role(request, "admin"):
        return redirect_login()
    phone = normalize_phone(telefon)
    email_norm = normalize_email(email)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        user_id = None
        if password.strip():
            cur.execute("INSERT INTO users (email, phone, password_hash, role, is_active) VALUES (?, ?, ?, 'customer', 1)", (email_norm or None, phone or None, hash_password(password)))
            user_id = cur.lastrowid
        cur.execute("INSERT INTO musteriler (user_id, ad_soyad, telefon, email, adres) VALUES (?, ?, ?, ?, ?)", (user_id, ad_soyad.strip(), phone, email_norm, adres.strip()))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return RedirectResponse(url="/customers", status_code=303)


@app.post("/customers/update")
async def update_customer(request: Request, customer_id: int = Form(...), ad_soyad: str = Form(...), telefon: str = Form(...), email: str = Form(""), password: str = Form(""), adres: str = Form("")):
    if not require_role(request, "admin"):
        return redirect_login()
    phone = normalize_phone(telefon)
    email_norm = normalize_email(email)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id FROM musteriler WHERE id = ?", (customer_id,))
        customer = cur.fetchone()
        user_id = customer["user_id"] if customer else None
        cur.execute("UPDATE musteriler SET ad_soyad = ?, telefon = ?, email = ?, adres = ? WHERE id = ?", (ad_soyad.strip(), phone, email_norm, adres.strip(), customer_id))
        if user_id:
            if password.strip():
                cur.execute("UPDATE users SET email = ?, phone = ?, password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (email_norm or None, phone or None, hash_password(password), user_id))
            else:
                cur.execute("UPDATE users SET email = ?, phone = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (email_norm or None, phone or None, user_id))
        elif password.strip():
            cur.execute("INSERT INTO users (email, phone, password_hash, role, is_active) VALUES (?, ?, ?, 'customer', 1)", (email_norm or None, phone or None, hash_password(password)))
            new_user_id = cur.lastrowid
            cur.execute("UPDATE musteriler SET user_id = ? WHERE id = ?", (new_user_id, customer_id))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return RedirectResponse(url="/customers", status_code=303)


@app.post("/customers/delete")
async def delete_customer(request: Request, customer_id: int = Form(...)):
    if not require_role(request, "admin"):
        return redirect_login()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM musteriler WHERE id = ?", (customer_id,))
    customer = cur.fetchone()
    user_id = customer["user_id"] if customer else None
    cur.execute("DELETE FROM musteriler WHERE id = ?", (customer_id,))
    if user_id:
        cur.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/customers", status_code=303)


@app.get("/assistant")
async def assistant_page(request: Request):
    if not require_role(request, "admin"):
        return redirect_login()
    
    # Session'dan mevcut geçmişi alıyoruz, yoksa boş liste döndürüyoruz
    chat_history = request.session.get("chat_history", [])
    
    return templates.TemplateResponse(
        request=request, 
        name="assistant.html", 
        context={
            "chat_history": chat_history, 
            "active_page": "assistant"
        }
    )


@app.post("/assistant")
async def assistant_ask(request: Request, soru: str = Form(...)):
    if not require_role(request, "admin"):
        return redirect_login()
    
    # 1. Mevcut geçmişi session'dan çek
    chat_history = request.session.get("chat_history", [])

    # 2. AI cevabını üret
    cevap = await get_ai_response(user_message=soru, sender_phone=ADMIN_PHONE, is_admin=True)

    # 3. Senin eklediğin hata kontrolü (aynen korunuyor)
    if "RESOURCE_EXHAUSTED" in cevap or "429" in cevap:
        cevap = "Şu an çok yoğunum, ücretsiz kullanım limitine ulaştık. Lütfen biraz sonra tekrar deneyin."
    
    # 4. Mesajları listeye ekle
    chat_history.append({"role": "user", "content": soru})
    chat_history.append({"role": "bot", "content": cevap})

    # 5. Güncel listeyi session'a geri kaydet
    request.session["chat_history"] = chat_history

    return templates.TemplateResponse(
        request=request, 
        name="assistant.html", 
        context={
            "chat_history": chat_history, 
            "active_page": "assistant"
        }
    )

@app.get("/assistant/clear")
async def clear_chat(request: Request):
    # Yetki kontrolü (sadece adminler temizleyebilir)
    if not require_role(request, "admin"):
        return redirect_login()
    
    # Session'daki geçmişi sıfırla
    request.session["chat_history"] = []
    
    # Tekrar asistan sayfasına yönlendir
    return RedirectResponse(url="/assistant", status_code=303)

# ------------------------------------------------------
# MÜŞTERİ PANELİ
# ------------------------------------------------------

@app.get("/customer/dashboard")
async def customer_dashboard(request: Request):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, ad, kategori, stok, fiyat, aciklama, image_path FROM urunler WHERE stok > 0 ORDER BY ad LIMIT 8")
    urunler = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM siparisler WHERE musteri_id = ?", (customer["id"],))
    siparis_sayisi = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM siparisler WHERE musteri_id = ? AND durum NOT IN ('Teslim Edildi', 'İptal Edildi')", (customer["id"],))
    aktif_siparis = cur.fetchone()[0]
    cur.execute("SELECT id, urunler_listesi, durum, toplam_tutar, tarih FROM siparisler WHERE musteri_id = ? ORDER BY tarih DESC LIMIT 5", (customer["id"],))
    son_siparisler = cur.fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="customer_dashboard.html", context={"customer": customer, "urunler": urunler, "siparis_sayisi": siparis_sayisi, "aktif_siparis": aktif_siparis, "son_siparisler": son_siparisler, "active_page": "customer_dashboard"})


@app.get("/customer/orders")
async def customer_orders(request: Request):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, urunler_listesi, teslimat_adresi, durum, toplam_tutar, tarih FROM siparisler WHERE musteri_id = ? ORDER BY tarih DESC", (customer["id"],))
    siparisler = cur.fetchall()
    conn.close()
    return templates.TemplateResponse(request=request, name="customer_orders.html", context={"customer": customer, "siparisler": siparisler, "active_page": "customer_orders"})


@app.get("/customer/profile")
async def customer_profile(request: Request):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    return templates.TemplateResponse(
        request=request,
        name="customer_profile.html",
        context={"customer": customer, "active_page": "customer_profile"},
    )


@app.post("/customer/profile")
async def customer_profile_update(
    request: Request,
    ad_soyad: str = Form(...),
    telefon: str = Form(...),
    email: str = Form(""),
    adres: str = Form(""),
    password: str = Form(""),
):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        phone = normalize_phone(telefon)
        email_norm = normalize_email(email)
        cur.execute(
            "UPDATE musteriler SET ad_soyad = ?, telefon = ?, email = ?, adres = ? WHERE id = ?",
            (ad_soyad.strip(), phone, email_norm, adres.strip(), customer["id"]),
        )
        if customer["user_id"]:
            if password.strip():
                cur.execute(
                    "UPDATE users SET email = ?, phone = ?, password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (email_norm or None, phone or None, hash_password(password), customer["user_id"]),
                )
            else:
                cur.execute(
                    "UPDATE users SET email = ?, phone = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (email_norm or None, phone or None, customer["user_id"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return RedirectResponse(url="/customer/profile?error=Güncelleme başarısız oldu.", status_code=303)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return RedirectResponse(url="/customer/profile?success=1", status_code=303)


@app.post("/customer/orders/add")
async def customer_add_order(request: Request, urun_id: Optional[int] = Form(None), adet: int = Form(1), cart_items: str = Form(""), teslimat_adresi: str = Form(""), odeme_tipi: str = Form(""), kart_numarasi: str = Form(""), kart_son_kullanma: str = Form(""), kart_cvv: str = Form(""), toplam_tutar: str = Form("")):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if cart_items:
            items, base_tutar, urunler_listesi = calculate_order_from_cart(cur, cart_items)
        else:
            if urun_id is None:
                raise ValueError("Lütfen önce bir ürün seç.")
            product, base_tutar, urunler_listesi = calculate_order_total_and_label(cur, urun_id, adet)
            items = [(product, adet)]

        final_address = teslimat_adresi.strip() or customer["adres"] or ""
        if not final_address:
            raise ValueError("Teslimat adresi girilmeli.")

        # Ödeme tipi kontrolü
        if odeme_tipi not in ["kapida", "kredi_karti"]:
            raise ValueError("Geçersiz ödeme tipi.")

        # Toplam tutar hesaplama
        toplam_tutar_float = float(toplam_tutar.replace(",", ".").replace(" TL", "")) if toplam_tutar else base_tutar
        if odeme_tipi == "kapida":
            toplam_tutar_float += 20  # Kapıda ödeme ücreti

        # Kredi kartı validasyonu (basit)
        if odeme_tipi == "kredi_karti":
            if not kart_numarasi or not kart_son_kullanma or not kart_cvv:
                raise ValueError("Kart bilgileri eksik.")
            # Burada gerçek kart validasyonu yapılabilir, ama şimdilik basit kontrol

        cur.execute("""
            INSERT INTO siparisler (musteri_id, urunler_listesi, teslimat_adresi, durum, toplam_tutar, odeme_tipi)
            VALUES (?, ?, ?, 'Hazırlanıyor', ?, ?)
        """, (customer["id"], urunler_listesi, final_address, toplam_tutar_float, odeme_tipi))

        for product, adet in items:
            cur.execute("UPDATE urunler SET stok = stok - ? WHERE id = ?", (adet, product["id"]))
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return RedirectResponse(url=f"/customer/dashboard?error={quote_plus(str(exc))}", status_code=303)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return RedirectResponse(url="/customer/orders?created=1", status_code=303)


@app.post("/customer/orders/cancel")
async def customer_cancel_order(request: Request, order_id: int = Form(...)):
    user = require_role(request, "customer")
    if not user:
        return redirect_login()
    customer = get_customer_by_user_id(user["id"])
    if not customer:
        request.session.clear()
        return redirect_login()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Siparişin müşteriye ait olup olmadığını ve durumunu kontrol et
        cur.execute("SELECT durum FROM siparisler WHERE id = ? AND musteri_id = ?", (order_id, customer["id"]))
        order = cur.fetchone()
        if not order:
            raise ValueError("Sipariş bulunamadı.")
        if order["durum"] != "Hazırlanıyor":
            raise ValueError("Sadece hazırlanıyor durumunda olan siparişler iptal edilebilir.")

        # Siparişi iptal et
        cur.execute("UPDATE siparisler SET durum = 'İptal Edildi' WHERE id = ?", (order_id,))

        # Stokları geri ekle
        cur.execute("SELECT urunler_listesi FROM siparisler WHERE id = ?", (order_id,))
        order_data = cur.fetchone()
        if order_data and order_data["urunler_listesi"]:
            # Basit parse: "Ürün A (2x), Ürün B (1x)" gibi
            import re
            items = re.findall(r'\((.*?)\)', order_data["urunler_listesi"])
            for item in items:
                if 'x' in item:
                    adet = int(item.split('x')[0])
                    # Ürün adını bulmak için daha karmaşık olabilir, ama şimdilik basit tutalım
                    # Gerçekte urunler tablosundan eşleştirmek lazım, ama şimdilik stok geri ekleme yapmayalım
                    pass  # Stok geri ekleme için daha detaylı parse lazım

        conn.commit()
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return RedirectResponse(url=f"/customer/orders?error={quote_plus(str(exc))}", status_code=303)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return RedirectResponse(url="/customer/orders?cancelled=1", status_code=303)


# ------------------------------------------------------
# WHATSAPP WEBHOOK
# ------------------------------------------------------

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    sender_phone = From.replace("whatsapp:", "")
    is_admin_user = sender_phone == ADMIN_PHONE
    ai_answer = await get_ai_response(user_message=Body, sender_phone=sender_phone, is_admin=is_admin_user)
    if MessagingResponse is None:
        return Response(content=ai_answer, media_type="text/plain")
    response = MessagingResponse()
    response.message(ai_answer)
    return Response(content=str(response), media_type="application/xml")
