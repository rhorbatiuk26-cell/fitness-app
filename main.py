import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# База даних у Volume для збереження даних
DB_DIR = "/app/data"
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_DIR}/fitlio_ultimate.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "profiles"
    user_id = Column(String, primary_key=True)
    c_kcal = Column(Integer); c_p = Column(Integer); c_f = Column(Integer)
    c_c = Column(Integer); c_sugar = Column(Integer); c_salt = Column(Integer)

class FoodLog(Base):
    __tablename__ = "food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float); fat = Column(Float)
    carbs = Column(Float); sugar = Column(Float); salt = Column(Float)
    created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); amount = Column(Float); created_at = Column(DateTime)

Base.metadata.create_all(bind=engine)
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    meals = {}
    for mt in ["Breakfast", "Snack1", "Lunch", "Snack2", "Dinner"]:
        items = [i for i in food if i.meal_type == mt]
        meals[mt] = {"kcal": sum(i.calories for i in items), "list": items}
    
    return {
        "totals": {
            "kcal": sum(f.calories for f in food), "p": round(sum(f.protein for f in food), 1), 
            "f": round(sum(f.fat for f in food), 1), "c": round(sum(f.carbs for f in food), 1),
            "sugar": round(sum(f.sugar for f in food), 1), "salt": round(sum(f.salt for f in food), 1)
        },
        "norms": {"kcal": p.c_kcal, "p": p.c_p, "f": p.c_f, "c": p.c_c, "sugar": p.c_sugar, "salt": p.c_salt} if p else None,
        "water": round(sum(w.amount for w in water), 2),
        "meals": meals
    }

@app.post("/calculate_norms")
async def calc_norms(data: dict):
    prompt = f"Розрахуй КБЖВ, цукор (до 50г) та сіль (до 5г) для: {data}. JSON: {{'kcal':0,'p':0,'f':0,'c':0,'sugar':50,'salt':5}}"
    res = model.generate_content(prompt)
    return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=data['user_id'], c_kcal=data['kcal'], c_p=data['p'], c_f=data['f'], c_c=data['c'], c_sugar=data['sugar'], c_salt=data['salt']))
    db.commit(); return {"ok": True}

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = "Поверни JSON: {'name': '...', 'kcal': 0, 'p': 0, 'f': 0, 'c': 0, 'sugar': 0, 'salt': 0}"
    if file: res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
    else: res = model.generate_content(prompt + (text_input or ""))
    return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])

@app.post("/confirm_save")
async def confirm_save(data: dict, db: Session = Depends(get_db)):
    db.add(FoodLog(user_id=data['user_id'], meal_type=data['meal_type'], food_name=data['name'], 
                   calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'], 
                   sugar=data['sugar'], salt=data['salt'], created_at=datetime.strptime(data['date'], '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/chat")
async def chat(msg: str = Form(...)):
    res = model.generate_content(f"Ти дієтолог FitLio. Дай пораду українською: {msg}")
    return {"reply": res.text}
