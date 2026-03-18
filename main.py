import os, json
from datetime import datetime, timedelta
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# ПОВЕРТАЄМО ШЛЯХ ЯК НА СКРИНШОТІ
DB_DIR = "/app/data"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_DIR}/fitlio_pro.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserProfile(Base):
    __tablename__ = "profiles"
    user_id = Column(String, primary_key=True)
    weight = Column(Float); height = Column(Float, default=0)
    c_kcal = Column(Integer, default=2000); c_p = Column(Integer, default=120)
    c_f = Column(Integer, default=70); c_c = Column(Integer, default=250)
    last_weight_date = Column(DateTime)

class FoodLog(Base):
    __tablename__ = "food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String); meal_type = Column(String); food_name = Column(String)
    calories = Column(Integer); protein = Column(Float, default=0.0)
    fat = Column(Float, default=0.0); carbs = Column(Float, default=0.0)
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
    # Перевірка на щотижневе зважування
    needs_w = True if not p or not p.last_weight_date or (datetime.now() - p.last_weight_date).days >= 7 else False
    
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    meals = {}
    for mt in ["Breakfast", "Snack1", "Lunch", "Snack2", "Dinner"]:
        items = [i for i in food if i.meal_type == mt]
        meals[mt] = {"kcal": sum(i.calories for i in items), "list": [{"id": i.id, "name": i.food_name, "kcal": i.calories} for i in items]}
    
    return {
        "kcal": sum(f.calories for f in food), "p": round(sum(f.protein for f in food), 1), 
        "f": round(sum(f.fat for f in food), 1), "c": round(sum(f.carbs for f in food), 1),
        "water": round(sum(w.amount for w in water), 2),
        "norms": {"kcal": p.c_kcal if p else 2000, "p": p.c_p if p else 120, "f": p.c_f if p else 70, "c": p.c_c if p else 250},
        "meals": meals, "profile": p, "needs_weight": needs_w
    }

@app.post("/copy_previous")
async def copy_prev(user_id: str, date: str, db: Session = Depends(get_db)):
    current_dt = datetime.strptime(date, '%Y-%m-%d').date()
    prev_dt = current_dt - timedelta(days=1)
    prev_items = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == prev_dt).all()
    for item in prev_items:
        db.add(FoodLog(user_id=item.user_id, meal_type=item.meal_type, food_name=item.food_name, 
                       calories=item.calories, protein=item.protein, fat=item.fat, carbs=item.carbs, 
                       created_at=datetime.combine(current_dt, datetime.min.time())))
    db.commit()
    return {"ok": True}

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = """Return ONLY JSON: {"name": "...", "kcal": 0, "p": 0, "f": 0, "c": 0}."""
    try:
        if file: res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
        else: res = model.generate_content(prompt + (text_input or ""))
        return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    except: return {"name": "Помилка", "kcal": 0, "p": 0, "f": 0, "c": 0}

@app.post("/confirm_save")
async def confirm_save(data: dict, db: Session = Depends(get_db)):
    db.add(FoodLog(user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'], 
                   calories=int(data['kcal']), created_at=datetime.strptime(data['date'], '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=str(data['user_id']), weight=float(data['weight']), 
                         c_kcal=int(data['c_kcal']), last_weight_date=datetime.now()))
    db.commit(); return {"ok": True}

@app.delete("/delete_food/{food_id}")
async def delete_food(food_id: int, db: Session = Depends(get_db)):
    db.query(FoodLog).filter(FoodLog.id == food_id).delete(); db.commit(); return {"ok": True}
