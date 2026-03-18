import os, json, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# БД Налаштування
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "fitlio_profiles"
    user_id = Column(String, primary_key=True)
    gender = Column(String); weight = Column(Float); height = Column(Float); age = Column(Integer); goal = Column(String)

class FoodLog(Base):
    __tablename__ = "fitlio_food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float); fat = Column(Float); carbs = Column(Float)
    sugar = Column(Float, default=0); salt = Column(Float, default=0); created_at = Column(DateTime)

class WorkoutLog(Base):
    __tablename__ = "fitlio_workouts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); activity = Column(String); burned = Column(Integer); created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "fitlio_water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); amount = Column(Float); created_at = Column(DateTime)

Base.metadata.create_all(bind=engine)

# AI Налаштування
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash') # Стабільна версія

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def calc_norms(p):
    val = (10 * p.weight) + (6.25 * p.height) - (5 * p.age)
    bmr = val + 5 if p.gender == 'male' else val - 161
    tdee = bmr * 1.3
    kcal = int(tdee - 500) if p.goal == 'lose' else int(tdee + 300) if p.goal == 'gain' else int(tdee)
    return {"kcal": kcal, "p": int(p.weight*1.8), "f": int(p.weight*0.9), "c": int((kcal-(p.weight*1.8*4+p.weight*0.9*9))/4), "sugar": 50, "salt": 5}

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = """Return ONLY JSON: {"name": "...", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}. Analyze: """
    if file:
        res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
    else:
        res = model.generate_content(prompt + (text_input or ""))
    return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])

@app.post("/save_food")
async def save_food(data: dict, db: Session = Depends(get_db)):
    dt = datetime.strptime(data['date'], '%Y-%m-%d')
    db.add(FoodLog(user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'], calories=int(data['kcal']), protein=float(data['p']), fat=float(data['f']), carbs=float(data['c']), sugar=float(data.get('sugar',0)), salt=float(data.get('salt',0)), created_at=dt))
    db.commit(); return {"ok": True}

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    norms = calc_norms(p) if p else {"kcal":2000, "p":120, "f":70, "c":250, "sugar":50, "salt":5}
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    workouts = db.query(WorkoutLog).filter(WorkoutLog.user_id == str(user_id), func.date(WorkoutLog.created_at) == dt).all()

    meals_data = {}
    for mt in ["Breakfast", "Lunch", "Dinner", "Snack"]:
        m_items = [f for f in food if f.meal_type == mt]
        meals_data[mt] = {"kcal": sum(i.calories for i in m_items), "items": [{"id": i.id, "name": i.food_name, "kcal": i.calories} for i in m_items]}

    return {
        "kcal": sum(f.calories for f in food), "burned": sum(w.burned for w in workouts),
        "p": sum(f.protein for f in food), "f": sum(f.fat for f in food), "c": sum(f.carbs for f in food),
        "sugar": sum(f.sugar for f in food), "salt": sum(f.salt for f in food),
        "water": sum(w.amount for w in water), "norms": norms, "meals": meals_data, "has_profile": p is not None, "weight": p.weight if p else 0
    }

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=str(data['user_id']), gender=data['gender'], weight=float(data['weight']), height=float(data['height']), age=int(data['age']), goal=data['goal']))
    db.commit(); return {"ok": True}

@app.delete("/delete/food/{id}")
async def delete_food(id: int, db: Session = Depends(get_db)):
    db.query(FoodLog).filter(FoodLog.id == id).delete(); db.commit(); return {"ok": True}
