import os, json, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Використовуємо стабільні назви таблиць, щоб дані не зникали при оновленнях
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "fitlio_profiles"
    user_id = Column(String, primary_key=True)
    gender = Column(String)
    weight = Column(Float)
    height = Column(Float)
    age = Column(Integer)
    goal = Column(String)

class FoodLog(Base):
    __tablename__ = "fitlio_food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    meal_type = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Float, default=0)
    fat = Column(Float, default=0)
    carbs = Column(Float, default=0)
    sugar = Column(Float, default=0)
    salt = Column(Float, default=0)
    created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "fitlio_water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime)

Base.metadata.create_all(bind=engine)

genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def get_user_norms(p):
    val = (10 * p.weight) + (6.25 * p.height) - (5 * p.age)
    bmr = val + 5 if p.gender == 'male' else val - 161
    tdee = bmr * 1.3
    
    if p.goal == 'lose': kcal = int(tdee - 500)
    elif p.goal == 'gain': kcal = int(tdee + 300)
    elif p.goal == 'muscle': kcal = int(tdee + 600)
    else: kcal = int(tdee)
    
    if p.goal == 'muscle':
        p_n, f_n = p.weight * 2.2, p.weight * 1.0
    elif p.goal == 'lose':
        p_n, f_n = p.weight * 2.0, p.weight * 0.8
    else:
        p_n, f_n = p.weight * 1.6, p.weight * 0.9
        
    c_n = (kcal - (p_n * 4 + f_n * 9)) / 4
    return {"kcal": kcal, "p": int(p_n), "f": int(f_n), "c": int(c_n)}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    p = UserProfile(user_id=str(data['user_id']), gender=data['gender'], weight=float(data['weight']), height=float(data['height']), age=int(data['age']), goal=data['goal'])
    db.merge(p); db.commit()
    return {"status": "ok"}

@app.post("/analyze")
async def analyze(user_id: str = Form(...), meal_type: str = Form(...), date: str = Form(...), text_input: str = Form(None), file: UploadFile = File(None), db: Session = Depends(get_db)):
    prompt = "Return ONLY JSON: {\"name\": \"...\", \"kcal\": 0, \"p\": 0, \"f\": 0, \"c\": 0, \"sugar\": 0, \"salt\": 0}. Analyze: "
    if file:
        img_data = await file.read()
        res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
    else:
        res = model.generate_content(prompt + (text_input or ""))
    
    d = json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    dt = datetime.strptime(date, '%Y-%m-%d')
    db.add(FoodLog(user_id=str(user_id), meal_type=meal_type, food_name=d['name'], calories=d['kcal'], protein=d['p'], fat=d['f'], carbs=d['c'], sugar=d['sugar'], salt=d['salt'], created_at=dt))
    db.commit()
    return d

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    norms = get_user_norms(p) if p else {"kcal": 2000, "p": 120, "f": 70, "c": 220}
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    meals = {"Breakfast": 0, "Lunch": 0, "Dinner": 0, "Snack": 0}
    food_list = []
    for f in food:
        meals[f.meal_type] += f.calories
        food_list.append({"id": f.id, "name": f.food_name, "kcal": f.calories, "type": f.meal_type})
    return {
        "kcal": sum(f.calories for f in food), "norms": norms,
        "p": round(sum(f.protein for f in food), 1), "f": round(sum(f.fat for f in food), 1), "c": round(sum(f.carbs for f in food), 1),
        "sugar": round(sum(f.sugar for f in food), 1), "salt": round(sum(f.salt for f in food), 1),
        "water": round(sum(w.amount for w in water), 2), "meals": meals, "food_list": food_list, "has_profile": p is not None
    }

@app.delete("/delete_food/{food_id}")
async def delete_food(food_id: int, db: Session = Depends(get_db)):
    db.query(FoodLog).filter(FoodLog.id == food_id).delete(); db.commit()
    return {"status": "ok"}

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d')
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=dt)); db.commit()
    return {"status": "ok"}
