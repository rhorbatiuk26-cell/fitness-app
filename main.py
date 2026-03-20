import os
import sqlite3
import json
from datetime import datetime, timedelta
import requests

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import google.generativeai as genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')

DB_PATH = "/app/data/database.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# --- МЕТАБОЛІЧНІ ЕКВІВАЛЕНТИ (MET) ДЛЯ ВПРАВ ---
ACTIVITIES = {
    "🏃‍♂️ Біг (швидкий)": 11.5,
    "🏃‍♀️ Біг (повільний / підтюпцем)": 8.0,
    "🚶‍♂️ Ходьба (швидка)": 4.3,
    "🚶‍♀️ Ходьба (прогулянка)": 3.0,
    "🏋️‍♂️ Силове тренування (зал)": 5.0,
    "🦵 Присідання (інтенсивні)": 5.0,
    "🚴‍♂️ Велосипед": 7.5,
    "🏊‍♂️ Плавання": 6.0,
    "🧘‍♀️ Йога / Пілатес": 2.5,
    "🤸‍♂️ Домашнє тренування (HIIT)": 8.0,
    "💃 Танці": 5.0,
    "⚽️ Футбол / Баскетбол": 7.0,
    "🥊 Бокс / Єдиноборства": 10.0
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        tg_id TEXT PRIMARY KEY, goal TEXT, age INTEGER, height REAL, 
                        weight REAL, target_weight REAL,
                        kcal REAL, protein REAL, fat REAL, carbs REAL, sugar REAL, salt REAL
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS food_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id TEXT, date TEXT, name TEXT,
                        kcal REAL, protein REAL, fat REAL, carbs REAL, sugar REAL, salt REAL
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS water_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id TEXT, date TEXT, amount INTEGER
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS exercise_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id TEXT, date TEXT, name TEXT, duration_min INTEGER, burned_kcal REAL
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS weight_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id TEXT, date TEXT, weight REAL
                    )''')
    conn.commit()
    conn.close()

init_db()

# --- МОДЕЛІ ---
class ProfileSetup(BaseModel):
    tg_id: str; goal: str; age: int; height: float; weight: float; target_weight: float

class ManualProfileSetup(BaseModel):
    tg_id: str; kcal: float; protein: float; fat: float; carbs: float; sugar: float; salt: float

class FoodTextRequest(BaseModel):
    tg_id: str; date: str; text: str

class BarcodeRequest(BaseModel):
    tg_id: str; date: str; barcode: str

class DirectFoodRequest(BaseModel):
    tg_id: str; date: str; food: dict

class ExerciseRequest(BaseModel):
    tg_id: str; date: str; name: str; duration_min: int

class WeightRequest(BaseModel):
    tg_id: str; date: str; weight: float

class ChatRequest(BaseModel):
    tg_id: str; message: str; history: list

def parse_ai_json(text: str):
    clean_text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

# --- API ЕНДПОІНТИ ---

@app.get("/api/daily/{tg_id}/{date}")
async def get_daily_data(tg_id: str, date: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT kcal, protein, fat, carbs, weight FROM users WHERE tg_id=?", (tg_id,))
    user_data = cursor.fetchone()
    if not user_data:
        conn.close()
        return {"needs_setup": True}
    
    norms = {"kcal": user_data[0], "protein": user_data[1], "fat": user_data[2], "carbs": user_data[3]}
    current_weight = user_data[4]
    
    cursor.execute("SELECT id, name, kcal FROM food_logs WHERE tg_id=? AND date=?", (tg_id, date))
    foods = [{"id": r[0], "name": r[1], "kcal": r[2]} for r in cursor.fetchall()]
    
    cursor.execute("SELECT SUM(kcal) FROM food_logs WHERE tg_id=? AND date=?", (tg_id, date))
    consumed_kcal = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM water_logs WHERE tg_id=? AND date=?", (tg_id, date))
    water = cursor.fetchone()[0] or 0

    cursor.execute("SELECT id, name, duration_min, burned_kcal FROM exercise_logs WHERE tg_id=? AND date=?", (tg_id, date))
    exercises = [{"id": r[0], "name": r[1], "duration": r[2], "burned": r[3]} for r in cursor.fetchall()]
    
    cursor.execute("SELECT SUM(burned_kcal) FROM exercise_logs WHERE tg_id=? AND date=?", (tg_id, date))
    total_burned = cursor.fetchone()[0] or 0

    conn.close()
    return {
        "needs_setup": False, 
        "user_norms": norms, 
        "current_weight": current_weight,
        "consumed_kcal": consumed_kcal,
        "foods": foods, 
        "water_ml": water,
        "exercises": exercises,
        "total_burned_kcal": total_burned,
        "activities_list": list(ACTIVITIES.keys())
    }

@app.post("/api/profile")
async def setup_profile_ai(req: ProfileSetup):
    bmr = 10 * req.weight + 6.25 * req.height - 5 * req.age + 5 
    if req.goal == "Схуднення": kcal = bmr * 1.2 - 400
    elif req.goal == "М'язи": kcal = bmr * 1.55 + 300
    else: kcal = bmr * 1.3
    protein = (kcal * 0.3) / 4; fat = (kcal * 0.25) / 9; carbs = (kcal * 0.45) / 4

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''REPLACE INTO users (tg_id, goal, age, height, weight, target_weight, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 50, 5)''',
                   (req.tg_id, req.goal, req.age, req.height, req.weight, req.target_weight, kcal, protein, fat, carbs))
    cursor.execute("INSERT INTO weight_logs (tg_id, date, weight) VALUES (?, ?, ?)", (req.tg_id, datetime.now().strftime("%Y-%m-%d"), req.weight))
    conn.commit(); conn.close()
    return {"status": "success"}

