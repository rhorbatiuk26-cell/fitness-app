import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# Зчитуємо ключ із Variables в Railway
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Змінюємо на максимально стабільну назву
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    print("Error: GEMINI_KEY missing")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v17.0 Stable Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        # Вказуємо ШІ бути максимально точним
        response = model.generate_content([
            "Проаналізуй фото страви. Назви її, вкажи вагу та калорії українською мовою.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        return {"result": response.text}
    except Exception as e:
        # Якщо знову буде 404, спробуємо автоматично підібрати іншу модель
        return {"result": f"Помилка: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
