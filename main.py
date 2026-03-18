import os, json, time, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Налаштування логів (щоб бачити помилки в Railway)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "prod_v44_food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Integer)
    fat = Column(Integer)
    carbs = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# AI SETUP
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Ти дієтолог. Проаналізуй фото. Поверни ТІЛЬКИ JSON: {\"name\": \"...\", \"kcal\": 0, \"p\": 0, \"f\": 0, \"c\": 0}"
        
        # Використовуємо надійний формат передачі
        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        txt = response.text
        data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        
        new_food = FoodLog(user_id=str(user_id), food_name=data['name'], calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'])
        db.add(new_food)
        db.commit()
        return data
    except Exception as e:
        logger.error(f"AI Error Analyze: {str(e)}")
        return {"error": "AI Error"}

@app.post("/chat")
async def chat(user_id: str, message: str):
    try:
        # Прямий запит без зайвих обгорток для швидкості
        response = model.generate_content(f"Ти фітнес-тренер FitLio. Коротко відповів на питання українською: {message}")
        return {"reply": response.text}
    except Exception as e:
        logger.error(f"AI Error Chat: {str(e)}")
        # Виводимо частину помилки в чат для діагностики (потім приберемо)
        return {"reply": f"Помилка Google API: {str(e)[:50]}..."}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
    return {"kcal": sum(f.calories for f in food) or 0, "p": sum(f.protein for f in food) or 0, "f": sum(f.fat for f in food) or 0, "c": sum(f.carbs for f in food) or 0, "water": 0}
