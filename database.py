import sqlite3
import os
from datetime import datetime

# Dosya yolunu garantiye alalım
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "isletme.db")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute('''CREATE TABLE IF NOT EXISTS urunler (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad TEXT NOT NULL,
        kategori TEXT,
        stok INTEGER DEFAULT 0,
        fiyat REAL DEFAULT 0.0
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS musteriler (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telefon TEXT UNIQUE NOT NULL, 
        ad_soyad TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS siparisler (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER,
        teslimat_adresi TEXT,
        urunler_listesi TEXT, -- JSON veya metin olarak sipariş detayı
        durum TEXT DEFAULT 'Hazırlanıyor',
        toplam_tutar REAL,
        tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (musteri_id) REFERENCES musteriler(id)
    )''')

    conn.commit()
    conn.close()
    print("✅ Veritabanı ve tablolar güncellendi.")

# --- MÜŞTERİ ARAÇLARI ---

def stok_sorgula(urun_adi: str) -> str:
    def turkish_lower(s):
        return s.replace('İ', 'i').replace('I', 'ı').replace('Ş', 'ş').replace('Ğ', 'ğ').replace('Ü', 'ü').replace('Ö', 'ö').lower()
    
    arama_terimi = turkish_lower(urun_adi)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # SQL seviyesinde 'LIKE' kullanarak daha geniş arama yapalım
    cursor.execute("SELECT ad, stok, fiyat FROM urunler WHERE ad LIKE ?", (f"%{urun_adi}%",))
    res = cursor.fetchone() # İlk eşleşeni al
    
    if not res:
        # Eğer SQL bulamazsa eski Python döngüsü mantığına (fallback) dön
        cursor.execute("SELECT ad, stok, fiyat FROM urunler")
        tum_urunler = cursor.fetchall()
        for ad, stok, fiyat in tum_urunler:
            if arama_terimi in turkish_lower(ad) or turkish_lower(ad) in arama_terimi:
                res = (ad, stok, fiyat)
                break
    
    conn.close()
    
    if res:
        return f"{res[0]} stoğu: {res[1]} adet/kg. Birim fiyatı: {res[2]} TL."
    return f"'{urun_adi}' ismine benzer bir ürün bulamadım"

