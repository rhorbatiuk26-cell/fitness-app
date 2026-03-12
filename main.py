import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Отримуємо ключ із налаштувань Railway
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Використовуємо -latest версію, вона найстабільніша для Paid Tier
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
else:
    print("Error: GEMINI_KEY not found in environment variables")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v19.0 Pro Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Запит до ШІ
        response = model.generate_content([
            "Опиши страву українською: назва, приблизна вага та калорії. Будь дуже коротким.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": response.text}
    
    except Exception as e:
        # Якщо знову 404, спробуємо дати підказку, що саме не так
        return {"result": f"Помилка доступу до Google AI: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
