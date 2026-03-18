import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Шлях до бази у Volume
DB_DIR = "/app/data"
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'fitlio.db')}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "fitlio_profiles"
    user_id = Column(String, primary_key=True)
    weight = Column(Float); height = Column(Float); goal = Column(String)
    c_kcal = Column(Integer, default=2000); c_p = Column(Integer, default=120)
    c_f = Column(Integer, default=70); c_c = Column(Integer, default=250)

class FoodLog(Base):
    __tablename__ = "fitlio_food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float, default=0.0)
    fat = Column(Float, default=0.0); carbs = Column(Float, default=0.0)
    sugar = Column(Float, default=0.0); salt = Column(Float, default=0.0)
    created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "fitlio_water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); amount = Column(Float); created_at = Column(DateTime)

Base.metadata.create_all(bind=engine)

genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal(); 
    try: yield db
    finally: db.close()

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = """Return ONLY JSON: {"name": "...", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}. Analyze food:"""
    try:
        if file: res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
        else: res = model.generate_content(prompt + (text_input or ""))
        return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    except: return {"name": "Помилка", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    n = {"kcal": p.c_kcal if p else 2000, "p": p.c_p if p else 120, "f": p.c_f if p else 70, "c": p.c_c if p else 250, "sugar": 50, "salt": 5}
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    meals = {}
    for mt in ["Breakfast", "Lunch", "Dinner", "Snack"]:
        items = [i for i in food if i.meal_type == mt]
        meals[mt] = {
            "kcal": sum(i.calories for i in items),
            "p": sum(i.protein for i in items), "f": sum(i.fat for i in items), "c": sum(i.carbs for i in items),
            "sugar": sum(i.sugar for i in items), "salt": sum(i.salt for i in items),
            "list": [{"id": i.id, "name": i.food_name, "kcal": i.calories, "p": i.protein, "f": i.fat, "c": i.carbs, "sugar": i.sugar, "salt": i.salt} for i in items]
        }
    return {"kcal": sum(f.calories for f in food), "p": sum(f.protein for f in food), "f": sum(f.fat for f in food), "c": sum(f.carbs for f in food), "sugar": sum(f.sugar for f in food), "salt": sum(f.salt for f in food), "water": sum(w.amount for w in water), "norms": n, "meals": meals, "profile": p}

@app.post("/confirm_save")
async def confirm_save(data: dict, db: Session = Depends(get_db)):
    db.add(FoodLog(user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'], calories=int(data['kcal']), protein=float(data.get('p',0)), fat=float(data.get('f',0)), carbs=float(data.get('c',0)), sugar=float(data.get('sugar',0)), salt=float(data.get('salt',0)), created_at=datetime.strptime(data['date'], '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.delete("/delete_food/{food_id}")
async def delete_food(food_id: int, db: Session = Depends(get_db)):
    db.query(FoodLog).filter(FoodLog.id == food_id).delete()
    db.commit(); return {"ok": True}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=str(data['user_id']), weight=float(data['weight']), height=float(data['height']), goal=data['goal'], c_kcal=int(data['c_kcal']), c_p=int(data['c_p']), c_f=int(data['c_f']), c_c=int(data['c_c'])))
    db.commit(); return {"ok": True}

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d'))); db.commit(); return {"ok": True}

@app.post("/coach_chat")
async def coach_chat(data: dict):
    prompt = f"Ти фітнес-тренер. Поточні КБЖВ користувача: {data['stats']}. Користувач каже: {data['msg']}. Дай коротку пораду укр мовою."
    res = model.generate_content(prompt)
    return {"reply": res.text}
