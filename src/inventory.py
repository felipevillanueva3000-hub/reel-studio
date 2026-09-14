"""Inspecciona cada archivo subido con ffprobe.

Le da al 'cerebro' (Gemini) un inventario honesto de lo que hay: qué es cada
archivo, cuánto dura un clip, si un audio es voz o música, etc. Sin esto la IA
inventaría planes con assets que no existen o duraciones imposibles.
"""
import os
import json
import subprocess

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")

FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")


def _probe(path: str) -> dict:
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, check=True,
        )
        return json.loads(out.stdout)
    except Exception:
        return {}


def _kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return "other"


def describe(path: str) -> dict:
    """Devuelve un dict con lo esencial de un archivo."""
    kind = _kind(path)
    info = {"file": os.path.basename(path), "path": path, "kind": kind,
            "duration": None, "width": None, "height": None}
    data = _probe(path)
    fmt = data.get("format", {})
    if fmt.get("duration"):
        try:
            info["duration"] = round(float(fmt["duration"]), 2)
        except ValueError:
            pass
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"] = s.get("width")
            info["height"] = s.get("height")
    # Una imagen no tiene duración real; ffprobe a veces reporta 0.04s.
    if kind == "image":
        info["duration"] = None
    return info


def build_inventory(paths: list) -> list:
    """Lista de dicts, uno por archivo, lista para pasársela a la IA."""
    return [describe(p) for p in paths]
