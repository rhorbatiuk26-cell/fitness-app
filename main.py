import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# База даних
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./fitlio.db").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "fitlio_profiles"
    user_id = Column(String, primary_key=True)
    gender = Column(String); weight = Column(Float); height = Column(Float); age = Column(Integer); goal = Column(String)
    c_kcal = Column(Integer, nullable=True); c_p = Column(Integer, nullable=True)
    c_f = Column(Integer, nullable=True); c_c = Column(Integer, nullable=True)

class FoodLog(Base):
    __tablename__ = "fitlio_food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float); fat = Column(Float); carbs = Column(Float)
    sugar = Column(Float, default=0.0); salt = Column(Float, default=0.0)
    created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "fitlio_water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); amount = Column(Float); created_at = Column(DateTime)

Base.metadata.create_all(bind=engine)

# Налаштування Gemini 2.5 Flash
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = """Return ONLY JSON: {"name": "...", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}. Use grams. Analyze: """
    if file:
        res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
    else:
        res = model.generate_content(prompt + (text_input or ""))
    return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    
    # Визначаємо норми
    norms = {
        "kcal": p.c_kcal if p and p.c_kcal else 2000,
        "p": p.c_p if p and p.c_p else 120,
        "f": p.c_f if p and p.c_f else 70,
        "c": p.c_c if p and p.c_c else 250,
        "sugar": 50, "salt": 5
    }

    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    meals = {}
    for mt in ["Breakfast", "Lunch", "Dinner", "Snack"]:
        items = [f for f in food if f.meal_type == mt]
        meals[mt] = {
            "kcal": sum(i.calories or 0 for i in items),
            "p": round(sum(i.protein or 0 for i in items), 1),
            "f": round(sum(i.fat or 0 for i in items), 1),
            "c": round(sum(i.carbs or 0 for i in items), 1),
            "sugar": round(sum(i.sugar or 0 for i in items), 1),
            "salt": round(sum(i.salt or 0 for i in items), 1),
            "list": [{"id": i.id, "name": i.food_name, "kcal": i.calories} for i in items]
        }

    return {
        "kcal": sum(f.calories or 0 for f in food),
        "p": sum(f.protein or 0 for f in food), "f": sum(f.fat or 0 for f in food), "c": sum(f.carbs or 0 for f in food),
        "sugar": sum(f.sugar or 0 for f in food), "salt": sum(f.salt or 0 for f in food),
        "water": round(sum(w.amount or 0 for w in water), 2),
        "norms": norms, "meals": meals, "has_profile": p is not None
    }

@app.post("/confirm_save")
async def confirm_save(data: dict, db: Session = Depends(get_db)):
    dt = datetime.strptime(data['date'], '%Y-%m-%d')
    db.add(FoodLog(user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'], 
                   calories=int(data['kcal']), protein=float(data['p']), fat=float(data['f']), 
                   carbs=float(data['c']), sugar=float(data.get('sugar',0)), salt=float(data.get('salt',0)), created_at=dt))
    db.commit(); return {"ok": True}

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d'))); db.commit()
    return {"ok": True}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=str(data['user_id']), gender='male', weight=float(data['weight']), 
                         height=float(data['height']), age=25, goal=data['goal'],
                         c_kcal=int(data['c_kcal']) if data.get('c_kcal') else None,
                         c_p=int(data['c_p']) if data.get('c_p') else None,
                         c_f=int(data['c_f']) if data.get('c_f') else None,
                         c_c=int(data['c_c']) if data.get('c_c') else None))
    db.commit(); return {"ok": True}
