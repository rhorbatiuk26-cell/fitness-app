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

# --- НАЛАШТУВАННЯ ---
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
    # Використовуємо найшвидшу модель для щоденних задач
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("УВАГА: GEMINI_API_KEY не знайдено!")

DB_PATH = "/app/data/database.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# --- ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблиця користувачів (налаштування норм)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        tg_id TEXT PRIMARY KEY,
                        goal TEXT, age INTEGER, height REAL, weight REAL, target_weight REAL,
                        kcal REAL, protein REAL, fat REAL, carbs REAL, sugar REAL, salt REAL
                    )''')
    
    # Таблиця історії страв
    cursor.execute('''CREATE TABLE IF NOT EXISTS food_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id TEXT, date TEXT, name TEXT,
                        kcal REAL, protein REAL, fat REAL, carbs REAL, sugar REAL, salt REAL
                    )''')
    
    # Таблиця випитої води
    cursor.execute('''CREATE TABLE IF NOT EXISTS water_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tg_id TEXT, date TEXT, amount INTEGER
                    )''')
    
    conn.commit()
    conn.close()

init_db()

# --- МОДЕЛІ ДАНИХ (Pydantic) ---
class ProfileSetup(BaseModel):
    tg_id: str
    goal: str
    age: int
    height: float
    weight: float
    target_weight: float

class ManualProfileSetup(BaseModel):
    tg_id: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    sugar: float
    salt: float

class FoodTextRequest(BaseModel):
    tg_id: str
    date: str
    text: str

class BarcodeRequest(BaseModel):
    tg_id: str
    date: str
    barcode: str

class DirectFoodRequest(BaseModel):
    tg_id: str
    date: str
    food: dict

class ChatRequest(BaseModel):
    tg_id: str
    message: str
    history: list

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def get_user_norms(tg_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT kcal, protein, fat, carbs, sugar, salt FROM users WHERE tg_id=?", (tg_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"kcal": row[0], "protein": row[1], "fat": row[2], "carbs": row[3], "sugar": row[4], "salt": row[5]}
    return None

def parse_ai_json(text: str):
    """Очищає відповідь Gemini від маркдауну та повертає словник"""
    clean_text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean_text)

# --- ЕНДПОІНТИ (API) ---

@app.get("/api/daily/{tg_id}/{date}")
async def get_daily_data(tg_id: str, date: str):
    norms = get_user_norms(tg_id)
    if not norms:
        return {"needs_setup": True}
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name, kcal, protein, fat, carbs, sugar, salt FROM food_logs WHERE tg_id=? AND date=?", (tg_id, date))
    foods = [{"id": r[0], "name": r[1], "kcal": r[2], "protein": r[3], "fat": r[4], "carbs": r[5], "sugar": r[6], "salt": r[7]} for r in cursor.fetchall()]
    
    cursor.execute("SELECT SUM(amount) FROM water_logs WHERE tg_id=? AND date=?", (tg_id, date))
    water = cursor.fetchone()[0] or 0
    
    conn.close()
    return {"needs_setup": False, "user_norms": norms, "foods": foods, "water_ml": water}

@app.post("/api/profile")
async def setup_profile_ai(req: ProfileSetup):
    # Автоматичний розрахунок за формулою Міффліна-Сан Жеора
    bmr = 10 * req.weight + 6.25 * req.height - 5 * req.age + 5  # Усереднено для чоловіків/жінок
    
    if req.goal == "Схуднення":
        kcal = bmr * 1.2 - 400
    elif req.goal == "М'язи":
        kcal = bmr * 1.55 + 300
    else:
        kcal = bmr * 1.3

    protein = (kcal * 0.3) / 4
    fat = (kcal * 0.25) / 9
    carbs = (kcal * 0.45) / 4
    sugar = 50.0
    salt = 5.0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''REPLACE INTO users (tg_id, goal, age, height, weight, target_weight, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (req.tg_id, req.goal, req.age, req.height, req.weight, req.target_weight, kcal, protein, fat, carbs, sugar, salt))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/profile/manual")
async def setup_profile_manual(req: ManualProfileSetup):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Якщо юзера немає, створюємо з пустими параметрами тіла, але з цими нормами
    cursor.execute('''INSERT INTO users (tg_id, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?)
                      ON CONFLICT(tg_id) DO UPDATE SET
                      kcal=excluded.kcal, protein=excluded.protein, fat=excluded.fat, carbs=excluded.carbs, sugar=excluded.sugar, salt=excluded.salt''',
                   (req.tg_id, req.kcal, req.protein, req.fat, req.carbs, req.sugar, req.salt))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/food/text")
async def add_food_text(req: FoodTextRequest):
    prompt = f"""
    Користувач з'їв: "{req.text}".
    Визнач калорії та БЖВ. Обов'язково вкажи приблизний вміст цукру та солі.
    Поверни ТІЛЬКИ валідний JSON у форматі:
    {{"name": "Назва страви", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "sugar": 0, "salt": 0}}
    """
    response = model.generate_content(prompt)
    data = parse_ai_json(response.text)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (req.tg_id, req.date, data['name'], data['kcal'], data['protein'], data['fat'], data['carbs'], data['sugar'], data['salt']))
    conn.commit()
    conn.close()
    return {"status": "success", "data": data}

@app.post("/api/food/photo")
async def add_food_photo(tg_id: str = Form(...), date_str: str = Form(...), file: UploadFile = File(...)):
    import PIL.Image
    import io
    
    image_data = await file.read()
    image = PIL.Image.open(io.BytesIO(image_data))
    
    prompt = """
    Проаналізуй страву на фотографії. Оціни приблизну вагу порції, калорії, БЖВ, а також вміст цукру та солі (в грамах).
    Поверни ТІЛЬКИ валідний JSON у форматі:
    {"name": "Назва страви", "kcal": 0, "protein": 0, "fat": 0, "carbs": 0, "sugar": 0, "salt": 0}
    """
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

@app.post("/api/food/barcode")
async def add_food_barcode(req: BarcodeRequest):
    """Шукає штрихкод у безкоштовній базі Open Food Facts"""
    url = f"https://world.openfoodfacts.org/api/v0/product/{req.barcode}.json"
    
    try:
        resp = requests.get(url, timeout=5).json()
        
        if resp.get("status") != 1:
            return {"status": "error", "message": "Продукт не знайдено"}

        product = resp["product"]
        # Намагаємось знайти українську або загальну назву
        name = product.get("product_name_uk") or product.get("product_name_ru") or product.get("product_name") or "Невідомий продукт"
        
        # Беремо вагу порції (якщо не вказано, рахуємо як 100г)
        serving = float(product.get("serving_quantity", 100))
        multiplier = serving / 100.0

        nutriments = product.get("nutriments", {})
        kcal = float(nutriments.get("energy-kcal_100g", 0)) * multiplier
        protein = float(nutriments.get("proteins_100g", 0)) * multiplier
        fat = float(nutriments.get("fat_100g", 0)) * multiplier
        carbs = float(nutriments.get("carbohydrates_100g", 0)) * multiplier
        sugar = float(nutriments.get("sugars_100g", 0)) * multiplier
        salt = float(nutriments.get("salt_100g", 0)) * multiplier

        final_name = f"{name} ({int(serving)}г)"

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO food_logs (tg_id, date, name, kcal, protein, fat, carbs, sugar, salt)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (req.tg_id, req.date, final_name, kcal, protein, fat, carbs, sugar, salt))
        conn.commit()
        conn.close()

        return {"status": "success", "name": final_name}

    except Exception as e:
        print(f"Помилка сканування: {e}")
        raise HTTPException(status_code=500, detail="Помилка обробки штрихкоду")

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
    # Беремо 15 останніх унікальних страв
    cursor.execute('''SELECT name, kcal, protein, fat, carbs, sugar, salt 
                      FROM food_logs WHERE tg_id=? 
                      GROUP BY name ORDER BY id DESC LIMIT 15''', (tg_id,))
    foods = [{"name": r[0], "kcal": r[1], "protein": r[2], "fat": r[3], "carbs": r[4], "sugar": r[5], "salt": r[6]} for r in cursor.fetchall()]
    conn.close()
    return foods

@app.post("/api/chat")
async def chat_with_ai(req: ChatRequest):
    # Формуємо контекст з історії
    messages = [{"role": "user", "parts": ["Ти ШІ-дієтолог. Відповідай коротко і дружньо українською мовою."]}]
    for msg in req.history[-5:]: # Беремо останні 5 повідомлень для економії
        role = "user" if msg["role"] == "user" else "model"
        messages.append({"role": role, "parts": [msg["text"]]})
    
    messages.append({"role": "user", "parts": [req.message]})
    
    try:
        response = model.generate_content(messages)
        return {"reply": response.text}
    except Exception as e:
        return {"reply": "Вибач, я зараз трохи зайнятий підрахунком калорій. Спробуй ще раз за хвилинку! 🍏"}
