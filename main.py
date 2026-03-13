import os
import logging
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Налаштування логів, щоб бачити помилки в консолі Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- БАЗА ДАНИХ (PostgreSQL) ---
DATABASE_URL = os.environ.get("DATABASE_URL")

# ВАЖЛИВО: Виправляємо postgres:// на postgresql:// для SQLAlchemy
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
    logger.info("✅ База даних успішно ініціалізована")
except Exception as e:
    logger.error(f"❌ Помилка підключення до бази: {e}")

# Опис таблиці в базі
class FoodLog(Base):
    __tablename__ = "food_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String)
    food_info = Column(Text)
    calories = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

# Створюємо таблиці, якщо їх немає
Base.metadata.create_all(bind=engine)

# --- ШТУЧНИЙ ІНТЕЛЕКТ (Gemini) ---
GEMINI_KEY = os.environ.get("GEMINI_KEY")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- СЕРВЕР ---
app = FastAPI()

# Дозволяємо доступ з твого Mini App
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Функція для отримання сесії бази
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def health():
    return {"status": "v31.0 System Online", "database": "Connected"}

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        
        prompt = """
        Ти дієтолог. Проаналізуй фото страви українською мовою. 
        Дай відповідь ТІЛЬКИ у такому форматі:
        Назва: [назва]
        Вага: [вага]
        Калорії: [число]
        БЖВ: [білки/жири/вуглеводи]
        ---
        В кінці напиши число калорій після знаку #. Наприклад: #250
        """
        
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        full_text = response.text
        
        # Витягуємо калорії
        kcal = 0
        if "#" in full_text:
            try:
                kcal_str = full_text.split("#")[-1].strip().split()[0]
                kcal = int(''.join(filter(str.isdigit, kcal_str)))
            except:
                kcal = 0

        # Зберігаємо запис
        clean_info = full_text.split("#")[0].strip()
        new_log = FoodLog(user_id=str(user_id), food_info=clean_info, calories=kcal)
        db.add(new_log)
        db.commit()
        
        return {"result": clean_info, "kcal": kcal}
    except Exception as e:
        logger.error(f"Помилка аналізу: {e}")
        return {"result": f"Помилка: {str(e)}", "kcal": 0}

@app.get("/stats")
async def get_stats(user_id: str, db: Session = Depends(get_db)):
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        logs = db.query(FoodLog).filter(
            FoodLog.user_id == str(user_id), 
            FoodLog.created_at >= today_start
        ).all()
        
        total = sum(log.calories for log in logs)
        history = [{"info": log.food_info, "kcal": log.calories} for log in logs]
        
        return {"total": total, "history": history}
    except Exception as e:
        logger.error(f"Помилка статистики: {e}")
        return {"total": 0, "history": []}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
