import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

DB_DIR = "/app/data"
if not os.path.exists(DB_DIR): os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_DIR}/database.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "profiles"
    user_id = Column(String, primary_key=True)
    goal = Column(String); target_weight = Column(Float)
    c_kcal = Column(Integer); c_p = Column(Integer); c_f = Column(Integer); c_c = Column(Integer)
    c_sugar = Column(Integer); c_salt = Column(Integer)

class FoodLog(Base):
    __tablename__ = "food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float); fat = Column(Float); carbs = Column(Float)
    sugar = Column(Float); salt = Column(Float); created_at = Column(DateTime)

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
    meals = {mt: {"kcal": sum(i.calories for i in food if i.meal_type == mt), "list": [i for i in food if i.meal_type == mt]} 
             for mt in ["Breakfast", "Snack1", "Lunch", "Snack2", "Dinner"]}
    return {
        "totals": {"kcal": sum(f.calories for f in food), "p": round(sum(f.protein for f in food),1), "f": round(sum(f.fat for f in food),1), "c": round(sum(f.carbs for f in food),1), "sugar": round(sum(f.sugar for f in food),1), "salt": round(sum(f.salt for f in food),1)},
        "norms": {"kcal": p.c_kcal, "p": p.c_p, "f": p.c_f, "c": p.c_c, "sugar": p.c_sugar, "salt": p.c_salt, "goal": p.goal, "tw": p.target_weight} if p else None,
        "water": round(sum(w.amount for w in water), 2), "meals": meals
    }

@app.post("/setup")
async def setup(data: dict, db: Session = Depends(get_db)):
    prompt = f"Розрахуй КБЖВ для цілі {data['goal']}, бажана вага {data['tw']}кг. Поточна: {data['w']}кг, {data['h']}см, {data['a']} років. JSON: {{'kcal':0,'p':0,'f':0,'c':0,'sugar':50,'salt':5}}"
    res = model.generate_content(prompt)
    n = json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    db.merge(UserProfile(user_id=data['user_id'], goal=data['goal'], target_weight=data['tw'], **n))
    db.commit(); return {"ok": True}

@app.post("/add_food")
async def add_food(data: dict, db: Session = Depends(get_db)):
    db.add(FoodLog(user_id=data['user_id'], meal_type=data['meal_type'], food_name=data['name'], calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'], sugar=data['sugar'], salt=data['salt'], created_at=datetime.strptime(data['date'], '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/water")
async def water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/chat")
async def chat(msg: str = Form(...)):
    res = model.generate_content(f"Ти дієтолог. Відповідай дуже коротко: {msg}")
    return {"reply": res.text}
