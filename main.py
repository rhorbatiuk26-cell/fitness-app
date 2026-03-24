import os
import json
import requests
import asyncio
import re
from pathlib import Path
from datetime import date, timedelta, datetime
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, desc, text
from sqlalchemy.orm import declarative_base, sessionmaker
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
    norm_fiber = Column(Float, default=28.0)
    
    # --- МОНЕТИЗАЦІЯ ---
    subscription_end = Column(Date, default=lambda: (datetime.now() + timedelta(days=3)).date())
    referred_by = Column(String, nullable=True)

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
    fiber = Column(Float, default=0.0) 

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

# БЕЗПЕЧНА МІГРАЦІЯ
with engine.connect() as conn:
    try: conn.execute(text("ALTER TABLE food_logs ADD COLUMN fiber FLOAT DEFAULT 0.0")); conn.commit()
    except Exception: pass
    try: conn.execute(text("ALTER TABLE users ADD COLUMN norm_fiber FLOAT DEFAULT 28.0")); conn.commit()
    except Exception: pass
    try: conn.execute(text("ALTER TABLE users ADD COLUMN subscription_end DATE")); conn.commit()
    except Exception: pass
    try: conn.execute(text("ALTER TABLE users ADD COLUMN referred_by VARCHAR")); conn.commit()
    except Exception: pass

app = FastAPI(title="FitLio Pro API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
BOT_TOKEN = os.getenv("BOT_TOKEN") 
# ЗАМІНИ НА ЮЗЕРНЕЙМ СВОГО БОТА (без @)
BOT_USERNAME = "fitlio_final_ai_bot" 

def clean_json_response(text):
    try:
        clean_text = text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except:
        match = re.search(r'(\{.*?\}|\[.*?\])', text, re.DOTALL)
        if match:
            try: return json.loads(match.group(1))
            except: pass
    return None

class ProfileData(BaseModel): tg_id: str; goal: str; weight: float; target_weight: float; height: float; age: int
class ManualNorms(BaseModel): tg_id: str; kcal: float; protein: float; fat: float; carbs: float; sugar: float; salt: float; fiber: float
class TextFoodRequest(BaseModel): tg_id: str; date: date; text: str
class DirectFoodRequest(BaseModel): tg_id: str; date: date; food: dict
class ExerciseRequest(BaseModel): tg_id: str; date: date; name: str; duration_min: int; custom_kcal: Optional[float] = None
class WeightRequest(BaseModel): tg_id: str; date: date; weight: float
class ChatMessage(BaseModel): tg_id: str; message: str; history: List[Dict[str, str]] = []

# --- ТЕЛЕГРАМ WEBHOOK ---
@app.post("/api/webhook/telegram")
async def telegram_webhook(request: Request):
    if not BOT_TOKEN: return {"ok": True}
    
    try:
        update = await request.json()
        db = SessionLocal()
        
        # 1. Запит перед оплатою (Telegram Stars)
        if "pre_checkout_query" in update:
            pq_id = update["pre_checkout_query"]["id"]
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery", json={"pre_checkout_query_id": pq_id, "ok": True})
            db.close()
            return {"ok": True}
            
        # 2. Обробка повідомлень
        if "message" in update:
            msg = update["message"]
            tg_id = str(msg.get("from", {}).get("id"))
            text = msg.get("text", "")
            
            # А) Старт та реферальна система
            if text.startswith("/start"):
                parts = text.split()
                ref_id = parts[1] if len(parts) > 1 else None
                
                user = db.query(User).filter(User.tg_id == tg_id).first()
                if not user:
                    user = User(tg_id=tg_id, referred_by=ref_id, subscription_end=date.today() + timedelta(days=3))
                    db.add(user)
                elif not user.referred_by and ref_id and ref_id != tg_id:
                    user.referred_by = ref_id
                db.commit()
                
                # Кнопка для відкриття Mini App
                keyboard = {"inline_keyboard": [[{"text": "Відкрити FitLio Pro 🍏", "web_app": {"url": "https://fitness-app-production-b4a3.up.railway.app/"}}]]}
                welcome_text = (
                    "👋 <b>Вітаю у FitLio Pro!</b>\n\n"
                    "Я твій розумний AI-щоденник харчування та тренувань. Що я вмію:\n\n"
                    "📸 <b>Розпізнавати їжу по фото:</b> просто сфотографуй тарілку, а я порахую калорії та БЖВ.\n"
                    "🎯 <b>Персональні норми:</b> розрахую твою ідеальну норму для схуднення чи набору маси.\n"
                    "🏃‍♂️ <b>Трекінг активності:</b> записуй тренування та воду в один клік.\n\n"
                    "🎁 <i>Тобі автоматично нараховано 3 дні безкоштовного PRO-доступу!</i>\n\n"
                    "Тисни кнопку нижче, щоб налаштувати свій профіль і почати 👇"
                )
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                    "chat_id": tg_id, 
                    "text": welcome_text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                })

            # Б) Успішна оплата (100 Stars)
            if "successful_payment" in msg:
                user = db.query(User).filter(User.tg_id == tg_id).first()
                if user:
                    today = date.today()
                    # Нараховуємо 30 днів тому, хто купив
                    if user.subscription_end and user.subscription_end > today:
                        user.subscription_end += timedelta(days=30)
                    else:
                        user.subscription_end = today + timedelta(days=30)
                        
                    # Нараховуємо 7 днів рефоводу
                    if user.referred_by:
                        referrer = db.query(User).filter(User.tg_id == user.referred_by).first()
                        if referrer:
                            if referrer.subscription_end and referrer.subscription_end > today:
                                referrer.subscription_end += timedelta(days=7)
                            else:
                                referrer.subscription_end = today + timedelta(days=7)
                            
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                                "chat_id": referrer.tg_id, "text": "🎁 Твій друг щойно оплатив підписку! Тобі нараховано +7 днів до FitLio Pro безкоштовно!"
                            })
                    db.commit()
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                        "chat_id": tg_id, "text": "🎉 Оплата успішна! Ти отримав 1 місяць доступу. Заходь у додаток!"
                    })
        db.close()
    except Exception as e:
        print("Webhook Error:", e)
        
    return {"ok": True}

