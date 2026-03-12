import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# ВСТАВ СВІЙ НОВИЙ API КЛЮЧ ТУТ
GEMINI_KEY = "AIzaSyAlhwZJJIdismq50Rcm9SewOLQE2N28OK4" # Переконайся, що ключ актуальний!
genai.configure(api_key=GEMINI_KEY)

# Використовуємо більш стабільну назву моделі
model = genai.GenerativeModel('gemini-1.5-flash-latest')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v10.0 Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        # Додаємо трохи магії для стабільності
        response = model.generate_content([
            "Опиши страву українською: назва, приблизна вага та калорії.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        return {"result": response.text}
    except Exception as e:
        # Тепер ми побачимо помилку в Mini App, якщо вона виникне
        return {"result": f"Помилка ШІ: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
