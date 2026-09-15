"""Comprueba la API key de Gemini de forma aislada.

Uso:  python check_key.py

Lee la key de .env (o de la variable de entorno) y hace UNA llamada mínima a
Gemini. Sirve para separar "¿la key sirve?" de "¿la app funciona?".
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Aviso: instala python-dotenv para leer .env automáticamente "
          "(pip install python-dotenv).")

key = os.environ.get("GEMINI_API_KEY", "").strip()
model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

if not key:
    print("❌ No se encontró GEMINI_API_KEY.")
    print("   Revisa que exista un archivo .env en esta carpeta con la línea:")
    print("   GEMINI_API_KEY=tu-clave")
    raise SystemExit(1)

print(f"🔑 Key detectada: {key[:6]}…{key[-4:]} (largo {len(key)}) · modelo: {model}")

try:
    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=model, contents="Responde solo: OK")
    print(f"✅ Gemini respondió: {(resp.text or '').strip()[:60]}")
    print("   La API key funciona. Ya puedes usar la app.")
except Exception as e:
    print(f"❌ La llamada a Gemini falló: {e}")
    print("   Posibles causas: key inválida/rotada, o el modelo no está en tu")
    print("   tier (usa un modelo Flash, p. ej. gemini-3.6-flash).")
    raise SystemExit(1)
