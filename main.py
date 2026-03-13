import os
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- БАЗА ДАНИХ (Railway PostgreSQL) ---
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_info = Column(Text)
    calories = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- ШТУЧНИЙ ІНТЕЛЕКТ (Gemini) ---
GEMINI_KEY = os.environ.get("GEMINI_KEY")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    return {"status": "v30.0 Pro System Online"}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        
        prompt = """
        Ти дієтолог. Проаналізуй фото страви українською мовою. 
        Дай відповідь ТІЛЬКИ у такому форматі:
        Назва: [назва]
        Вага: [вага]
        Калорії: [число]
        БЖВ: [білки/жири/вуглеводи]
        ---
        В кінці напиши тільки число калорій після знаку #. Наприклад: #250
        """
        
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        full_text = response.text
        
        # Витягуємо число калорій для бази
        kcal = 0
        if "#" in full_text:
            try: kcal = int(full_text.split("#")[-1].strip())
            except: kcal = 0

        # Зберігаємо в PostgreSQL
        new_log = FoodLog(user_id=user_id, food_info=full_text.split("#")[0], calories=kcal)
        db.add(new_log)
        db.commit()
        
        return {"result": full_text.split("#")[0], "kcal": kcal}
    except Exception as e:
        return {"result": f"Помилка: {str(e)}", "kcal": 0}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    logs = db.query(FoodLog).filter(FoodLog.user_id == user_id, FoodLog.created_at >= today_start).all()
    total = sum(log.calories for log in logs)
    history = [{"info": log.food_info, "kcal": log.calories} for log in logs]
    return {"total": total, "history": history}
