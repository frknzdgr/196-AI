======================================================================
           🌿 HATAY KOBI ASISTANI - FULL ENTEGRASYON REHBERI 🌿
======================================================================

Bu dosya, projenin yerel ortamda calistirilmasi, Ngrok tunelleme ve 
Twilio WhatsApp entegrasyonu icin gereken TUM adimlari icerir.

----------------------------------------------------------------------
1. ADIM: TEMEL KURULUMLAR (Python & Kutuphaneler)
----------------------------------------------------------------------
1. Bilgisayarinizda Python yuklu oldugundan emin olun.
2. Terminali acin ve proje klasorune girip su komutu calistirin:
   > pip install -r requirements.txt

----------------------------------------------------------------------
2. ADIM: NGROK KURULUMU (Yerel Sunucuyu Disa Acma)
----------------------------------------------------------------------
Ngrok, bilgisayarinizdaki 'localhost:8000' portunu internete acar.

1. https://ngrok.com/ adresine gidin ve ucretsiz hesap acin.
2. Ngrok dosyasini indirin ve ZIP'ten cikarin.
3. Ngrok panelindeki 'Your Authtoken' kismina gidin ve tokeni kopyalayin.
4. Terminalde su komutla tokeni kaydedin:
   > ngrok config add-authtoken <KOPYALADIGINIZ_TOKEN>
5. Sunucuyu disa acmak icin su komutu calistirin:
   > ngrok http 8000
6. Ekranda 'Forwarding' yazan yerdeki 'https://...' URL'sini kopyalayin.
   (NOT: Bu terminal penceresini sakin kapatmayin!)

----------------------------------------------------------------------
3. ADIM: TWILIO SANDBOX AYARLARI (WhatsApp Entegrasyonu)
----------------------------------------------------------------------
1. https://www.twilio.com/ adresinden ucretsiz bir hesap acin.
2. Console panelinde 'Messaging' -> 'Try it Out' -> 'Send a WhatsApp Message'a gidin.
3. Telefondan ekrandaki numaraya 'join <kelime>' mesajini atin (Baglanti icin sart).
4. 'Sandbox Settings' sekmesine tiklayin.
5. 'WHEN A MESSAGE COMES IN' kutusuna NGROK'tan kopyaladiginiz linki yapistirin.
6. !!! KRITIK NOKTA !!! Linkin sonuna mutlaka '/webhook' ekleyin.
   Ornek: https://abcd-1234.ngrok-free.app/webhook
7. Sayfanin en altindan 'SAVE' butonuna basin.

----------------------------------------------------------------------
4. ADIM: GEMINI API KEY VE .env DOSYASI
----------------------------------------------------------------------
1. https://aistudio.google.com/ adresinden 'Get API Key' diyerek anahtarinizi alin.
2. Proje icindeki .env dosyasini su bilgilerle doldurun:

   GEMINI_API_KEY=Sizin_API_Keyiniz
   ADMIN_PHONE=+905XXXXXXXXX (Admin olarak taninacak numaraniz)

----------------------------------------------------------------------
5. ADIM: SISTEMI CALISTIRMA
----------------------------------------------------------------------
1. Ana terminalde sunucuyu baslatin:
   > uvicorn main:app --reload

2. Artik WhatsApp uzerinden mesaj atabilirsiniz!

----------------------------------------------------------------------
ROLLER VE YETKILER:
----------------------------------------------------------------------
👑 ADMIN (Siz): "Fiyat guncelle", "Stok duzelt", "Kritik rapor ver" 
   diyerek dukkani yonetebilirsiniz.
👤 MUSTERI (Digerleri): Sadece urun sorabilir ve isim/adres vererek 
   siparis olusturabilir. Pazarlik yapamazlar, yetkileri kisitlidir.

HATA ALIRSANIZ: Ngrok'u kapatip acarsaniz URL degisir. Twilio'daki 
linki de guncellemeyi unutmayin!
----------------------------------------------------------------------
Hazirlayan: Furkan Ozudogru
======================================================================