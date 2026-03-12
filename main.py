import os, google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# ВСТАВ СВІЙ API КЛЮЧ
GEMINI_KEY = "AIzaSyAlhwZJJIdismq50Rcm9SewOLQE2N28OK4" 
genai.configure(api_key=GEMINI_KEY)

# Використовуємо модель, яка ТОЧНО є у твоєму списку:
model = genai.GenerativeModel('gemini-2.0-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def health():
    return {"status": "v13.0 Online"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # Аналіз страви
        response = model.generate_content([
            "Опиши страву українською: назва, приблизна вага та калорійність. Будь лаконічним.",
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        return {"result": response.text}
    
    except Exception as e:
        return {"result": f"Помилка: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
