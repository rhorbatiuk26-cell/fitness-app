import os
import json
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# 1. НАЛАШТУВАННЯ БАЗИ ДАНИХ (Шлях для Volume у Railway)
DB_DIR = "/app/data"
# Перевіряємо чи існує папка, якщо ні - створюємо (це важливо для стабільності)
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_DIR}/database.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. МОДЕЛІ ДАНИХ
class UserProfile(Base):
    __tablename__ = "profiles"
    user_id = Column(String, primary_key=True)
    goal = Column(String)
    target_weight = Column(Float)
    c_kcal = Column(Integer)
    c_p = Column(Integer)
    c_f = Column(Integer)
    c_c = Column(Integer)
    c_sugar = Column(Integer)
    c_salt = Column(Integer)

class FoodLog(Base):
    __tablename__ = "food"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    meal_type = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Float)
    fat = Column(Float)
    carbs = Column(Float)
    sugar = Column(Float)
    salt = Column(Float)
    created_at = Column(DateTime)

class WaterLog(Base):
    __tablename__ = "water"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime)

# Створюємо таблиці
Base.metadata.create_all(bind=engine)

# 3. НАЛАШТУВАННЯ AI (Gemini)
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 4. ЕНДПОІНТИ (ФУНКЦІЇ)

@app.get("/stats")
async def get_stats(user_id: str, date: str, db: Session = Depends(get_db)):
    dt = datetime.strptime(date, '%Y-%m-%d').date()
    p = db.query(UserProfile).filter(UserProfile.user_id == str(user_id)).first()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), func.date(FoodLog.created_at) == dt).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), func.date(WaterLog.created_at) == dt).all()
    
    meals_map = {mt: {"kcal": 0, "list": []} for mt in ["Breakfast", "Snack1", "Lunch", "Snack2", "Dinner"]}
    for f in food:
        meals_map[f.meal_type]["kcal"] += f.calories
        meals_map[f.meal_type]["list"].append({
            "food_name": f.food_name, "calories": f.calories, "protein": f.protein,
            "fat": f.fat, "carbs": f.carbs, "sugar": f.sugar, "salt": f.salt
        })
        
    return {
        "totals": {
            "kcal": sum(f.calories for f in food), "p": round(sum(f.protein for f in food), 1),
            "f": round(sum(f.fat for f in food), 1), "c": round(sum(f.carbs for f in food), 1),
            "sugar": round(sum(f.sugar for f in food), 1), "salt": round(sum(f.salt for f in food), 1)
        },
        "norms": {
            "kcal": p.c_kcal, "p": p.c_p, "f": p.c_f, "c": p.c_c, 
            "sugar": p.c_sugar, "salt": p.c_salt, "goal": p.goal, "tw": p.target_weight
        } if p else None,
        "water": round(sum(w.amount for w in water), 2),
        "meals": meals_map
    }

@app.post("/setup")
async def setup(data: dict, db: Session = Depends(get_db)):
    prompt = f"Розрахуй КБЖВ для цілі {data['goal']}, бажана вага {data['tw']}кг. Поточна: {data['w']}кг, {data['h']}см, {data['a']} років. Поверни ТІЛЬКИ JSON: {{'kcal':0,'p':0,'f':0,'c':0,'sugar':50,'salt':5}}"
    res = model.generate_content(prompt)
    n = json.loads(res.text[res.text.find("{"):res.text.rfind("}")+1])
    
    profile = UserProfile(
        user_id=str(data['user_id']), goal=data['goal'], target_weight=float(data['tw']),
        c_kcal=n['kcal'], c_p=n['p'], c_f=n['f'], c_c=n['c'], 
        c_sugar=n.get('sugar', 50), c_salt=n.get('salt', 5)
    )
    db.merge(profile)
    db.commit()
    return {"ok": True}

@app.post("/analyze")
async def analyze(text_input: str = Form(None), file: UploadFile = File(None)):
    prompt = "Проаналізуй їжу. Поверни ТІЛЬКИ JSON: {'name':'','kcal':0,'p':0,'f':0,'c':0,'sugar':0,'salt':0}"
    if file:
        res = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": await file.read()}])
    else:
        res = model.generate_content(prompt + (text_input or ""))
    
    clean_json = res.text[res.text.find("{"):res.text.rfind("}")+1]
    return json.loads(clean_json)

@app.post("/add_food")
async def add_food(data: dict, db: Session = Depends(get_db)):
    new_food = FoodLog(
        user_id=str(data['user_id']), meal_type=data['meal_type'], food_name=data['name'],
        calories=data['kcal'], protein=data['p'], fat=data['f'], carbs=data['c'],
        sugar=data['sugar'], salt=data['salt'], 
        created_at=datetime.strptime(data['date'], '%Y-%m-%d')
    )
    db.add(new_food)
    db.commit()
    return {"ok": True}

@app.post("/water")
async def water(user_id: str, date: str, amount: float, db: Session = Depends(get_db)):
    new_water = WaterLog(
        user_id=str(user_id), amount=amount, 
        created_at=datetime.strptime(date, '%Y-%m-%d')
    )
    db.add(new_water)
    db.commit()
    return {"ok": True}

@app.post("/chat")
async def chat(msg: str = Form(...)):
    res = model.generate_content(f"Ти професійний дієтолог FitLio. Відповідай коротко і по справі: {msg}")
    return {"reply": res.text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
