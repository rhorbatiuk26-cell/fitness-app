import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- DATABASE ---
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_logs_v36"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Integer)
    fat = Column(Integer)
    carbs = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_logs_v36"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- SMART AI SETUP ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))

def get_available_model():
    try:
        # Питаємо список доступних моделей для твого ключа
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"DEBUG: Доступні моделі: {models}")
        
        # Шукаємо Flash 1.5 або Pro, або беремо першу доступну
        for target in ['flash', 'pro', 'vision']:
            for m in models:
                if target in m.lower():
                    return genai.GenerativeModel(m)
        return genai.GenerativeModel(models[0]) if models else None
    except Exception as e:
        print(f"DEBUG Error listing models: {e}")
        return genai.GenerativeModel('gemini-1.5-flash') # fallback

active_model = get_available_model()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    m_name = active_model.model_name if active_model else "None"
    return {"status": "v36.0 Discovery Online", "active_model": m_name}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Аналіз їжі. Поверни JSON: {\"name\": \"назва\", \"kcal\": 200, \"p\": 10, \"f\": 5, \"c\": 20}"
        
        response = active_model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        txt = response.text
        start = txt.find('{')
        end = txt.rfind('}') + 1
        data = json.loads(txt[start:end])
        
        new_food = FoodLog(user_id=user_id, food_name=data['name'], calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'])
        db.add(new_food)
        db.commit()
        return data
    except Exception as e:
        return {"error": f"ШІ не зміг прочитати фото. Модель: {active_model.model_name if active_model else 'None'}. Помилка: {str(e)}"}

@app.post("/chat")
async def chat(user_id: str, message: str, db: Session = Depends(get_db)):
    try:
        today = datetime.utcnow().date()
        food = db.query(FoodLog).filter(FoodLog.user_id == user_id, FoodLog.created_at >= today).all()
        kcal_sum = sum(f.calories for f in food)
        
        prompt = f"Ти тренер. Сьогодні з'їдено {kcal_sum} ккал. Питання: {message}. Відповідай коротко українською."
        response = active_model.generate_content(prompt)
        return {"reply": response.text}
    except Exception as e:
        return {"reply": f"Помилка чату. Модель: {active_model.model_name if active_model else 'None'}. Текст: {str(e)}"}

# ... (інші методи stats та add_water залишаються такими ж)
