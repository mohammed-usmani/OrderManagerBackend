import os
from dotenv import load_dotenv

load_dotenv()

# Embeddings (semantic menu search) use MISTRAL_API_KEY; required for that
# feature but search degrades to keyword-only if it's missing.
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

# Gemini Live Native Audio — the active voice engine (STT + LLM + TTS in one).
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL", "models/gemini-3.1-flash-live-preview"
)
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Charon")

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# Razorpay (TEST mode for this project). Empty when unset → online payments are
# disabled and the UI falls back to cash only.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

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

# GLOBAL cap on simultaneous voice calls across ALL users — this is the real
# bottleneck: the Gemini free tier allows ~3 concurrent Live sessions. Anyone
# arriving when all slots are full is turned away with a "lines busy" message,
# and the client auto-retries until a slot frees up (a simple queue). A returning
# user gets straight in whenever a slot is free — no per-user blocking.
MAX_CONCURRENT_CALLS = int(os.environ.get("MAX_CONCURRENT_CALLS", "3"))

JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

# Seed menu, admin, service areas and floor plan on startup (first run fills
# empty tables only). Set to "false" once a deployment is set up.
SEED_ON_STARTUP = os.environ.get("SEED_ON_STARTUP", "true").lower() != "false"

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

# Restaurant bill policy. Charges are quoted by the agent and displayed on every
# cart/order card sent to the frontend. Keep in sync with the "Restaurant
# Policies" section of agent/brain.py.
#
# Context-aware charge policy. Each charge declares WHEN it applies:
#   applies_to: "all" | "dine_in" | "parcel"
#   ac_only:    True  -> only for dine-in orders seated in an AC zone
# Order is the display order on the bill. Parcel bills stay exactly as before
# (service + GST); dine-in in an AC zone additionally gets the AC charge.
CHARGE_POLICY: list[dict] = [
    {"key": "service", "label": "Service charge (10%)", "rate": 0.10, "applies_to": "all"},
    {"key": "ac",      "label": "AC charge (5%)",       "rate": 0.05, "applies_to": "dine_in", "ac_only": True},
    {"key": "gst",     "label": "GST (5%)",             "rate": 0.05, "applies_to": "all"},
]
