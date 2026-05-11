import os
from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse
from ai_service import get_ai_response
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
ADMIN_PHONE = os.getenv("ADMIN_PHONE")


@app.get("/")

async def root():

    """Sunucunun çalışıp çalışmadığını kontrol etmek için."""

    return {

        "durum": "Aktif",

        "mesaj": "KOBİ Asistan Sunucusu başarıyla çalışıyor!",

        "versiyon": "1.0.0"

    }

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    sender_phone = From.replace("whatsapp:", "")
    is_admin = (sender_phone == ADMIN_PHONE)
    
    # Servise hem mesajı hem de numara bilgisini gönderiyoruz
    ai_answer = await get_ai_response(Body, sender_phone=sender_phone, is_admin=is_admin)
    print(f"🤖 Botun Yanıtı: {ai_answer}")
    response = MessagingResponse()
    response.message(ai_answer)
    return Response(content=str(response), media_type="application/xml")