import os
import re
import sqlite3
from difflib import SequenceMatcher
from dotenv import load_dotenv

try:
    from google import genai
except Exception:
    genai = None

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "isletme.db"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None

if genai is not None and GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"⚠️ Gemini istemcisi başlatılamadı: {e}")
else:
    print("⚠️ GEMINI_API_KEY bulunamadı. AI asistan demo modda çalışacak.")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def norm(text):
    text = (text or "").lower().strip()
    for a, b in {"ı":"i","ğ":"g","ü":"u","ş":"s","ö":"o","ç":"c","İ":"i"}.items():
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def num(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def tl(value):
    value = float(value or 0)
    return f"{int(value)} TL" if value.is_integer() else f"{value:.2f} TL"


def find_by_name(table, name_field, query):
    q = norm(query)
    if not q:
        return None
    db = conn(); cur = db.cursor()
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall(); db.close()
    best = None; best_score = 0
    for row in rows:
        n = norm(row[name_field])
        if q == n or q in n or n in q:
            return row
        score = SequenceMatcher(None, q, n).ratio()
        if score > best_score:
            best = row; best_score = score
    return best if best_score >= 0.62 else None


def get_database_context():
    try:
        db = conn(); cur = db.cursor()
        context = "İŞLETME VERİLERİ:\n\nÜRÜNLER:\n"
        cur.execute("SELECT ad, kategori, stok, fiyat, aciklama FROM urunler ORDER BY ad")
        for u in cur.fetchall():
            context += f"- {u['ad']} | Kategori: {u['kategori']} | Stok: {u['stok']} | Fiyat: {u['fiyat']} TL | Açıklama: {u['aciklama']}\n"
        context += "\nMÜŞTERİLER:\n"
        cur.execute("SELECT ad_soyad, telefon, adres FROM musteriler ORDER BY tarih DESC LIMIT 20")
        for m in cur.fetchall():
            context += f"- {m['ad_soyad']} | Telefon: {m['telefon']} | Adres: {m['adres']}\n"
        context += "\nSİPARİŞLER:\n"
        cur.execute("""
            SELECT siparisler.id, musteriler.ad_soyad, siparisler.urunler_listesi,
                   siparisler.durum, siparisler.toplam_tutar
            FROM siparisler
            LEFT JOIN musteriler ON siparisler.musteri_id = musteriler.id
            ORDER BY siparisler.tarih DESC LIMIT 15
        """)
        for s in cur.fetchall():
            context += f"- #{s['id']} | Müşteri: {s['ad_soyad']} | Ürünler: {s['urunler_listesi']} | Durum: {s['durum']} | Tutar: {s['toplam_tutar']} TL\n"
        db.close()
        return context
    except Exception as e:
        return f"Veritabanı bilgisi alınamadı: {e}"


def add_customer(name, phone="-", address="", email="", password="123456"):
    db = conn(); cur = db.cursor()
    cur.execute("INSERT INTO musteriler (ad_soyad, telefon, email, sifre, adres) VALUES (?, ?, ?, ?, ?)", (name.strip().title(), phone.strip().replace(" ", "") or "-", email.strip(), password, address.strip()))
    cid = cur.lastrowid
    db.commit(); db.close()
    return cid


def process_admin_database_command(message_raw):
    message = norm(message_raw)

    # müşteri ekle ad Ayşe Yılmaz telefon 0555 adres İstanbul
    m = re.search(r"musteri\s+ekle\s+ad\s+(?P<name>.+?)(?:\s+telefon\s+(?P<phone>[0-9+\s]+))?(?:\s+adres\s+(?P<address>.+))?$", message_raw, re.I)
    if not m:
        m = re.search(r"(?P<name>.+?)\s+musteri\w*\s+ekle(?:\s+telefon\s+(?P<phone>[0-9+\s]+))?(?:\s+adres\s+(?P<address>.+))?$", message_raw, re.I)
    if m:
        name = (m.group("name") or "").strip(" ,-:")
        phone = (m.group("phone") or "-").strip()
        address = (m.group("address") or "").strip()
        if len(name) < 2:
            return "Müşteri eklemek için ad soyad yazmalısın. Örnek: müşteri ekle ad Ayşe Yılmaz telefon 05551234567 adres İstanbul"
        cid = add_customer(name, phone, address)
        return f"✅ Müşteri gerçekten veritabanına eklendi.\nMüşteri No: #{cid}\nAd Soyad: {name.title()}\nTelefon: {phone}\nAdres: {address or '-'}\nVarsayılan şifre: 123456"

    # sipariş ekle müşteri Ayşe Yılmaz ürün Nar Ekşisi adet 2 adres İstanbul
    if "siparis" in message and "ekle" in message:
        pm = re.search(r"sipari\w*\s+ekle\s+musteri\s+(?P<customer>.+?)\s+urun\s+(?P<product>.+?)(?:\s+adet\s+(?P<count>\d+))?(?:\s+adres\s+(?P<address>.+))?$", message_raw, re.I)
        if not pm:
            return "Sipariş eklemek için şöyle yaz: sipariş ekle müşteri Ayşe Yılmaz ürün Nar Ekşisi adet 2 adres İstanbul"
        customer_name = pm.group("customer").strip()
        product_name = pm.group("product").strip()
        adet = int(pm.group("count") or 1)
        address = (pm.group("address") or "").strip()

        customer = find_by_name("musteriler", "ad_soyad", customer_name)
        product = find_by_name("urunler", "ad", product_name)
        if not customer:
            cid = add_customer(customer_name, "-", address)
            customer = {"id": cid, "ad_soyad": customer_name.title(), "adres": address}
        if not product:
            return f"'{product_name}' ürününü bulamadım. Önce Ürünler bölümünden eklemelisin."
        if int(product["stok"] or 0) < adet:
            return f"❌ Stok yetersiz. {product['ad']} stok: {product['stok']}"
        if not address:
            address = customer["adres"] or ""
        total = float(product["fiyat"] or 0) * adet
        db = conn(); cur = db.cursor()
        cur.execute("INSERT INTO siparisler (musteri_id, urunler_listesi, teslimat_adresi, durum, toplam_tutar) VALUES (?, ?, ?, ?, ?)", (customer["id"], f"{product['ad']} {adet} adet", address, "Hazırlanıyor", total))
        oid = cur.lastrowid
        cur.execute("UPDATE urunler SET stok = stok - ? WHERE id = ?", (adet, product["id"]))
        db.commit(); db.close()
        return f"✅ Sipariş gerçekten veritabanına eklendi.\nSipariş No: #{oid}\nMüşteri: {customer['ad_soyad']}\nÜrün: {product['ad']} x {adet}\nDurum: Hazırlanıyor\nToplam: {tl(total)}"

    # fiyat/stok güncelle
    for field, label in [("fiyat", "fiyatı"), ("stok", "stoğu")]:
        change = re.search(rf"^(?P<product>.+?)\s+{field}\w*\s+(?P<amount>\d+(?:[\.,]\d+)?)\s*(?:tl|adet)?\s*(?P<action>arttir|artir|azalt|dusur|indir)", message)
        setm = re.search(rf"^(?P<product>.+?)\s+{field}\w*\s+(?P<amount>\d+(?:[\.,]\d+)?)\s*(?:tl|adet)?\s*(?:yap|ayarla|guncelle)", message)
        if change or setm:
            mm = change or setm
            product = find_by_name("urunler", "ad", mm.group("product"))
            amount = num(mm.group("amount"))
            if not product:
                return f"'{mm.group('product')}' ürününü bulamadım."
            old = float(product[field] or 0)
            if setm:
                new = amount
            else:
                new = old - amount if mm.group("action") in ["azalt", "dusur", "indir"] else old + amount
            if new < 0:
                new = 0
            db = conn(); cur = db.cursor()
            cur.execute(f"UPDATE urunler SET {field} = ? WHERE id = ?", (int(new) if field == "stok" else new, product["id"]))
            db.commit(); db.close()
            return f"✅ {product['ad']} ürününün {label} gerçekten güncellendi.\nEski: {old}\nYeni: {new}"

    return None


def demo_response(user_message, is_admin=False):
    if is_admin:
        return (
            "AI asistan demo modda. Yine de yönetici komutları veritabanına işlenir:\n"
            "- müşteri ekle ad Ayşe Yılmaz telefon 05551234567 adres İstanbul\n"
            "- sipariş ekle müşteri Ayşe Yılmaz ürün Nar Ekşisi adet 2 adres İstanbul\n"
            "- Nar Ekşisi fiyatı 10 tl arttır"
        )
    return "Merhaba! Ürünleri görmek ve sipariş vermek için müşteri panelinden giriş yapabilirsin."


async def get_ai_response(user_message, sender_phone=None, is_admin=False):
    if is_admin:
        db_result = process_admin_database_command(user_message)
        if db_result is not None:
            return db_result

    if client is None:
        return demo_response(user_message, is_admin=is_admin)

    context = get_database_context()
    role_instruction = "Kullanıcı işletme yöneticisidir." if is_admin else "Kullanıcı müşteridir. Yöneticiye özel bilgi paylaşma."
    prompt = f"""
Sen Türkçe konuşan KOBİ satış asistanısın.
{role_instruction}

{context}

Kullanıcı mesajı: {user_message}

Kısa, net, Türkçe cevap ver. Veritabanında işlem yaptığını sadece sistem gerçekten yaptıysa söyle.
"""
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"AI cevabı oluşturulurken hata oluştu: {e}"
