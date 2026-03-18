import os, json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Шлях до бази у нашому Volume
DB_DIR = "/app/data"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'fitlio.db')}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- МОДЕЛІ ---
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

# --- АВТО-РЕМОНТ БАЗИ (МІГРАЦІЯ) ---
Base.metadata.create_all(bind=engine)
with engine.connect() as conn:
    for col in ["sugar", "salt"]:
        try:
            conn.execute(text(f"ALTER TABLE fitlio_food ADD COLUMN {col} FLOAT DEFAULT 0.0"))
            conn.commit()
        except:
            pass

# --- API ---
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
    prompt = """Return ONLY JSON: {"name": "...", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}. Analyze food:"""
    try:
        if file:
            res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
        else:
            res = model.generate_content(prompt + (text_input or ""))
        return json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    except:
        return {"name": "Помилка", "kcal": 0, "p": 0, "f": 0, "c": 0, "sugar": 0, "salt": 0}

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    
    n = {"kcal": p.c_kcal if p else 2000, "p": p.c_p if p else 120, "f": p.c_f if p else 70, 
         "c": p.c_c if p else 250, "sugar": 50, "salt": 5}

    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    m_data = {}
    for mt in ["Breakfast", "Lunch", "Dinner", "Snack"]:
        items = [f for f in food if f.meal_type == mt]
        m_data[mt] = {
            "kcal": sum(i.calories or 0 for i in items),
            "p": round(sum(i.protein or 0 for i in items), 1),
            "f": round(sum(i.fat or 0 for i in items), 1),
            "c": round(sum(i.carbs or 0 for i in items), 1),
            "sugar": round(sum(i.sugar or 0 for i in items), 1),
            "salt": round(sum(i.salt or 0 for i in items), 1),
            "list": [{"name": i.food_name, "kcal": i.calories} for i in items]
        }

    return {
        "kcal": sum(f.calories or 0 for f in food), "p": round(sum(f.protein or 0 for f in food), 1),
        "f": round(sum(f.fat or 0 for f in food), 1), "c": round(sum(f.carbs or 0 for f in food), 1),
        "sugar": round(sum(f.sugar or 0 for f in food), 1), "salt": round(sum(f.salt or 0 for f in food), 1),
        "water": round(sum(w.amount or 0 for w in water), 2), "norms": n, "meals": m_data, "profile": p
    }

@app.post("/confirm_save")
async def confirm_save(data: dict, db: Session = Depends(get_db)):
    db.add(FoodLog(user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'], 
                   calories=int(data['kcal']), protein=float(data.get('p',0)), fat=float(data.get('f',0)), 
                   carbs=float(data.get('c',0)), sugar=float(data.get('sugar',0)), salt=float(data.get('salt',0)), 
                   created_at=datetime.strptime(data['date'], '%Y-%m-%d')))
    db.commit(); return {"ok": True}

@app.post("/add_water")
async def add_water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount, created_at=datetime.strptime(date, '%Y-%m-%d'))); db.commit()
    return {"ok": True}

@app.post("/save_profile")
async def save_profile(data: dict, db: Session = Depends(get_db)):
    db.merge(UserProfile(user_id=str(data['user_id']), weight=float(data['weight']), height=float(data['height']), 
                         goal=data['goal'], c_kcal=int(data['c_kcal']), c_p=int(data['c_p']), 
                         c_f=int(data['c_f']), c_c=int(data['c_c'])))
    db.commit(); return {"ok": True}
