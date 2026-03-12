import os
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Забираємо ключ із Variables Railway
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Використовуємо СТАНДАРТНУ модель
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("CRITICAL ERROR: GEMINI_KEY is missing!")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v20.0 PRO STABLE"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Запит до ШІ
        response = model.generate_content([
            "Ти дієтолог. Опиши страву на фото українською: назва, приблизна вага, калорії. Будь коротким.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        if response.text:
            return {"result": response.text}
        else:
            return {"result": "ШІ не зміг розпізнати фото. Спробуйте інший ракурс."}
            
    except Exception as e:
        # Це допоможе нам зрозуміти, якщо ключ все ще не "підхопився"
        return {"result": f"Помилка конфігурації: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
