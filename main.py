import os
import json
import requests
from pathlib import Path
from datetime import date, timedelta
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, desc, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError
import google.generativeai as genai

# --- МЕТАБОЛІЧНІ ЕКВІВАЛЕНТИ (MET) ДЛЯ ВПРАВ ---
ACTIVITIES = {
    "🏃‍♂️ Біг (швидкий)": 11.5, "🏃‍♀️ Біг (повільний / підтюпцем)": 8.0,
    "🚶‍♂️ Ходьба (швидка)": 4.3, "🚶‍♀️ Ходьба (прогулянка)": 3.0,
    "🏋️‍♂️ Силове тренування (зал)": 5.0, "🦵 Присідання (інтенсивні)": 5.0,
    "🚴‍♂️ Велосипед": 7.5, "🏊‍♂️ Плавання": 6.0, "🧘‍♀️ Йога / Пілатес": 2.5,
    "🤸‍♂️ Домашнє тренування (HIIT)": 8.0, "💃 Танці": 5.0,
    "⚽️ Футбол / Баскетбол": 7.0, "🥊 Бокс / Єдиноборства": 10.0
}

# --- Налаштування директорії та БД ---
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "fitlio_base.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    tg_id = Column(String, primary_key=True, index=True)
    goal = Column(String)
    weight = Column(Float)
    target_weight = Column(Float)
    height = Column(Float)
    age = Column(Integer)
    norm_kcal = Column(Float)
    norm_p = Column(Float)
    norm_f = Column(Float)
    norm_c = Column(Float)
    norm_sugar = Column(Float)
    norm_salt = Column(Float)

class FoodLog(Base):
    __tablename__ = "food_logs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    name = Column(String)
    kcal = Column(Float)
    protein = Column(Float)
    fat = Column(Float)
    carbs = Column(Float)
    sugar = Column(Float)
    salt = Column(Float)
    fiber = Column(Float, default=0.0) # НОВА КОЛОНКА ДЛЯ КЛІТКОВИНИ

class WaterLog(Base):
    __tablename__ = "water_logs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    amount_ml = Column(Float)

class ExerciseLog(Base):
    __tablename__ = "exercise_logs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    name = Column(String)
    duration_min = Column(Integer)
    burned_kcal = Column(Float)

class WeightLog(Base):
    __tablename__ = "weight_logs"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    weight = Column(Float)

Base.metadata.create_all(bind=engine)

# БЕЗПЕЧНА МІГРАЦІЯ: Додаємо колонку fiber, якщо її ще немає, не видаляючи старі дані!
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE food_logs ADD COLUMN fiber FLOAT DEFAULT 0.0"))
        conn.commit()
    except OperationalError:
        pass # Якщо колонка вже є, скрипт просто піде далі

app = FastAPI(title="FitLio Pro API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Схеми ---
class ProfileData(BaseModel): tg_id: str; goal: str; weight: float; target_weight: float; height: float; age: int
class ManualNorms(BaseModel): tg_id: str; kcal: float; protein: float; fat: float; carbs: float; sugar: float; salt: float
class TextFoodRequest(BaseModel): tg_id: str; date: date; text: str
class BarcodeRequest(BaseModel): tg_id: str; date: date; barcode: str
class DirectFoodRequest(BaseModel): tg_id: str; date: date; food: dict
class ExerciseRequest(BaseModel): tg_id: str; date: date; name: str; duration_min: int
class WeightRequest(BaseModel): tg_id: str; date: date; weight: float
class ChatMessage(BaseModel): tg_id: str; message: str; history: List[Dict[str, str]] = []

# --- Ендпоінти ---
@app.post("/api/profile")
def update_profile(data: ProfileData):
    db = SessionLocal()
    prompt = f"Calculate daily nutritional norms for a person with: Age {data.age}, Height {data.height}cm, Weight {data.weight}kg, Target Weight {data.target_weight}kg, Goal: {data.goal}. Limits: Sugar up to 50g, Salt up to 5g. Return ONLY a valid JSON with keys: kcal, protein, fat, carbs, sugar, salt."
    try:
        response = model.generate_content(prompt)
        norms = json.loads(response.text.strip('` \njson'))
    except:
        norms = {"kcal": 2000, "protein": 100, "fat": 60, "carbs": 200, "sugar": 50, "salt": 5}

    user = db.query(User).filter(User.tg_id == data.tg_id).first()
    if not user: user = User(tg_id=data.tg_id); db.add(user)
    
    user.goal = data.goal; user.weight = data.weight; user.target_weight = data.target_weight; user.height = data.height; user.age = data.age
    user.norm_kcal = norms.get('kcal', 2000); user.norm_p = norms.get('protein', 100); user.norm_f = norms.get('fat', 60); user.norm_c = norms.get('carbs', 200); user.norm_sugar = norms.get('sugar', 50); user.norm_salt = norms.get('salt', 5)
    
    db.add(WeightLog(tg_id=data.tg_id, log_date=date.today(), weight=data.weight))
    db.commit(); db.close()
    return {"status": "success", "norms": norms}

@app.post("/api/profile/manual")
def update_manual_norms(data: ManualNorms):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == data.tg_id).first()
    if not user: user = User(tg_id=data.tg_id); db.add(user)
    user.norm_kcal = data.kcal; user.norm_p = data.protein; user.norm_f = data.fat; user.norm_c = data.carbs; user.norm_sugar = data.sugar; user.norm_salt = data.salt
    db.commit(); db.close()
    return {"status": "success"}

