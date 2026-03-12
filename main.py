import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Ключ із Variables в Railway
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
else:
    print("Error: GEMINI_KEY is missing!")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v18.0 Smart-Model Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Спроба 1: Найновіша стабільна модель
        model_name = 'gemini-1.5-flash' 
        # (Ми використовуємо 1.5-flash, бо для платних акаунтів вона 
        # зараз є стандартом, поки 2.0 не вийде з бети повністю)
        
        model = genai.GenerativeModel(model_name)
        
        response = model.generate_content([
            "Проаналізуй фото їжі українською: назва, вага, калорії, БЖВ.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": response.text}
        
    except Exception as e:
        # Якщо 1.5 не спрацювала, спробуємо знайти будь-яку іншу
        return {"result": f"Помилка: {str(e)}. Спробуйте оновити сторінку."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
