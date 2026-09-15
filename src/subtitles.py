"""Genera subtítulos .ass estilizados.

Dos caminos, según de dónde salga la voz:
- Voz IA (tts): edge-tts nos dio los tiempos por palabra -> sync exacto.
- Voz subida por ella: no hay tiempos. v1 reparte el texto por la duración real
  del audio (medida con ffprobe). Para sync palabra-por-palabra de su voz, más
  adelante se enchufa faster-whisper aquí (ver transcribe()).
"""
import os
import subprocess

from . import config

FONT = os.environ.get("SUB_FONT", "DejaVu Sans")


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _header(font: str) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.WIDTH}
PlayResY: {config.HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,120,120,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _audio_duration(audio_path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", audio_path],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 30.0


def _cues_from_boundaries(boundaries, wpc):
    cues = []
    for i in range(0, len(boundaries), wpc):
        g = boundaries[i:i + wpc]
        if not g:
            continue
        start = g[0][0] / 1e7
        end = (g[-1][0] + g[-1][1]) / 1e7
        cues.append((start, end, " ".join(w[2] for w in g)))
    return cues


def _cues_from_text(text, duration, wpc):
    words = text.split()
    groups = [words[i:i + wpc] for i in range(0, len(words), wpc)]
    total = sum(len(" ".join(g)) for g in groups) or 1
    cues, t = [], 0.0
    for g in groups:
        span = duration * (len(" ".join(g)) / total)
        cues.append((t, t + span, " ".join(g)))
        t += span
    return cues


def build_ass(ass_path: str, text: str = "", boundaries=None,
              audio_path: str = None, words_per_cue: int = 3):
    """Escribe el .ass. Da prioridad a boundaries (sync exacto)."""
    if boundaries:
        cues = _cues_from_boundaries(boundaries, words_per_cue)
    elif text and audio_path:
        cues = _cues_from_text(text, _audio_duration(audio_path), words_per_cue)
    else:
        cues = []

    lines = [_header(FONT)]
    for start, end, txt in cues:
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{txt.upper()}"
        )
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return ass_path


def transcribe(audio_path: str):
    """Punto de extensión: transcribir la voz SUBIDA por ella con timestamps.

    v1 devuelve None (se usa el reparto por duración). Para activar sync exacto
    de su propia voz, instala faster-whisper y devuelve una lista de
    (inicio_seg, fin_seg, texto). No lo activamos aún para no cargar el MVP.
    """
    return None