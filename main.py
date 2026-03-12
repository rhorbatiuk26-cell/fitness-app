import os
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Забираємо ключ
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    # Примусово налаштовуємо клієнт
    genai.configure(api_key=GEMINI_KEY)
    # Спробуємо створити модель БЕЗ вказання версії в об'єкті, 
    # бібліотека сама має обрати v1 для платних акаунтів
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("GEMINI_KEY is missing")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v21.0 Final Push"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Використовуємо метод generate_content
        response = model.generate_content([
            "Опиши цю їжу українською: назва, вага, калорії.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": response.text}
            
    except Exception as e:
        # Якщо знову помилка, виведемо ТИП помилки для діагностики
        return {"result": f"Помилка {type(e).__name__}: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
