import os, json, time
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- DATABASE ---
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "production_food_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    protein = Column(Integer)
    fat = Column(Integer)
    carbs = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "production_water_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- AI PRODUCTION CONFIG ---
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
# Використовуємо конкретну стабільну версію
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# Функція безпечного запиту до ШІ з повторами
def safe_generate(content, retries=3):
    for i in range(retries):
        try:
            response = model.generate_content(content)
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"Retry {i+1} failed: {e}")
            time.sleep(1) # пауза перед повтором
    return None

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        prompt = "Аналіз їжі. Поверни ТІЛЬКИ JSON: {\"name\": \"назва\", \"kcal\": 200, \"p\": 10, \"f\": 5, \"c\": 20}"
        
        contents = [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": img_data}}]}]
        
        raw_res = safe_generate(contents)
        if not raw_res: raise Exception("AI Timeout")

        # Чистий парсинг JSON
        clean_json = raw_res[raw_res.find("{"):raw_res.rfind("}")+1]
        data = json.loads(clean_json)
        
        new_food = FoodLog(
            user_id=str(user_id), food_name=data.get('name', 'Їжа'),
            calories=int(data.get('kcal', 0)), protein=int(data.get('p', 0)),
            fat=int(data.get('f', 0)), carbs=int(data.get('c', 0))
        )
        db.add(new_food)
        db.commit()
        return data
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat")
async def chat(user_id: str, message: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
    kcal = sum(f.calories for f in food)
    
    prompt = f"Ти тренер. Юзер з'їв {kcal} ккал. Питання: {message}. Відповідай коротко."
    reply = safe_generate(prompt)
    
    return {"reply": reply or "Вибачте, сервіс перевантажений. Спробуйте ще раз за мить."}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    food = db.query(FoodLog).filter(FoodLog.user_id == str(user_id), FoodLog.created_at >= today).all()
    water = db.query(WaterLog).filter(WaterLog.user_id == str(user_id), WaterLog.created_at >= today).all()
    return {
        "kcal": sum(f.calories for f in food) or 0,
        "p": sum(f.protein for f in food) or 0,
        "f": sum(f.fat for f in food) or 0,
        "c": sum(f.carbs for f in food) or 0,
        "water": round(sum(w.amount for w in water), 2) or 0.0
    }

@app.post("/add_water")
async def add_water(user_id: str, amount: float, db: Session = Depends(get_db)):
    db.add(WaterLog(user_id=str(user_id), amount=amount))
    db.commit()
    return {"status": "ok"}
