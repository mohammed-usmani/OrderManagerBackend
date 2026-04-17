import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
MISTRAL_API_KEY = os.environ["MISTRAL_API_KEY"]
NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]
VOICE_ID = os.environ["VOICE_ID"]

# Gemini Live Native Audio (feature branch)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "models/gemini-3.1-flash-live-preview"
)
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Charon")

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

# Restaurant bill policy. Service charge + GST are quoted by the agent and
# displayed on every cart/order card sent to the frontend. Keep in sync with
# the "Restaurant Policies" section of agent/brain.py.
BILL_CHARGES: list[dict] = [
    {"label": "Service charge (10%)", "rate": 0.10},
    {"label": "GST (5%)", "rate": 0.05},
]