# --- ЕНДПОІНТИ ПІДПИСКИ ТА ОПЛАТИ ---
@app.get("/api/subscription/{tg_id}")
def get_subscription(tg_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == tg_id).first()
    
    if not user:
        db.close()
        return {"is_active": True, "days_left": 3, "ref_link": f"https://t.me/{BOT_USERNAME}?start={tg_id}"}
        
    today = date.today()
    if not user.subscription_end:
        user.subscription_end = today + timedelta(days=3)
        db.commit()
        
    days_left = (user.subscription_end - today).days
    is_active = days_left >= 0
    
    db.close()
    return {
        "is_active": is_active, 
        "days_left": max(0, days_left), 
        "end_date": user.subscription_end.strftime("%d.%m.%Y"),
        "ref_link": f"https://t.me/{BOT_USERNAME}?start={tg_id}"
    }

@app.get("/api/invoice/stars/{tg_id}")
def get_stars_invoice(tg_id: str):
    if not BOT_TOKEN: return {"status": "error", "message": "BOT_TOKEN not set"}
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    payload = {
        "title": "FitLio Pro - 1 місяць", "description": "Повний доступ до AI-дієтолога",
        "payload": f"sub_{tg_id}", "currency": "XTR", "prices": [{"label": "Місяць", "amount": 100}]
    }
    resp = requests.post(url, json=payload).json()
    if resp.get("ok"): return {"status": "success", "invoice_url": resp["result"]}
    else: return {"status": "error", "message": resp.get("description")}

@app.get("/api/admin/grant/{target_tg_id}")
def grant_lifetime_access(target_tg_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == target_tg_id).first()
    if not user:
        user = User(tg_id=target_tg_id); db.add(user)
    user.subscription_end = date.today() + timedelta(days=18250)
    db.commit(); db.close()
    return {"status": "success", "message": f"Доступ на 50 років видано для {target_tg_id}"}