@app.get("/api/daily/{tg_id}/{log_date}")
def get_daily_data(tg_id: str, log_date: date):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user: return {"needs_setup": True}
    
    foods = db.query(FoodLog).filter(FoodLog.tg_id == tg_id, FoodLog.log_date == log_date).all()
    water = db.query(WaterLog).filter(WaterLog.tg_id == tg_id, WaterLog.log_date == log_date).all()
    exercises = db.query(ExerciseLog).filter(ExerciseLog.tg_id == tg_id, ExerciseLog.log_date == log_date).all()
    
    db.close()
    return {
        "needs_setup": False,
        "user_norms": {"kcal": user.norm_kcal, "protein": user.norm_p, "fat": user.norm_f, "carbs": user.norm_c, "sugar": user.norm_sugar, "salt": user.norm_salt},
        "current_weight": user.weight,
        "foods": [{"id": f.id, "name": f.name, "kcal": f.kcal, "protein": f.protein, "fat": f.fat, "carbs": f.carbs, "sugar": f.sugar, "salt": f.salt, "fiber": f.fiber} for f in foods],
        "water_ml": sum([w.amount_ml for w in water]),
        "exercises": [{"id": e.id, "name": e.name, "duration": e.duration_min, "burned": e.burned_kcal} for e in exercises],
        "total_burned_kcal": sum([e.burned_kcal for e in exercises])
    }

@app.get("/api/progress/{tg_id}")
def get_progress(tg_id: str):
    db = SessionLocal()
    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    foods = db.query(FoodLog).filter(FoodLog.tg_id == tg_id, FoodLog.log_date >= start_date, FoodLog.log_date <= end_date).all()
    progress_data = { (start_date + timedelta(days=i)).strftime("%Y-%m-%d"): 0 for i in range(7) }
    for f in foods: progress_data[f.log_date.strftime("%Y-%m-%d")] += f.kcal
    db.close()
    return {"dates": list(progress_data.keys()), "kcal": list(progress_data.values())}

@app.get("/api/foods/recent/{tg_id}")
def get_recent_foods(tg_id: str):
    db = SessionLocal()
    foods = db.query(FoodLog).filter(FoodLog.tg_id == tg_id).order_by(desc(FoodLog.id)).limit(100).all()
    unique_foods = {}
    for f in foods:
        clean_name = f.name.replace("[Сніданок] ", "").replace("[Обід] ", "").replace("[Вечеря] ", "").strip()
        if clean_name not in unique_foods:
            unique_foods[clean_name] = {"name": clean_name, "kcal": f.kcal, "protein": f.protein, "fat": f.fat, "carbs": f.carbs, "sugar": f.sugar, "salt": f.salt, "fiber": f.fiber}
    db.close()
    return list(unique_foods.values())

def save_food_to_db(req_tg_id, req_date, food_data):
    db = SessionLocal()
    # Зберігаємо клітковину офіційно в базу
    new_food = FoodLog(tg_id=req_tg_id, log_date=req_date, name=food_data['name'], kcal=food_data['kcal'], protein=food_data['protein'], fat=food_data['fat'], carbs=food_data['carbs'], sugar=food_data.get('sugar', 0), salt=food_data.get('salt', 0), fiber=food_data.get('fiber', 0))
    db.add(new_food); db.commit(); db.refresh(new_food); db.close()
    return new_food.id

@app.post("/api/food/direct")
def add_food_direct(req: DirectFoodRequest):
    save_food_to_db(req.tg_id, req.date, req.food)
    return {"status": "success"}

@app.post("/api/food/text")
def add_food_text(req: TextFoodRequest):
    prompt = f"Analyze food: '{req.text}'. Return ONLY valid JSON: keys name(string in Ukrainian), kcal, protein, fat, carbs, fiber, sugar, salt (numbers). No markdown."
    response = model.generate_content(prompt)
    food_data = json.loads(response.text.strip('` \njson'))
    save_food_to_db(req.tg_id, req.date, food_data)
    return {"status": "success", "food": food_data}