@app.post("/api/profile/manual")
async def setup_profile_manual(req: ManualProfileSetup):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO users (tg_id, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?)
                      ON CONFLICT(tg_id) DO UPDATE SET
                      kcal=excluded.kcal, protein=excluded.protein, fat=excluded.fat, carbs=excluded.carbs, sugar=excluded.sugar, salt=excluded.salt''',
                   (req.tg_id, req.kcal, req.protein, req.fat, req.carbs, req.sugar, req.salt))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/exercise")
async def add_exercise(req: ExerciseRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT weight FROM users WHERE tg_id=?", (req.tg_id,))
    row = cursor.fetchone()
    weight = row[0] if row else 70.0 
    
    met = ACTIVITIES.get(req.name, 5.0)
    burned_kcal = met * weight * (req.duration_min / 60.0)
    
    cursor.execute('''INSERT INTO exercise_logs (tg_id, date, name, duration_min, burned_kcal)
                      VALUES (?, ?, ?, ?, ?)''', (req.tg_id, req.date, req.name, req.duration_min, burned_kcal))
    conn.commit(); conn.close()
    return {"status": "success", "burned_kcal": round(burned_kcal)}

@app.post("/api/weight")
async def update_weight(req: WeightRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO weight_logs (tg_id, date, weight) VALUES (?, ?, ?)", (req.tg_id, req.date, req.weight))
    cursor.execute("UPDATE users SET weight=? WHERE tg_id=?", (req.weight, req.tg_id))
    conn.commit(); conn.close()
    return {"status": "success"}

@app.post("/api/food/barcode")
async def add_food_barcode(req: BarcodeRequest):
    url = f"https://world.openfoodfacts.org/api/v0/product/{req.barcode}.json"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get("status") != 1: return {"status": "error", "message": "Продукт не знайдено"}
        product = resp["product"]
        name = product.get("product_name_uk") or product.get("product_name_ru") or product.get("product_name") or "Невідомий продукт"
        serving = float(product.get("serving_quantity", 100))
        multiplier = serving / 100.0
        nutriments = product.get("nutriments", {})
        
        kcal = float(nutriments.get("energy-kcal_100g", 0)) * multiplier
        protein = float(nutriments.get("proteins_100g", 0)) * multiplier
        fat = float(nutriments.get("fat_100g", 0)) * multiplier
        carbs = float(nutriments.get("carbohydrates_100g", 0)) * multiplier

        final_name = f"📱 {name} ({int(serving)}г)"
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                          VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)''', (req.tg_id, req.date, final_name, kcal, protein, fat, carbs))
        conn.commit(); conn.close()
        return {"status": "success", "name": final_name, "kcal": round(kcal)}
    except Exception as e:
        return {"status": "error", "message": "Помилка зв'язку"}