# --- ОСНОВНІ ЕНДПОІНТИ ---
@app.post("/api/profile")
def update_profile(data: ProfileData):
    db = SessionLocal()
    prompt = f"Calculate daily nutritional norms for a person with: Age {data.age}, Height {data.height}cm, Weight {data.weight}kg, Target Weight {data.target_weight}kg, Goal: {data.goal}. Limits: Sugar up to 50g, Salt up to 5g. Return ONLY a valid JSON with keys: kcal, protein, fat, carbs (MUST BE STRICTLY NET CARBS, total carbs minus fiber), sugar, salt, fiber (calculate separately, approx 14g per 1000 kcal)."
    try:
        response = model.generate_content(prompt)
        norms = clean_json_response(response.text) or {"kcal": 2000, "protein": 100, "fat": 60, "carbs": 200, "sugar": 50, "salt": 5, "fiber": 28}
    except:
        norms = {"kcal": 2000, "protein": 100, "fat": 60, "carbs": 200, "sugar": 50, "salt": 5, "fiber": 28}

    user = db.query(User).filter(User.tg_id == data.tg_id).first()
    if not user: user = User(tg_id=data.tg_id); db.add(user)
    
    user.goal = data.goal; user.weight = data.weight; user.target_weight = data.target_weight; user.height = data.height; user.age = data.age
    user.norm_kcal = norms.get('kcal', 2000); user.norm_p = norms.get('protein', 100); user.norm_f = norms.get('fat', 60); user.norm_c = norms.get('carbs', 200)
    user.norm_sugar = norms.get('sugar', 50); user.norm_salt = norms.get('salt', 5); user.norm_fiber = norms.get('fiber', 28)
    
    db.add(WeightLog(tg_id=data.tg_id, log_date=date.today(), weight=data.weight))
    db.commit(); db.close()
    return {"status": "success", "norms": norms}

@app.post("/api/profile/manual")
def update_manual_norms(data: ManualNorms):
    db = SessionLocal()
    user = db.query(User).filter(User.tg_id == data.tg_id).first()
    if not user: user = User(tg_id=data.tg_id); db.add(user)
    user.norm_kcal = data.kcal; user.norm_p = data.protein; user.norm_f = data.fat; user.norm_c = data.carbs
    user.norm_sugar = data.sugar; user.norm_salt = data.salt; user.norm_fiber = data.fiber
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
        "user_norms": {"kcal": user.norm_kcal, "protein": user.norm_p, "fat": user.norm_f, "carbs": user.norm_c, "sugar": user.norm_sugar, "salt": user.norm_salt, "fiber": user.norm_fiber},
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

@app.get("/api/progress/weight/{tg_id}")
def get_weight_progress(tg_id: str):
    db = SessionLocal()
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    logs = db.query(WeightLog).filter(WeightLog.tg_id == tg_id, WeightLog.log_date >= start_date, WeightLog.log_date <= end_date).order_by(WeightLog.log_date).all()
    weight_dict = {}
    for w in logs: weight_dict[w.log_date.strftime("%Y-%m-%d")] = w.weight
    db.close()
    return {"dates": list(weight_dict.keys()), "weights": list(weight_dict.values())}

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
    new_food = FoodLog(tg_id=req_tg_id, log_date=req_date, name=food_data['name'], kcal=food_data['kcal'], protein=food_data['protein'], fat=food_data['fat'], carbs=food_data['carbs'], sugar=food_data.get('sugar', 0), salt=food_data.get('salt', 0), fiber=food_data.get('fiber', 0))
    db.add(new_food); db.commit(); db.refresh(new_food); db.close()
    return new_food.id

@app.post("/api/food/direct")
def add_food_direct(req: DirectFoodRequest):
    save_food_to_db(req.tg_id, req.date, req.food)
    return {"status": "success"}

@app.post("/api/food/text")
def add_food_text(req: TextFoodRequest):
    prompt = f"Calculate the TOTAL combined exact macros for all items mentioned here: '{req.text}'. SUM their nutritional values into ONE single object. Combine names (e.g., 'Вівсянка (200г) + Кава'). Return ONLY ONE valid JSON object with keys: \"name\" (string, with weights), \"kcal\", \"protein\", \"fat\", \"carbs\" (MUST BE STRICTLY NET CARBS. E.g. if avocado has 9g total carbs and 7g fiber, return 2 for carbs), \"fiber\", \"sugar\", \"salt\" (numbers)."
    try:
        response = model.generate_content(prompt)
        food_data = clean_json_response(response.text)
        if isinstance(food_data, list): food_data = food_data[0] if food_data else None
        if not food_data: raise Exception("Invalid JSON")
        return {"status": "success", "food": food_data}
    except:
        return {"status": "success", "food": {"name": f"{req.text} (помилка ШІ)", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0, "sugar": 0, "salt": 0}}

