import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- DATABASE SETUP ---
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_logs_v5"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Integer)
    fat = Column(Integer)
    carbs = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_logs_v5"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- AI SETUP (STABLE VERSION) ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
# ВАЖЛИВО: Використовуємо повну назву 'models/gemini-1.5-flash'
model = genai.GenerativeModel('models/gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/")
async def health():
    return {"status": "v34.2 Stable Chat Online"}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Проаналізуй фото. Поверни ТІЛЬКИ JSON: {\"name\": \"назва\", \"kcal\": 200, \"p\": 10, \"f\": 5, \"c\": 20}"
        # Використовуємо стабільну модель
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw_text)
        new_food = FoodLog(user_id=user_id, food_name=data['name'], calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'])
        db.add(new_food)
        db.commit()
        return data
    except Exception as e:
        return {"error": str(e)}

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=user_id, amount=amount))
    db.commit()
    return {"status": "ok"}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == user_id, FoodLog.created_at >= today).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == user_id, WaterLog.created_at >= today).all()
    return {
        "kcal": sum(f.calories for f in food), 
        "p": sum(f.protein for f in food),
        "f": sum(f.fat for f in food), 
        "c": sum(f.carbs for f in food),
        "water": round(sum(w.amount for w in water), 2)
    }

@app.post("/chat")
async def chat(user_id: str, message: str, db: Session = Depends(get_db)):
    try:
        today = datetime.utcnow().date()
        food = db.query(FoodLog).filter(FoodLog.user_id == user_id, FoodLog.created_at >= today).all()
        kcal_sum = sum(f.calories for f in food)
        
        # Використовуємо стабільний метод
        prompt = f"Ти фітнес-тренер. Користувач з'їв {kcal_sum} ккал сьогодні. Питання: {message}. Дай коротку пораду українською."
        response = model.generate_content(prompt)
        return {"reply": response.text}
    except Exception as e:
        return {"reply": f"Вибачте, технічна заминка: {str(e)}"}
