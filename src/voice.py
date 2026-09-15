"""Voz IA con edge-tts (gratis, sin API key).

Solo se usa cuando el modo de audio es "tts". Si ella sube su propia voz, este
módulo no se toca. Devuelve, además del mp3, los 'word boundaries' (tiempos por
palabra) para poder generar subtítulos perfectamente sincronizados.
"""
import asyncio

from . import config


async def _synth(text: str, out_path: str, voice: str):
    import edge_tts
    boundaries = []
    communicate = edge_tts.Communicate(text, voice)
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append((chunk["offset"], chunk["duration"], chunk["text"]))
    return boundaries


def synthesize(text: str, out_path: str, voice: str = None):
    """Genera el mp3 y devuelve [(offset_100ns, dur_100ns, palabra), ...]."""
    return asyncio.run(_synth(text, out_path, voice or config.TTS_VOICE))
