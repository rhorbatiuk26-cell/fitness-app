import os, json, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB SETUP
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_v47"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_v47"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- ПРИМУСОВА КОНФІГУРАЦІЯ AI ---
API_KEY = os.environ.get("GEMINI_KEY")
genai.configure(api_key=API_KEY)

# Створюємо модель без додаткових префіксів
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    return {"status": "v47.0 Stable Mode"}

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount))
    db.commit()
    return {"status": "ok"}

@app.post("/chat")
async def chat(user_id: str, message: str):
    try:
        # Пряма генерація контенту
        response = model.generate_content(f"Ти тренер. Дай коротку пораду: {message}")
        return {"reply": response.text}
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        # Якщо знову 404, спробуємо отримати список моделей для діагностики
        try:
            available_models = [m.name for m in genai.list_models()]
            return {"reply": f"Доступні моделі: {available_models[0:2]}. Помилка: {str(e)[:50]}"}
        except:
            return {"reply": "ШІ ще прокидається. Спробуйте через 10 секунд."}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        contents = [
            "Проаналізуй фото. Поверни ТІЛЬКИ JSON: {\"name\": \"...\", \"kcal\": 0}",
            {"mime_type": "image/jpeg", "data": img_data}
        ]
        response = model.generate_content(contents)
        data = json.loads(response.text[response.text.find("{"):response.text.rfind("}")+1])
        db.add(FoodLog(user_id=str(user_id), food_name=data['name'], calories=data['kcal']))
        db.commit()
        return data
    except Exception as e:
        return {"error": str(e)}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), WaterLog.created_at >= today).all()
    return {
        "kcal": sum(f.calories for f in food) or 0,
        "water": round(sum(w.amount for w in water), 2) or 0
    }
