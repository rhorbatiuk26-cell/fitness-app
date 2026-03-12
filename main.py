import os
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

GEMINI_KEY = os.environ.get("GEMINI_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
else:
    print("GEMINI_KEY is missing")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v24.0 Auto-Select Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # АВТОПІДБІР МОДЕЛІ: беремо першу доступну, що підтримує генерацію
        available_models = [m.name for m in genai.list_models() 
                           if 'generateContent' in m.supported_generation_methods]
        
        if not available_models:
            return {"result": "Помилка: Ваш ключ не бачить жодної доступної моделі ШІ."}
        
        # Вибираємо модель (пріоритет на flash, якщо ні - перша зі списку)
        selected_model = next((m for m in available_models if 'flash' in m), available_models[0])
        
        model = genai.GenerativeModel(selected_model)
        
        response = model.generate_content([
            "Опиши цю їжу українською: назва, вага, калорії.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": f"[{selected_model}]: {response.text}"}
            
    except Exception as e:
        return {"result": f"Детальна помилка: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
