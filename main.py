import os
import json
from pathlib import Path
from datetime import date
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from sqlalchemy.orm import declarative_base, sessionmaker
import google.generativeai as genai

# --- 1. Налаштування директорії та БД (Volume Requirement) ---
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "database.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. Моделі бази даних ---
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
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    name = Column(String)
    kcal = Column(Float)
    protein = Column(Float)
    fat = Column(Float)
    carbs = Column(Float)
    sugar = Column(Float)
    salt = Column(Float)

class WaterLog(Base):
    __tablename__ = "water_logs"
    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(String, index=True)
    log_date = Column(Date, index=True)
    amount_ml = Column(Float)

Base.metadata.create_all(bind=engine)

# --- 3. Налаштування FastAPI та Gemini ---
app = FastAPI(title="FitLio Pro API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

# --- 4. Pydantic Схеми ---
class ProfileData(BaseModel):
    tg_id: str
    goal: str
    weight: float
    target_weight: float
    height: float
    age: int

class TextFoodRequest(BaseModel):
    tg_id: str
    date: date
    text: str

class ChatMessage(BaseModel):
    tg_id: str
    message: str

# --- 5. Ендпоінти ---

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/api/profile")
def update_profile(data: ProfileData):
    db = SessionLocal()
    
    # Промпт для Gemini для розрахунку норм
    prompt = f"""
    Calculate daily nutritional norms for a person with: Age {data.age}, Height {data.height}cm, Weight {data.weight}kg, Target Weight {data.target_weight}kg, Goal: {data.goal}.
    Limits: Sugar strictly up to 50g, Salt strictly up to 5g.
    Return ONLY a valid JSON object with keys: kcal, protein, fat, carbs, sugar, salt. Values must be numbers. Do not include markdown formatting like ```json.
    """
    response = model.generate_content(prompt)
    try:
        norms = json.loads(response.text.strip('` \njson'))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to parse Gemini response for norms.")

    user = db.query(User).filter(User.tg_id == data.tg_id).first()
    if not user:
        user = User(tg_id=data.tg_id)
        db.add(user)
    
    user.goal = data.goal
    user.weight = data.weight
    user.target_weight = data.target_weight
    user.height = data.height
    user.age = data.age
    user.norm_kcal = norms.get('kcal', 2000)
    user.norm_p = norms.get('protein', 100)
    user.norm_f = norms.get('fat', 60)
    user.norm_c = norms.get('carbs', 200)
    user.norm_sugar = norms.get('sugar', 50)
    user.norm_salt = norms.get('salt', 5)
    
    db.commit()
    db.close()
    return {"status": "success", "norms": norms}

@app.get("/api/daily/{tg_id}/{log_date}")
def get_daily_data(tg_id: str, log_date: date):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user:
        db.close()
        return {"needs_setup": True}
    
    foods = db.query(FoodLog).filter(FoodLog.tg_id == tg_id, FoodLog.log_date == log_date).all()
    water = db.query(WaterLog).filter(WaterLog.tg_id == tg_id, WaterLog.log_date == log_date).all()
    total_water = sum([w.amount_ml for w in water])
    
    db.close()
    return {
        "needs_setup": False,
        "user_norms": {
            "kcal": user.norm_kcal, "protein": user.norm_p, "fat": user.norm_f, 
            "carbs": user.norm_c, "sugar": user.norm_sugar, "salt": user.norm_salt
        },
        "foods": foods,
        "water_ml": total_water
    }

@app.post("/api/food/text")
def add_food_text(req: TextFoodRequest):
    db = SessionLocal()
    prompt = f"""
    Analyze this food description: "{req.text}".
    Return ONLY a valid JSON object with keys: name (string in Ukrainian), kcal, protein, fat, carbs, sugar, salt (all numbers). 
    If weight isn't specified, assume standard portion. Do not include markdown formatting.
    """
    response = model.generate_content(prompt)
    try:
        food_data = json.loads(response.text.strip('` \njson'))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to parse Gemini response for food.")

    new_food = FoodLog(
        tg_id=req.tg_id, log_date=req.date,
        name=food_data['name'], kcal=food_data['kcal'],
        protein=food_data['protein'], fat=food_data['fat'],
        carbs=food_data['carbs'], sugar=food_data.get('sugar', 0),
        salt=food_data.get('salt', 0)
    )
    db.add(new_food)
    db.commit()
    db.close()
    return {"status": "success", "food": food_data}

@app.post("/api/food/photo")
async def add_food_photo(tg_id: str = Form(...), date_str: str = Form(...), file: UploadFile = File(...)):
    db = SessionLocal()
    contents = await file.read()
    
    image_parts = [{"mime_type": file.content_type, "data": contents}]
    prompt = "Analyze this food image. Return ONLY a valid JSON object with keys: name (string in Ukrainian), kcal, protein, fat, carbs, sugar, salt (all numbers). Assume a standard portion if scale is unclear. No markdown."
    
    response = model.generate_content([prompt, image_parts[0]])
    try:
        food_data = json.loads(response.text.strip('` \njson'))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to parse Gemini response.")

    new_food = FoodLog(
        tg_id=tg_id, log_date=date.fromisoformat(date_str),
        name=food_data['name'], kcal=food_data['kcal'],
        protein=food_data['protein'], fat=food_data['fat'],
        carbs=food_data['carbs'], sugar=food_data.get('sugar', 0),
        salt=food_data.get('salt', 0)
    )
    db.add(new_food)
    db.commit()
    db.close()
    return {"status": "success", "food": food_data}

@app.post("/api/water")
def add_water(tg_id: str = Form(...), date_str: str = Form(...), amount: float = Form(...)):
    db = SessionLocal()
    new_water = WaterLog(tg_id=tg_id, log_date=date.fromisoformat(date_str), amount_ml=amount)
    db.add(new_water)
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/chat")
def ai_chat(req: ChatMessage):
    prompt = f"Ти професійний дієтолог FitLio Pro. Користувач питає: {req.message}. Дай коротку, корисну відповідь українською мовою."
    response = model.generate_content(prompt)
    return {"reply": response.text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