@app.post("/api/food/text")
async def add_food_text(req: FoodTextRequest):
    prompt = f"З'їдено: '{req.text}'. Визнач калорії та БЖВ. Поверни ТІЛЬКИ JSON: {{\"name\": \"Назва\", \"kcal\": 0, \"protein\": 0, \"fat\": 0, \"carbs\": 0, \"sugar\": 0, \"salt\": 0}}"
    response = model.generate_content(prompt)
    data = parse_ai_json(response.text)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (req.tg_id, req.date, data['name'], data['kcal'], data['protein'], data['fat'], data['carbs'], data['sugar'], data['salt']))
    conn.commit(); conn.close()
    return {"status": "success", "data": data}

@app.post("/api/food/photo")
async def add_food_photo(tg_id: str = Form(...), date_str: str = Form(...), file: UploadFile = File(...)):
    import PIL.Image
    import io
    image_data = await file.read()
    image = PIL.Image.open(io.BytesIO(image_data))
    
    prompt = """Проаналізуй страву на фото. Оціни вагу, калорії, БЖВ. 
    Поверни ТІЛЬКИ JSON: {"name": "Назва", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "sugar": 0, "salt": 0}"""
    response = model.generate_content([prompt, image])
    data = parse_ai_json(response.text)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (tg_id, date_str, data['name'], data['kcal'], data['protein'], data['fat'], data['carbs'], data['sugar'], data['salt']))
    conn.commit()
    conn.close()
    return {"status": "success", "data": data}

@app.post("/api/food/direct")
async def add_direct_food(req: DirectFoodRequest):
    f = req.food
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (req.tg_id, req.date, f['name'], f['kcal'], f['protein'], f['fat'], f['carbs'], f.get('sugar',0), f.get('salt',0)))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/water")
async def add_water(tg_id: str = Form(...), date_str: str = Form(...), amount: int = Form(...)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO water_logs (tg_id, date, amount) VALUES (?, ?, ?)", (tg_id, date_str, amount))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/api/food/{food_id}")
async def delete_food(food_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM food_logs WHERE id=?", (food_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/progress/{tg_id}")
async def get_progress(tg_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    dates = []
    kcal_data = []
    today = datetime.now()
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        cursor.execute("SELECT SUM(kcal) FROM food_logs WHERE tg_id=? AND date=?", (tg_id, d))
        total = cursor.fetchone()[0] or 0
        dates.append(d)
        kcal_data.append(total)
    conn.close()
    return {"dates": dates, "kcal": kcal_data}

@app.get("/api/foods/recent/{tg_id}")
async def get_recent_foods(tg_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''SELECT name, kcal, protein, fat, carbs, sugar, salt 
                      FROM food_logs WHERE tg_id=? 
                      GROUP BY name ORDER BY id DESC LIMIT 15''', (tg_id,))
    foods = [{"name": r[0], "kcal": r[1], "protein": r[2], "fat": r[3], "carbs": r[4], "sugar": r[5], "salt": r[6]} for r in cursor.fetchall()]
    conn.close()
    return foods

@app.post("/api/chat")
async def chat_with_ai(req: ChatRequest):
    messages = [{"role": "user", "parts": ["Ти крутий фітнес-наставник і дієтолог. Відповідай коротко, підтримуй користувача, українською мовою."]}]
    for msg in req.history[-5:]:
        role = "user" if msg["role"] == "user" else "model"
        messages.append({"role": role, "parts": [msg["text"]]})
    messages.append({"role": "user", "parts": [req.message]})
    
    try:
        response = model.generate_content(messages)
        return {"reply": response.text}
    except Exception as e:
        return {"reply": "Зараз я трохи завантажений аналізом страв. Спробуй написати мені через хвилинку! 💪"}
