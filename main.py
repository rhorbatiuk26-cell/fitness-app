import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Налаштування Gemini
GEMINI_KEY = "AIzaSyD7hZP32yHw6hqSiO-LxOoWbO2YsyzYYYA"
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()

# Дозволяємо Mini App підключатися до сервера
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def health():
    return {"status": "v9.0 Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    img_data = await file.read()
    response = model.generate_content([
        "Опиши страву українською: назва, приблизна вага та калорії. Будь дуже коротким.",
        {"mime_type": "image/jpeg", "data": img_data}
    ])
    return {"result": response.text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
