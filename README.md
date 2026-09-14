# reel-studio 🎬

App web para armar reels verticales a partir de tu **propio material** (fotos,
clips, voz, música), sin saber editar. Subes, describes lo que quieres, la IA
propone un plan de edición, lo ajustas, apruebas y descargas.

## Cómo funciona (4 pasos para la usuaria)
1. **Sube** fotos/clips y, si quieres, tu voz y tu música.
2. **Describe** el reel que quieres (duración, orden, textos, tono).
3. La IA propone un **plan** → lo revisas y ajustas en una tabla.
4. **Aprobar** → se arma el reel → lo ves y lo **descargas**.

## Requisitos
- Python 3.12
- FFmpeg en el PATH (`ffmpeg` y `ffprobe`)
- Una **API key de Gemini** (gratis; ver abajo)

## Correr en local
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# FFmpeg:  Linux: sudo apt-get install -y ffmpeg fonts-dejavu-core
#          Windows: winget install -e --id Gyan.FFmpeg
cp .env.example .env                 # pega tu GEMINI_API_KEY
export $(grep -v '^#' .env | xargs)  # cargar variables (Linux/Mac)
streamlit run app.py
```
Abre http://localhost:8501

## Conseguir la API key de Gemini (gratis, sin tarjeta)
1. Entra a **https://aistudio.google.com/apikey** con tu cuenta Google.
2. **Create API key** → copia la clave (empieza con `AIza…`).
3. Ponla en `.env` como `GEMINI_API_KEY=...` (o como secret en el hosting).
El tier gratis cubre los modelos **Flash** (este proyecto usa `gemini-3.6-flash`).

## Variables de entorno principales
| Variable | Para qué | Default |
|---|---|---|
| `GEMINI_API_KEY` | El cerebro (arma el plan) | — (obligatoria) |
| `GEMINI_MODEL` | Modelo | `gemini-3.6-flash` |
| `TTS_VOICE` | Voz IA | `es-MX-DaliaNeural` |
| `WATERMARK_TEXT` | Marca de agua | vacío |
| `STORAGE_BACKEND` | `local` o `gcs` | `local` |
| `GCS_BUCKET` | Bucket (si gcs) | — |

## Despliegue

### Opción A — Streamlit Community Cloud (gratis, para empezar)
1. Sube el repo a GitHub.
2. En https://share.streamlit.io conecta el repo y elige `app.py`.
3. En *Secrets* agrega `GEMINI_API_KEY`.
Ideal para validar el flujo con clips cortos.

### Opción B — Google Cloud Run (producción, escala a cero)
```bash
# 1) Bucket para persistencia (los uploads/outputs)
gcloud storage buckets create gs://reel-studio-media --location=us-central1

# 2) Deploy directo desde el código (usa el Dockerfile)
gcloud run deploy reel-studio \
  --source . \
  --region us-central1 \
  --cpu 2 --memory 4Gi \
  --min-instances 0 --max-instances 3 \
  --concurrency 4 --timeout 900 \
  --session-affinity \
  --set-env-vars STORAGE_BACKEND=gcs,GCS_BUCKET=reel-studio-media \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest \
  --no-allow-unauthenticated
```
- `--session-affinity` es **obligatorio** (Streamlit usa websockets y el estado
  vive en la instancia).
- `--min-instances 0` = **escala a cero** = ~$0 cuando nadie lo usa.
- `--no-allow-unauthenticated` = privado; da acceso solo a su cuenta Google (ver
  sección de seguridad en la conversación).
- La API key va como **secret** (Secret Manager), no como env plano.

## Notas
- El disco de Cloud Run NO sobrevive al escalar a cero: por eso los uploads y el
  reel final van a **GCS** (`STORAGE_BACKEND=gcs`). El trabajo temporal de FFmpeg
  sí es local (/tmp), y está bien.
- La versión de los modelos Gemini cambia; si `gemini-3.6-flash` deja de estar en
  el tier gratis, cambia `GEMINI_MODEL` por el Flash vigente.
