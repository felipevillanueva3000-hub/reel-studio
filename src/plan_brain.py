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
from . import inventory as inv_mod


class QuotaExhausted(Exception):
    """Se agotó la cuota gratis (429/RESOURCE_EXHAUSTED) del modelo actual."""

    def __init__(self, model_id: str = ""):
        self.model_id = model_id
        super().__init__(f"Cuota agotada para el modelo {model_id}.")


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
               tono: str = "", model: str = None, max_retries: int = 4) -> dict:
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

    prompt = f"""Eres un editor PROFESIONAL de reels verticales (9:16) en español de México.
Tu trabajo es ORGANIZAR el material que la usuaria ya subió y armar un reel con
narrativa clara. NO inventes archivos: solo puedes usar EXACTAMENTE estos nombres:
{archivos}

MUY IMPORTANTE: después de estas instrucciones te muestro FOTOGRAMAS de cada clip.
Míralos con atención para entender QUÉ se ve en cada uno (lugar, calle, letreros,
personas, ambiente) y así ordenarlos con lógica y captar la esencia.

Instrucciones de la usuaria:
\"\"\"{instrucciones.strip()}\"\"\"

TONO / ESTILO deseado: {tono or "natural y auténtico, como contar una experiencia vivida (fuimos, vimos, nos gustó); NO promocional"}
Escribe el guion y los rótulos con ESE tono.

Modo de audio elegido: {modo_voz}
- "voz_subida": ella subió su narración (un archivo de audio de la lista).
- "tts": genera un guion y se narrará con voz IA ({voz_tts}).
- "solo_musica": sin narración, solo música de fondo.
- "ninguno": sin audio.

Devuelve SOLO un objeto JSON válido (sin markdown ni texto extra) con esta forma:
{{
  "duracion_total": <segundos totales, 15 a 300 según el material y lo pedido>,
  "audio": {{
    "tipo": "{modo_voz}",
    "archivo": "<nombre del audio de voz de la lista, o null>",
    "guion": "<si tipo=tts: guion 60-160 palabras, coherente con lo que se ve; si no: null>",
    "voz_tts": "{voz_tts}"
  }},
  "musica": {{ "archivo": "<nombre de un audio de música de la lista, o null>", "volumen": 0.18 }},
  "subtitulos": {{ "activo": true, "fuente": "auto" }},
  "segmentos": [
    {{
      "asset": "<nombre EXACTO de una imagen o video de la lista>",
      "inicio": <para VIDEOS: segundo donde empezar a tomar lo relevante; imágenes: 0>,
      "dur": <segundos de este segmento>,
      "efecto": "kenburns" | "none",
      "texto": "<rótulo MUY corto, máx 4 palabras, o null>",
      "transicion": "fade" | "none"
    }}
  ]
}}

Reglas de un buen reel:
- Usa SOLO estos nombres: {nombres_validos}
- ORDEN CON SENTIDO (no al azar): empieza UBICANDO (el lugar, la calle o la
  entrada), luego desarrolla el ambiente y lo interesante, y cierra con un buen
  final. Decide el orden por lo que VES en los fotogramas.
- ESENCIA: guion y rótulos deben describir lo que de verdad se ve. Si en un letrero
  se lee una calle o el nombre del lugar, aprovéchalo al inicio ("Llegas por...").
- DURACIÓN: ajústala al material y a lo pedido (de 20 s hasta ~5 min si hay
  grabaciones largas). Trozos generosos, nada de cortes de 1-2 s.
- "inicio": para cada VIDEO empieza en la parte buena (evita arranques
  temblorosos); inicio + dur nunca más allá de la duración real del clip.
- CORTAR/ADAPTAR: un video largo puedes trocearlo en varios segmentos con distinto
  "inicio"/"dur" para usar solo lo mejor.
- ROTULOS: MUY cortos (máx 4 palabras) para que quepan; no en todos los segmentos.
- CIERRE: el último segmento debe sentirse como un FINAL acorde al tono (una
  conclusión), no un corte seco. Si hay guion, termínalo con una frase de cierre
  (p. ej. en experiencia: "una visita que sin duda vale la pena").
- Para imágenes usa efecto "kenburns"; para videos "none"."""

    # Multimodal: adjuntamos fotogramas de cada clip para que el modelo VEA el
    # contenido. Si la extracción falla, sigue funcionando con solo texto.
    contents = [prompt]
    for it in inventory:
        frames = inv_mod.sample_frames(it) if it.get("kind") in ("image", "video") else []
        if frames:
            d = f"{it.get('duration')}s" if it.get("duration") else "imagen"
            contents.append(f"FOTOGRAMAS de «{it['file']}» ({it['kind']}, {d}):")
            for fb in frames:
                contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))

    model_id = model or config.GEMINI_MODEL
    last = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                ),
            )
            return _extract_json(resp.text)
        except errors.APIError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            last = e
            if code == 429:
                # 429 = cuota/límite agotado. Un reintento corto por si fuera un
                # límite POR MINUTO; si sigue, es cuota agotada -> avisamos claro.
                if attempt == 0:
                    time.sleep(8)
                    continue
                raise QuotaExhausted(model_id)
            if code in (500, 502, 503) and attempt < max_retries - 1:
                wait = 6 * (attempt + 1)
                print(f"Gemini {code} (saturado). Reintento en {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise last
    raise last