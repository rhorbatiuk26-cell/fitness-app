import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Тепер ключ береться з налаштувань Railway автоматично
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    print("ПОМИЛКА: Ключ GEMINI_KEY не знайдено в налаштуваннях Railway!")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v16.0 Protected Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    if not GEMINI_KEY:
        return {"result": "Помилка: Ключ ШІ не налаштовано на сервері."}
    try:
        img_data = await file.read()
        response = model.generate_content([
            "Опиши страву українською: назва, приблизна вага, калорії, БЖВ.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        return {"result": response.text}
    except Exception as e:
        return {"result": f"Помилка: {str(e)}"}
