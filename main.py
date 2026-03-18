import os, json, logging
from datetime import datetime, timedelta
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "profiles_v55"
    user_id = Column(String, primary_key=True)
    gender = Column(String)
    weight = Column(Float)
    height = Column(Float)
    age = Column(Integer)
    goal = Column(String) # lose / gain / maintain

class FoodLog(Base):
    __tablename__ = "food_v55"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    meal_type = Column(String) # Breakfast, Lunch, Dinner, Snack
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    sugar = Column(Float, default=0)
    salt = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_v55"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- AI CONFIG ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def calc_norm(p: UserProfile):
    val = (10 * p.weight) + (6.25 * p.height) - (5 * p.age)
    bmr = val + 5 if p.gender == 'male' else val - 161
    tdee = bmr * 1.2
    if p.goal == 'lose': return int(tdee - 400)
    if p.goal == 'gain': return int(tdee + 400)
    return int(tdee)

# --- ROUTES ---

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    p = UserProfile(
        user_id=str(data['user_id']), gender=data['gender'],
        weight=float(data['weight']), height=float(data['height']),
        age=int(data['age']), goal=data['goal']
    )
    db.merge(p)
    db.commit()
    return {"status": "ok"}

@app.post("/analyze")
async def analyze(user_id: str, meal_type: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Поверни ТІЛЬКИ чистий JSON: {\"name\": \"...\", \"kcal\": 0, \"p\": 0, \"f\": 0, \"c\": 0, \"sugar\": 0, \"salt\": 0}"
        res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        d = json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
        db.add(FoodLog(user_id=str(user_id), meal_type=meal_type, food_name=d['name'], 
                       calories=d['kcal'], protein=d['p'], fat=d['f'], carbs=d['c'], 
                       sugar=d['sugar'], salt=d['salt']))
        db.commit()
        return d
    except Exception as e:
        logger.error(f"Analyze error: {e}")
        return {"error": str(e)}

@app.get("/stats")
async def get_stats(user_id: str, days: int = 1, db: Session = Depends(get_db)):
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    daily_norm = calc_norm(p) if p else 2000
    
    start_date = datetime.utcnow() - timedelta(days=days)
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= start_date).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), WaterLog.created_at >= start_date).all()
    
    meals_summary = {"Breakfast": 0, "Lunch": 0, "Dinner": 0, "Snack": 0}
    for f in food:
        if f.meal_type in meals_summary:
            meals_summary[f.meal_type] += f.calories

    return {
        "kcal": sum(f.calories for f in food) or 0,
        "norm": daily_norm * days,
        "p": round(sum(f.protein for f in food), 1),
        "f": round(sum(f.fat for f in food), 1),
        "c": round(sum(f.carbs for f in food), 1),
        "sugar": round(sum(f.sugar for f in food), 1),
        "salt": round(sum(f.salt for f in food), 1),
        "water": round(sum(w.amount for w in water), 2) or 0,
        "meals": meals_summary,
        "has_profile": p is not None
    }

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount))
    db.commit()
    return {"status": "ok"}
