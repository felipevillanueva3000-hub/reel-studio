"""Publicación OPCIONAL a YouTube como Short (reutiliza tu flujo ya probado).

No se activa por defecto: en el MVP el resultado se descarga. Cuando quieras que
suba sola, importa upload_short() desde app.py detrás de un botón, con estos
secretos configurados: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.

Sube un archivo LOCAL (ya lo tenemos en disco tras el render), sin dependencias
de google-*, solo requests.
"""
import os
import json
import time

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")


def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Falta el secreto {name}.")
    return v


def _access_token() -> str:
    data = {"client_id": _require("YT_CLIENT_ID"),
            "client_secret": _require("YT_CLIENT_SECRET"),
            "refresh_token": _require("YT_REFRESH_TOKEN"),
            "grant_type": "refresh_token"}
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Token YouTube {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def upload_short(video_path: str, title: str, description: str = "",
                 tags=None, privacy: str = None) -> str:
    """Sube un mp4 local como Short. Devuelve el video_id (URL: youtu.be/<id>)."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    privacy = (privacy or os.environ.get("YT_PRIVACY", "private")).lower()
    token = _access_token()
    size = os.path.getsize(video_path)

    desc = (description or "").strip()
    if "#shorts" not in desc.lower():
        desc = (desc + "\n\n#Shorts").strip()

    metadata = {
        "snippet": {"title": (title or "Reel")[:100], "description": desc[:4900],
                    "tags": tags or [], "categoryId": "22",
                    "defaultLanguage": "es-MX", "defaultAudioLanguage": "es-MX"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    init = requests.post(
        UPLOAD_URL,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/*",
                 "X-Upload-Content-Length": str(size)},
        data=json.dumps(metadata).encode("utf-8"), timeout=60,
    )
    if init.status_code not in (200, 201):
        raise RuntimeError(f"YouTube init {init.status_code}: {init.text[:300]}")
    session_url = init.headers["Location"]

    with open(video_path, "rb") as f:
        put = requests.put(session_url,
                           headers={"Content-Type": "video/*",
                                    "Content-Length": str(size)},
                           data=f.read(), timeout=600)
    if put.status_code not in (200, 201):
        raise RuntimeError(f"YouTube upload {put.status_code}: {put.text[:300]}")
    return put.json()["id"]
