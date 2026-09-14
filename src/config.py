"""Configuración central de reel-studio.

Todo lo ajustable vive aquí y se lee de variables de entorno, para que
funcione igual en local (con .env) que en Cloud Run (con secrets/vars).
"""
import os

# --- Formato de salida ---
WIDTH = int(os.environ.get("REEL_WIDTH", "1080"))
HEIGHT = int(os.environ.get("REEL_HEIGHT", "1920"))
FPS = int(os.environ.get("REEL_FPS", "30"))

# --- IA (el "cerebro" que arma el plan) ---
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# --- Voz IA (edge-tts, gratis, sin key) ---
TTS_VOICE = os.environ.get("TTS_VOICE", "es-MX-DaliaNeural")

# --- Marca ---
WATERMARK = os.environ.get("WATERMARK_TEXT", "")  # p. ej. "@su_canal"

# --- Almacenamiento ---
# STORAGE_BACKEND: "local" (default) o "gcs".
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
GCS_BUCKET = os.environ.get("GCS_BUCKET", "").strip()
LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", "data")

# --- Límites de subida (para el UI) ---
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))

# --- Fuente para textos quemados ---
FONT_CANDIDATES = [
    os.environ.get("FONT_FILE", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def font_file() -> str:
    for p in FONT_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return ""  # drawtext usará su fuente por defecto si queda vacío
