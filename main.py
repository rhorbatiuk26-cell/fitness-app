import os, json, logging
from datetime import datetime
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Логи
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB SETUP
DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class FoodLog(Base):
    __tablename__ = "food_v49"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    food_name = Column(String)
    calories = Column(Integer)
    sugar = Column(Float, default=0) # Нове
    salt = Column(Float, default=0) # Нове
    created_at = Column(DateTime, default=datetime.utcnow)

class WaterLog(Base):
    __tablename__ = "water_v49"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# AI SETUP
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.post("/analyze")
async def analyze(user_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        img_data = await file.read()
        # Оновлений промпт для ШІ
        prompt = "Аналіз їжі. Поверни ТІЛЬКИ чистий JSON: {\"name\": \"...\", \"kcal\": 0, \"sugar\": 0.0, \"salt\": 0.0}"
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        
        txt = response.text
        data = json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        
        db.add(FoodLog(
            user_id=str(user_id), food_name=data['name'], 
            calories=data['kcal'], sugar=data['sugar'], salt=data['salt']))
        db.commit()
        return data
    except Exception as e:
        return {"error": str(e)}

# (Маршрути add_water, chat, stats - залишаються як у v48)
