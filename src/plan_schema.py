"""Valida y normaliza el plan que devolvió la IA antes de renderizar.

La IA se equivoca a veces (nombra un archivo que no existe, pone duraciones
raras). Aquí lo dejamos SIEMPRE renderizable, o damos un error claro. También
es lo que respalda el "modo aprobación": la app muestra este plan ya saneado y
ella lo edita.
"""
from . import inventory as inv

EFECTOS = ("kenburns", "none")
TRANSICIONES = ("fade", "none")
MODOS_AUDIO = ("voz_subida", "tts", "solo_musica", "ninguno")


class PlanError(ValueError):
    pass


def _index(inventory: list) -> dict:
    return {it["file"]: it for it in inventory}


def normalize(plan: dict, inventory: list) -> dict:
    idx = _index(inventory)
    if not isinstance(plan, dict):
        raise PlanError("El plan no es un objeto JSON.")

    # --- Segmentos ---
    segs_in = plan.get("segmentos") or []
    segs = []
    for s in segs_in:
        asset = (s.get("asset") or "").strip()
        if asset not in idx:
            continue  # descarta segmentos que apuntan a archivos inexistentes
        kind = idx[asset]["kind"]
        if kind not in ("image", "video"):
            continue
        dur = s.get("dur", 4)
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = 4.0
        dur = max(1.0, min(dur, 20.0))
        # Si es video más corto que 'dur', ajusta a su duración real.
        real = idx[asset].get("duration")
        if kind == "video" and real:
            dur = min(dur, float(real))
        efecto = s.get("efecto") if s.get("efecto") in EFECTOS else (
            "kenburns" if kind == "image" else "none")
        trans = s.get("transicion") if s.get("transicion") in TRANSICIONES else "none"
        texto = (s.get("texto") or "").strip() or None
        segs.append({"asset": asset, "path": idx[asset]["path"], "kind": kind,
                     "dur": round(dur, 2), "efecto": efecto,
                     "transicion": trans, "texto": texto})

    if not segs:
        raise PlanError("El plan no tiene segmentos válidos (¿los archivos "
                        "existen y son imagen o video?).")

    # --- Audio ---
    audio = plan.get("audio") or {}
    tipo = audio.get("tipo") if audio.get("tipo") in MODOS_AUDIO else "ninguno"
    a_file = (audio.get("archivo") or "").strip()
    if a_file and (a_file not in idx or idx[a_file]["kind"] != "audio"):
        a_file = ""  # nombre de audio inválido
    if tipo == "voz_subida" and not a_file:
        tipo = "ninguno"  # pidió voz subida pero no hay audio válido
    audio_norm = {"tipo": tipo, "archivo": a_file or None,
                  "path": idx[a_file]["path"] if a_file else None,
                  "guion": (audio.get("guion") or "").strip() or None,
                  "voz_tts": (audio.get("voz_tts") or "").strip() or None}

    # --- Música ---
    musica = plan.get("musica") or {}
    m_file = (musica.get("archivo") or "").strip()
    if m_file and (m_file not in idx or idx[m_file]["kind"] != "audio"):
        m_file = ""
    # que la música no sea el mismo archivo que la voz
    if m_file and m_file == a_file:
        m_file = ""
    try:
        vol = float(musica.get("volumen", 0.18))
    except (TypeError, ValueError):
        vol = 0.18
    musica_norm = {"archivo": m_file or None,
                   "path": idx[m_file]["path"] if m_file else None,
                   "volumen": max(0.0, min(vol, 1.0))}

    # --- Subtítulos ---
    subs = plan.get("subtitulos") or {}
    subs_norm = {"activo": bool(subs.get("activo", False)),
                 "fuente": subs.get("fuente") or "auto"}
    # Sin narración no hay de dónde sacar subtítulos automáticos.
    if tipo in ("solo_musica", "ninguno"):
        subs_norm["activo"] = False

    total = sum(s["dur"] for s in segs)
    return {"duracion_total": round(total, 2),
            "audio": audio_norm, "musica": musica_norm,
            "subtitulos": subs_norm, "segmentos": segs}


def resumen_legible(plan: dict) -> str:
    """Texto amigable del plan, para mostrarlo en la app (no JSON crudo)."""
    lines = [f"Duración total: ~{plan['duracion_total']}s",
             f"Audio: {plan['audio']['tipo']}"]
    if plan["musica"]["archivo"]:
        lines.append(f"Música: {plan['musica']['archivo']} (vol {plan['musica']['volumen']})")
    lines.append(f"Subtítulos: {'sí' if plan['subtitulos']['activo'] else 'no'}")
    lines.append("Segmentos:")
    for i, s in enumerate(plan["segmentos"], 1):
        t = f' · texto: "{s["texto"]}"' if s["texto"] else ""
        lines.append(f"  {i}. {s['asset']} ({s['kind']}) · {s['dur']}s · {s['efecto']}{t}")
    return "\n".join(lines)
