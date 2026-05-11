import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
import database

load_dotenv()

# ÖNEMLİ: Eğer asenkron (async) hata veriyorsa Client'ı normal kullanacağız
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def get_ai_response(user_message: str, sender_phone: str, is_admin: bool = False):
    try:
        # Araçları belirle
        tools = [database.stok_sorgula, database.siparis_durumu, database.siparis_olustur]
        if is_admin:
            tools.extend([database.fiyat_guncelle, database.stok_duzelt, database.kritik_stok_raporu])

        # Talimatı belirle
        if is_admin:
            instr = f"""Sen dükkan sahibisin (Admin). Telefonun: {sender_phone}. Stok ve fiyat yönetebilirsin.
            İş bitirici ol! Eğer admin '10 TL zam yap' gibi bir komut verirse:
            1. ÖNCE 'stok_sorgula' ile ürünün mevcut fiyatını kendin kontrol et.
            2. Yeni fiyatı kendin hesapla.
            3. SONRA 'fiyat_guncelle' fonksiyonunu çağır.
            Admine 'bilmiyorum' diye soru sorma, elindeki araçları (tools) sırayla kullan."""
        else:
            instr = f"""Sen Hatay yerel ürünleri satan bir dükkanın satış asistanısın. 
            Müşteri nosu: {sender_phone}.
    
            SİPARİŞ AKIŞI (BU SIRAYI TAKİP ET):
            1. Müşteri bir ürün istediğinde 'stok_sorgula' ile kontrol et ve fiyatı söyle.
            2. Eğer ürün net değilse (pul biber mi acı biber mi gibi) netleştir.
            3. Ürün netleştiğinde Müşteriden şu bilgileri SIRAYLA iste: 'Ad Soyad' ve 'Açık Adres'.
            4. Tüm bilgiler tamamsa, toplam tutarı hesapla ve müşteriye 'Onaylıyor musunuz?' diye sor.
            5. Müşteri 'Onaylıyorum' veya 'Evet' dediği an 'siparis_olustur' fonksiyonunu çağır.
    
            KURAL: Sipariş tamamlanmadan 'Hoş geldiniz', 'Nasılsınız' gibi boşa vakit harcayan cümlelerle süreci uzatma. Hedefin siparişi veritabanına yazdırmak."""

        # Chat oturumu oluştur (Model ismini sende çalışanla değiştir: gemini-2.0-flash-lite vb.)
        chat = client.chats.create(
            model="gemini-2.5-flash", 
            config=types.GenerateContentConfig(
                tools=tools,
                system_instruction=instr,
                temperature=0.1 # Daha kararlı cevaplar için
            )
        )
        
        # Mesajı gönder (Senkron çağrı yapıyoruz çünkü SDK bazen await'te None dönebiliyor)
        response = chat.send_message(user_message)
        
        # Response kontrolü
        if response and response.text:
            return response.text
        elif response.candidates:
            # Eğer text doğrudan gelmediyse ilk candidate'i dene
            return response.candidates[0].content.parts[0].text
        else:
            return "Anladım ama şu an cevap üretemedim, tekrar sorar mısın?"

    except Exception as e:
        print(f"HATA DETAYI (ai_service): {e}")
        return f"Üzgünüm, bir hata oluştu: {str(e)}"