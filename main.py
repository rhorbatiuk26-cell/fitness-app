import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# ВСТАВ СВІЙ НОВИЙ API КЛЮЧ
GEMINI_KEY = "AIzaSyAlhwZJJIdismq50Rcm9SewOLQE2N28OK4" 
genai.configure(api_key=GEMINI_KEY)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v12.0 Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Спробуємо використати модель gemini-1.5-flash
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        response = model.generate_content([
            "Опиши страву українською: назва, приблизна вага та калорії.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        return {"result": response.text}
    
    except Exception as e:
        # Якщо помилка, спробуємо знайти назви доступних моделей
        available_models = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)
        except:
            pass
            
        return {
            "result": f"Помилка: {str(e)}\n\nДоступні моделі у вашому ключі: {', '.join(available_models) if available_models else 'не знайдено'}"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
