import os, json, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Логи
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB SETUP
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_v48"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_v48"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- НОВА КОНФІГУРАЦІЯ AI (GEMINI 2.5) ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
# Використовуємо саме ту модель, яку підтвердив твій акаунт
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    return {"status": "v48.0 Ultra Stable Online"}

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount))
    db.commit()
    return {"status": "ok"}

@app.post("/chat")
async def chat(user_id: str, message: str):
    try:
        response = model.generate_content(f"Ти фітнес-тренер FitLio. Дай дуже коротку пораду: {message}")
        return {"reply": response.text}
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        return {"reply": f"ШІ: Помилка конфігурації. Спробуйте ще раз."}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Проаналізуй їжу на фото. Поверни ТІЛЬКИ JSON: {\"name\": \"назва\", \"kcal\": 200}"
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        
        # Чистий парсинг JSON
        txt = response.text
        data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        
        db.add(FoodLog(user_id=str(user_id), food_name=data['name'], calories=data['kcal']))
        db.commit()
        return data
    except Exception as e:
        logger.error(f"Analyze Error: {e}")
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
