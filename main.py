import os
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Отримуємо ключ із налаштувань Railway
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Пряме звернення до стабільної моделі
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("CRITICAL: GEMINI_KEY is missing!")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v23.0 API_ENABLED_STABLE"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Виклик моделі з чітким інструктажем
        response = model.generate_content([
            "Ти дієтолог. Проаналізуй фото страви українською мовою. Дай відповідь у форматі: Назва, Вага, Калорії, БЖВ.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": response.text}
            
    except Exception as e:
        # Тепер ми точно побачимо, якщо API все ще видає 404 або іншу помилку
        return {"result": f"Статус: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
