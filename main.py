import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- DATABASE SETUP ---
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "final_food_logs_v1"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer, default=0)
    protein = Column(Integer, default=0)
    fat = Column(Integer, default=0)
    carbs = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "final_water_logs_v1"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- AI CONFIG ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    return {"status": "v37.0 Stable"}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Проаналізуй фото страви. Поверни ТІЛЬКИ чистий JSON без тексту навколо: {\"name\": \"...\", \"kcal\": 200, \"p\": 10, \"f\": 5, \"c\": 20}"
        
        response = model.generate_content([
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_data}}
        ])
        
        # Очищення JSON від можливих маркерів ```json
        txt = response.text.strip()
        if "{" in txt:
            txt = txt[txt.find("{"):txt.rfind("}")+1]
        
        data = json.loads(txt)
        new_food = FoodLog(
            user_id=str(user_id), 
            food_name=data.get('name', 'Страва'),
            calories=int(data.get('kcal', 0)),
            protein=int(data.get('p', 0)),
            fat=int(data.get('f', 0)),
            carbs=int(data.get('c', 0))
        )
        db.add(new_food)
        db.commit()
        return data
    except Exception as e:
        print(f"Error: {e}")
        return {"error": "ШІ не зміг розпізнати фото", "kcal": 0, "p": 0, "f": 0, "c": 0}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), WaterLog.created_at >= today).all()
    
    return {
        "kcal": sum(f.calories for f in food) or 0,
        "p": sum(f.protein for f in food) or 0,
        "f": sum(f.fat for f in food) or 0,
        "c": sum(f.carbs for f in food) or 0,
        "water": round(sum(w.amount for w in water), 2) or 0.0
    }

@app.post("/chat")
async def chat(user_id: str, message: str, db: Session = Depends(get_db)):
    try:
        today = datetime.utcnow().date()
        food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
        kcal = sum(f.calories for f in food) or 0
        
        resp = model.generate_content(f"Ти тренер. Юзер з'їв {kcal} ккал сьогодні. Питання: {message}. Відповідай дуже коротко українською.")
        return {"reply": resp.text}
    except Exception:
        return {"reply": "Вибач, я трохи відволікся. Спробуй ще раз!"}

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=float(amount)))
    db.commit()
    return {"status": "ok"}
