"""El 'cerebro': convierte instrucciones + inventario de assets en un PLAN de edición.

Reutiliza el patrón que ya funciona en tu proyecto faceless (prompt -> JSON
validado, con reintentos ante 503/429). La diferencia es que aquí la IA NO
inventa el contenido: organiza el material que ELLA subió.

Salida: un dict con la forma que documenta plan_schema.py.
"""
import os
import json
import time

from . import config


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"El modelo no devolvió JSON:\n{text[:500]}")
    return json.loads(text[start:end + 1])


def _inventory_lines(inventory: list) -> str:
    lines = []
    for it in inventory:
        d = f"{it['duration']}s" if it.get("duration") else "sin duración (imagen)"
        res = f"{it['width']}x{it['height']}" if it.get("width") else "?"
        lines.append(f"- {it['file']} · {it['kind']} · {d} · {res}")
    return "\n".join(lines) if lines else "(no hay archivos)"


def build_plan(instrucciones: str, inventory: list,
               modo_voz: str = "tts", voz_tts: str = None,
               max_retries: int = 4) -> dict:
    """
    instrucciones: lo que ella escribió (duración, orden, textos, tono).
    inventory: salida de inventory.build_inventory (assets reales disponibles).
    modo_voz: "voz_subida" | "tts" | "solo_musica" | "ninguno".
    """
    # Import perezoso: si google-genai tuviera problemas, la app igual carga y el
    # error solo aparece aquí (al generar), no al importar todo el proyecto.
    from google import genai
    from google.genai import types, errors

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    voz_tts = voz_tts or config.TTS_VOICE

    archivos = _inventory_lines(inventory)
    nombres_validos = [it["file"] for it in inventory]

    prompt = f"""Eres editor de video de reels verticales (9:16) en español de México.
Tu trabajo es ORGANIZAR el material que la usuaria ya subió, siguiendo sus
instrucciones. NO inventes archivos: solo puedes usar EXACTAMENTE estos nombres:
{archivos}

Instrucciones de la usuaria:
\"\"\"{instrucciones.strip()}\"\"\"

Modo de audio elegido: {modo_voz}
- "voz_subida": ella subió su narración (un archivo de audio de la lista).
- "tts": genera un guion y se narrará con voz IA ({voz_tts}).
- "solo_musica": sin narración, solo música de fondo.
- "ninguno": sin audio.

Devuelve SOLO un objeto JSON válido (sin markdown ni texto extra) con esta forma:
{{
  "duracion_total": <número de segundos, 15 a 60>,
  "audio": {{
    "tipo": "{modo_voz}",
    "archivo": "<nombre del audio de voz de la lista, o null>",
    "guion": "<si tipo=tts: guion corto 60-110 palabras para narrar; si no: null>",
    "voz_tts": "{voz_tts}"
  }},
  "musica": {{ "archivo": "<nombre de un audio de música de la lista, o null>", "volumen": 0.18 }},
  "subtitulos": {{ "activo": true, "fuente": "auto" }},
  "segmentos": [
    {{
      "asset": "<nombre EXACTO de una imagen o video de la lista>",
      "inicio": <para VIDEOS: segundo del clip donde empezar a tomar, para quedarte con lo relevante; para imágenes: 0>,
      "dur": <segundos que dura este segmento>,
      "efecto": "kenburns" | "none",
      "texto": "<texto corto para mostrar encima, o null>",
      "transicion": "fade" | "none"
    }}
  ]
}}

Reglas:
- Usa SOLO nombres de esta lista: {nombres_validos}
- La suma de los "dur" de los segmentos debe acercarse a "duracion_total".
- DURACIÓN: no hagas cortes demasiado breves. Ajusta la duración del reel al
  MATERIAL y a lo que pida la usuaria: si tiene grabaciones largas y quiere un
  reel largo, puede durar desde 20 s hasta ~5 minutos. Toma trozos generosos
  (varios segundos cada uno) para que se aprecie el contenido.
- "inicio": para cada VIDEO elige el segundo donde empieza lo más representativo
  (evita el arranque si suele ser preparación o cámara temblorosa); nunca pongas
  inicio + dur más allá de la duración real del clip. Para imágenes, inicio = 0.
- CORTAR/ADAPTAR: un mismo video largo puedes trocearlo en VARIOS segmentos con
  distinto "inicio" y "dur" para usar solo los momentos que se piden, o recorrerlo
  en orden. Usa lo que la usuaria pida (p. ej. "solo la parte del final").
- Para imágenes usa efecto "kenburns" (zoom lento); para videos, "none".
- "texto" breve (máx. 8 palabras), tipo rótulo; no en todos los segmentos.
- Respeta el orden y las ideas que pidió la usuaria."""

    last = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                ),
            )
            return _extract_json(resp.text)
        except errors.APIError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            last = e
            if code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = 6 * (attempt + 1)
                print(f"Gemini {code} (saturado). Reintento en {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise last
