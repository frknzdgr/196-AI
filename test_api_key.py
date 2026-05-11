import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Mevcut modelleri listele - attribute ismini güncelledik
for m in client.models.list():
    print(f"Model Adı: {m.name}, Desteklenen İşlemler: {m.supported_actions}")