def siparis_olustur(telefon: str, ad_soyad: str, adres: str, urunler_ve_adetler: str, toplam_fiyat: float) -> str:
    """Müşteri için yeni sipariş kaydı oluşturur."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Müşteriyi bul veya oluştur
        cursor.execute("INSERT OR IGNORE INTO musteriler (telefon, ad_soyad) VALUES (?, ?)", (telefon, ad_soyad))
        cursor.execute("SELECT id FROM musteriler WHERE telefon = ?", (telefon,))
        musteri_id = cursor.fetchone()[0]

        # Siparişi ekle
        cursor.execute('''INSERT INTO siparisler (musteri_id, teslimat_adresi, urunler_listesi, toplam_tutar) 
                          VALUES (?, ?, ?, ?)''', (musteri_id, adres, urunler_ve_adetler, toplam_fiyat))
        siparis_id = cursor.lastrowid
        conn.commit()
        return f"✅ Siparişiniz başarıyla alındı! Sipariş No: {siparis_id}. Toplam: {toplam_fiyat} TL."
    except Exception as e:
        return f"❌ Sipariş oluşturulurken hata: {str(e)}"
    finally:
        conn.close()

def siparis_durumu(siparis_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT durum, teslimat_adresi FROM siparisler WHERE id = ?", (siparis_id,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return f"{siparis_id} nolu sipariş durumu: **{res[0]}**. Adres: {res[1]}"
    return "Sipariş bulunamadı."

# --- ADMIN ARAÇLARI ---

def fiyat_guncelle(urun_adi: str, yeni_fiyat: float) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE urunler SET fiyat = ? WHERE ad LIKE ?", (yeni_fiyat, f"%{urun_adi}%"))
    conn.commit()
    changed = conn.total_changes
    conn.close()
    return f"✅ {urun_adi} fiyatı {yeni_fiyat} TL oldu." if changed > 0 else "❌ Ürün bulunamadı."

def stok_duzelt(urun_adi: str, miktar: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE urunler SET stok = ? WHERE ad LIKE ?", (miktar, f"%{urun_adi}%"))
    conn.commit()
    conn.close()
    return f"✅ {urun_adi} yeni stoğu: {miktar}."

def kritik_stok_raporu() -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT ad, stok FROM urunler WHERE stok < 5")
    res = cursor.fetchall()
    conn.close()
    if res:
        return "🚨 Kritik Stoklar:\n" + "\n".join([f"- {r[0]}: {r[1]}" for r in res])
    return "✅ Stoklar normal."

# --- SEED DATA (Sadece ilk kurulumda) ---
def seed_data():
    urunler = [
        ("Acı Biber Salçası", "Salça", 50, 180.0),
        ("Tatlı Biber Salçası", "Salça", 45, 180.0),
        ("Köy Tipi Domates Salçası", "Salça", 60, 150.0),
        ("Hakiki Nar Ekşisi (700ml)", "Sos", 30, 320.0),
        ("Zahterli Kahvaltılık Sos", "Sos", 25, 110.0),
        ("Halhalı Kırma Yeşil Zeytin", "Zeytin", 100, 210.0),
        ("Siyah Sele Zeytin", "Zeytin", 80, 195.0),
        ("Attun Siyah Zeytin", "Zeytin", 70, 185.0),
        ("Soğuk Sıkım Sızma Zeytinyağı (1L)", "Yağ", 150, 480.0),
        ("Yeni Hasat Zeytinyağı (5L)", "Yağ", 40, 2250.0),
        ("Hatay Sünme Peyniri", "Peynir", 35, 290.0),
        ("Sürk Peyniri (Baharatlı Çökelek)", "Peynir", 50, 145.0),
        ("Taze Lavaş Peyniri", "Peynir", 30, 240.0),
        ("Tuzlu Yoğurt", "Süt Ürünleri", 45, 135.0),
        ("Künefelik Peynir (Tuzsuz)", "Peynir", 40, 275.0),
        ("Toz Zahter (Kahvaltılık)", "Baharat", 100, 90.0),
        ("Dağ Kekiği (Bilye)", "Baharat", 80, 120.0),
        ("İpek Pul Biber", "Baharat", 60, 210.0),
        ("Özel Karışım Köfte Baharatı", "Baharat", 70, 140.0),
        ("Kuru Nane", "Baharat", 50, 80.0),
        ("Çörek Otu", "Baharat", 40, 95.0),
        ("Kireçte Kabak Tatlısı", "Tatlı", 25, 280.0),
        ("Cevizli Sucuk (Pekmezli)", "Tatlı", 35, 340.0),
        ("Kömbe Kurabiyesi (7 Baharatlı)", "Unlu Mamul", 100, 190.0),
        ("Tuzlu Fıstık", "Kuruyemiş", 100, 230.0),
        ("Hatay Yerli Ceviz İçi", "Kuruyemiş", 40, 490.0),
        ("Karakılçık Bulguru", "Bakliyat", 100, 75.0),
        ("Kırmızı Mercimek (Yerli)", "Bakliyat", 200, 58.0),
        ("Kuru Patlıcan (Dizi)", "Kurutulmuş", 120, 140.0),
        ("Kuru Biber (Dizi)", "Kurutulmuş", 120, 130.0),
        ("Erişte (El Kesmesi)", "Unlu Mamul", 60, 95.0),
        ("İçli Köfte (Oruk - Adet)", "Hazır Gıda", 200, 40.0),
        ("Kaytaz Böreği", "Hazır Gıda", 150, 30.0),
        ("Samandağ Biberi (Taze)", "Sebze", 50, 85.0),
        ("Saf Defne Sabunu", "Kozmetik", 300, 60.0),
        ("Zeytinyağlı Sabun", "Kozmetik", 250, 50.0),
        ("Turunç Reçeli", "Reçel", 30, 150.0),
        ("İncir Reçeli", "Reçel", 30, 140.0),
        ("Hatay İpek Şal", "Tekstil", 15, 800.0),
        ("Aşurelik Buğday", "Bakliyat", 80, 45.0)
    ]
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Önce masayı bir silelim ki üst üste binmesin
    cursor.execute("DELETE FROM urunler") 
    
    cursor.executemany("INSERT INTO urunler (ad, kategori, stok, fiyat) VALUES (?, ?, ?, ?)", urunler)
    conn.commit()
    conn.close()
    print("✨ Veritabanı 40 ürünle sıfırdan kuruldu.")

    
if __name__ == "__main__":
    init_db()
    #seed_data()