@app.post("/api/food/photo")
async def add_food_photo(tg_id: str = Form(...), date_str: str = Form(...), file: UploadFile = File(...)):
    contents = await file.read()
    response = model.generate_content(["Analyze food image. Return ONLY valid JSON: name(string in Ukrainian), kcal, protein, fat, carbs, fiber, sugar, salt(numbers). No markdown.", {"mime_type": file.content_type, "data": contents}])
    food_data = json.loads(response.text.strip('` \njson'))
    save_food_to_db(tg_id, date.fromisoformat(date_str), food_data)
    return {"status": "success", "data": food_data}

@app.post("/api/food/barcode")
def add_food_barcode(req: BarcodeRequest):
    url = f"https://world.openfoodfacts.org/api/v0/product/{req.barcode}.json"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get("status") == 1:
            product = resp["product"]
            name = product.get("product_name_uk") or product.get("product_name_ru") or product.get("product_name") or "Невідомий продукт"
            serving = float(product.get("serving_quantity", 100))
            multiplier = serving / 100.0
            nutriments = product.get("nutriments", {})
            
            kcal = float(nutriments.get("energy-kcal_100g", 0)) * multiplier
            protein = float(nutriments.get("proteins_100g", 0)) * multiplier
            fat = float(nutriments.get("fat_100g", 0)) * multiplier
            carbs = float(nutriments.get("carbohydrates_100g", 0)) * multiplier
            fiber = float(nutriments.get("fiber_100g", 0)) * multiplier
            
            food_data = {"name": f"📱 {name} ({int(serving)}г)", "kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs, "fiber": fiber, "sugar": 0, "salt": 0}
            save_food_to_db(req.tg_id, req.date, food_data)
            return {"status": "success", "name": food_data["name"], "kcal": food_data["kcal"], "food": food_data}
    except:
        pass 

    prompt = f"User scanned a barcode: {req.barcode}. If you guess the product, return info. If unknown, return generic 'Невідомий продукт' with 0 macros. Return ONLY valid JSON: name(string in Ukrainian), kcal, protein, fat, carbs, fiber, sugar, salt(numbers). No markdown."
    response = model.generate_content(prompt)
    try: food_data = json.loads(response.text.strip('` \njson'))
    except: food_data = {"name": f"Продукт {req.barcode}", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0, "sugar": 0, "salt": 0}
    save_food_to_db(req.tg_id, req.date, food_data)
    return {"status": "success", "name": food_data["name"], "kcal": food_data["kcal"], "food": food_data}

@app.delete("/api/food/{food_id}")
def delete_food(food_id: int):
    db = SessionLocal()
    db.query(FoodLog).filter(FoodLog.id == food_id).delete(); db.commit(); db.close()
    return {"status": "success"}

@app.delete("/api/exercise/{exercise_id}")
def delete_exercise(exercise_id: int):
    db = SessionLocal()
    db.query(ExerciseLog).filter(ExerciseLog.id == exercise_id).delete()
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/water")
def add_water(tg_id: str = Form(...), date_str: str = Form(...), amount: float = Form(...)):
    db = SessionLocal()
    db.add(WaterLog(tg_id=tg_id, log_date=date.fromisoformat(date_str), amount_ml=amount)); db.commit(); db.close()
    return {"status": "success"}

@app.post("/api/exercise")
def add_exercise(req: ExerciseRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == req.tg_id).first()
    weight = user.weight if user and user.weight else 70.0
    met = ACTIVITIES.get(req.name, 5.0)
    burned_kcal = met * weight * (req.duration_min / 60.0)
    db.add(ExerciseLog(tg_id=req.tg_id, log_date=req.date, name=req.name, duration_min=req.duration_min, burned_kcal=burned_kcal))
    db.commit(); db.close()
    return {"status": "success", "burned_kcal": burned_kcal}

@app.post("/api/weight")
def update_weight(req: WeightRequest):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == req.tg_id).first()
    if user: user.weight = req.weight
    db.add(WeightLog(tg_id=req.tg_id, log_date=req.date, weight=req.weight))
    db.commit(); db.close()
    return {"status": "success"}

@app.post("/api/chat")
def ai_chat(req: ChatMessage):
    context = "\n".join([f"{msg['role']}: {msg['text']}" for msg in req.history[-6:]])
    prompt = f"Ти професійний дієтолог FitLio. Контекст розмови:\n{context}\nКористувач каже: {req.message}. Дай коротку і корисну відповідь українською."
    response = model.generate_content(prompt)
    return {"reply": response.text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