@app.post("/api/food/photo")
async def add_food_photo(tg_id: str = Form(...), date_str: str = Form(...), file: UploadFile = File(...)):
    contents = await file.read()
    prompt = "Analyze food image. Combine into ONE single meal description and SUM nutritional values. Return ONLY ONE valid JSON object with keys: \"name\" (string in Ukrainian, combine names and weight), \"kcal\", \"protein\", \"fat\", \"carbs\" (MUST BE STRICTLY NET CARBS: Total carbs minus fiber), \"fiber\", \"sugar\", \"salt\" (numbers)."
    try:
        response = model.generate_content([prompt, {"mime_type": file.content_type, "data": contents}])
        food_data = clean_json_response(response.text)
        if isinstance(food_data, list): food_data = food_data[0] if food_data else None
        if not food_data: raise Exception("Invalid JSON")
        return {"status": "success", "data": food_data}
    except:
        return {"status": "success", "data": {"name": "Не вдалося розпізнати", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0, "sugar": 0, "salt": 0}}

@app.delete("/api/food/{food_id}")
def delete_food(food_id: int):
    db = SessionLocal(); db.query(FoodLog).filter(FoodLog.id == food_id).delete(); db.commit(); db.close()
    return {"status": "success"}

@app.delete("/api/exercise/{exercise_id}")
def delete_exercise(exercise_id: int):
    db = SessionLocal(); db.query(ExerciseLog).filter(ExerciseLog.id == exercise_id).delete(); db.commit(); db.close()
    return {"status": "success"}

@app.post("/api/water")
def add_water(tg_id: str = Form(...), date_str: str = Form(...), amount: float = Form(...)):
    db = SessionLocal(); db.add(WaterLog(tg_id=tg_id, log_date=date.fromisoformat(date_str), amount_ml=amount)); db.commit(); db.close()
    return {"status": "success"}

@app.post("/api/exercise")
def add_exercise(req: ExerciseRequest):
    db = SessionLocal()
    if req.custom_kcal is not None and req.custom_kcal > 0: burned_kcal = req.custom_kcal
    else:
        user = db.query(User).filter(User.tg_id == req.tg_id).first()
        weight = user.weight if user and user.weight else 70.0
        burned_kcal = ACTIVITIES.get(req.name, 5.0) * weight * (req.duration_min / 60.0)
    db.add(ExerciseLog(tg_id=req.tg_id, log_date=req.date, name=req.name, duration_min=req.duration_min, burned_kcal=burned_kcal))
    db.commit(); db.close()
    return {"status": "success", "burned_kcal": burned_kcal}

@app.post("/api/weight")
def update_weight(req: WeightRequest):
    db = SessionLocal(); user = db.query(User).filter(User.tg_id == req.tg_id).first()
    if user: user.weight = req.weight
    db.add(WeightLog(tg_id=req.tg_id, log_date=req.date, weight=req.weight)); db.commit(); db.close()
    return {"status": "success"}

@app.post("/api/chat")
def ai_chat(req: ChatMessage):
    context = "\n".join([f"{msg['role']}: {msg['text']}" for msg in req.history[-6:]])
    prompt = f"Ти професійний дієтолог FitLio. Контекст розмови:\n{context}\nКористувач каже: {req.message}. Дай коротку і корисну відповідь українською."
    return {"reply": model.generate_content(prompt).text}

async def smart_reminders_task():
    while True:
        now = datetime.now()
        if now.hour == 20 and now.minute == 0 and BOT_TOKEN:
            db = SessionLocal()
            for user in db.query(User).all():
                if sum([w.amount_ml for w in db.query(WaterLog).filter(WaterLog.tg_id == user.tg_id, WaterLog.log_date == date.today()).all()]) < 2000:
                    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": user.tg_id, "text": "💧 Гей! Ти сьогодні випив мало води. Час зробити ковток!"}, timeout=5)
                    except: pass
            db.close()
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event(): asyncio.create_task(smart_reminders_task())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
