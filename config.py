import os
from dotenv import load_dotenv

load_dotenv()

# Embeddings (semantic menu search) use MISTRAL_API_KEY; required for that
# feature but search degrades to keyword-only if it's missing.
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

# Legacy / fallback-path keys — NOT used by the active Gemini Live pipeline.
# Optional so deployments don't need to provide keys they'll never use.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
VOICE_ID = os.environ.get("VOICE_ID", "")

# Gemini Live Native Audio — the active voice engine (STT + LLM + TTS in one).
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "models/gemini-3.1-flash-live-preview"
)
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Charon")

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# Semantic menu search (pgvector + Mistral embeddings). mistral-embed is
# 1024-dimensional. Embeddings degrade gracefully — if the API key/model is
# missing or a call fails, search falls back to keyword matching.
MISTRAL_EMBED_MODEL = os.environ.get("MISTRAL_EMBED_MODEL", "mistral-embed")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

# Image upload (Cloudinary). When unset, the admin image-upload endpoint is
# disabled and admins can still paste an image URL directly.
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")

# Hard cap on a single voice call (seconds). Protects against runaway/abusive
# sessions holding a WebSocket (and CPU) open indefinitely. Default 15 minutes.
MAX_SESSION_SECONDS = int(os.environ.get("MAX_SESSION_SECONDS", "900"))

# Per-IP cooldown between voice calls (seconds). 0 disables the cooldown — but a
# single active call per IP is always enforced. Keeps one visitor from hogging
# the shared demo CPU. Set to 0 locally while developing.
SESSION_COOLDOWN_SECONDS = int(os.environ.get("SESSION_COOLDOWN_SECONDS", "60"))

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
