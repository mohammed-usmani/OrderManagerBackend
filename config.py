import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
MISTRAL_API_KEY = os.environ["MISTRAL_API_KEY"]
NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]
VOICE_ID = os.environ["VOICE_ID"]