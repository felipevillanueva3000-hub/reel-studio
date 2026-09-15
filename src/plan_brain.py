"""Renderizador: ejecuta un PLAN validado y produce el reel .mp4 con FFmpeg.

Evolución de tu video.py: en vez de un fondo plano, arma una secuencia de
clips/fotos (con zoom lento tipo Ken Burns en las fotos), les pone rótulos,
mezcla voz + música y quema los subtítulos.

Diseño: primero normaliza CADA segmento a un mp4 idéntico (mismo códec, tamaño,
fps) en el build dir; luego los concatena con '-c copy' (rápido y sin sorpresas);
al final añade audio y subtítulos en un solo paso. Así es fácil de depurar.
"""
import os
import subprocess

from . import config

W, H, FPS = config.WIDTH, config.HEIGHT, config.FPS


def _run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            "FFmpeg falló:\n" + " ".join(cmd) + "\n\n" + p.stderr[-1500:]
        )
    return p


def _wrap(text: str, max_chars: int) -> list:
    """Parte el texto en líneas de <= max_chars (cortando por palabras)."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if not cur or len(cur) + 1 + len(w) <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_text(text: str, max_width_px: int = 900, max_lines: int = 3):
    """Elige el tamaño de fuente MÁS GRANDE que haga caber el texto dentro de
    max_width_px partiéndolo hasta en max_lines líneas. Devuelve (texto, fontsize).

    Así el rótulo NUNCA se desborda: si es corto va grande en una línea; si es
    largo, baja de tamaño y/o se parte en varias líneas hasta que cabe.
    """
    text = text.upper()
    # 0.60 ≈ ancho medio por carácter respecto al tamaño de fuente (DejaVu Bold).
    for fontsize in (66, 60, 54, 48, 42, 38):
        max_chars = max(6, int(max_width_px / (fontsize * 0.60)))
        lines = _wrap(text, max_chars)
        longest = max((len(l) for l in lines), default=0)
        if longest <= max_chars and len(lines) <= max_lines:
            return "\n".join(lines), fontsize
    # último recurso: fuente más chica y las líneas que hagan falta
    fontsize = 34
    max_chars = max(6, int(max_width_px / (fontsize * 0.60)))
    return "\n".join(_wrap(text, max_chars)), fontsize


def _drawtext(texto: str, build_dir: str, idx: int) -> str:
    """Escribe el texto (ya ajustado) a un archivo y devuelve el filtro drawtext."""
    wrapped, fontsize = _fit_text(texto, max_width_px=900, max_lines=3)
    txt_path = os.path.join(build_dir, f"txt_{idx}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    # La fuente se copia al build_dir y se referencia RELATIVA. Así evitamos que
    # una ruta absoluta de Windows (con ':' y '\') rompa el parser de filtros.
    fontfile = ""
    font = config.font_file()
    if font:
        dst = os.path.join(build_dir, "font.ttf")
        if not os.path.isfile(dst):
            import shutil
            shutil.copy2(font, dst)
        fontfile = "fontfile=font.ttf:"
    return (
        f"drawtext={fontfile}textfile='txt_{idx}.txt':"
        f"fontcolor=white:fontsize={fontsize}:borderw=4:bordercolor=black@0.85:"
        f"box=1:boxcolor=black@0.35:boxborderw=22:"
        f"x=(w-text_w)/2:y=h*0.72:line_spacing=12"
    )


def _fade(dur: float) -> str:
    d = 0.4
    return f"fade=t=in:st=0:d={d},fade=t=out:st={max(0.0, dur - d):.2f}:d={d}"


def _suffix(seg: dict, build_dir: str, idx: int) -> str:
    """Cola de filtros común (texto, fundido, formato) que se encadena al final."""
    parts = []
    if seg["texto"]:
        parts.append(_drawtext(seg["texto"], build_dir, idx))
    if seg["transicion"] == "fade":
        parts.append(_fade(seg["dur"]))
    parts.append("setsar=1")
    parts.append("format=yuv420p")
    return "," + ",".join(parts)


def _contain_blur(src: str) -> str:
    """Encaja el contenido COMPLETO en 9:16 sobre un fondo desenfocado.

    Nada se recorta ni se desborda: si el material es horizontal, se ve entero
    y arriba/abajo se rellena con una versión ampliada y borrosa del mismo clip.
    """
    return (
        f"[{src}]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"gblur=sigma=20[bgb];"
        f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
    )


def _render_segment(seg: dict, build_dir: str, idx: int) -> str:
    """Normaliza un segmento a build_dir/seg_{idx}.mp4 (video sin audio)."""
    out = f"seg_{idx}.mp4"
    dur = seg["dur"]
    frames = max(1, int(round(dur * FPS)))
    inicio = float(seg.get("inicio") or 0.0)
    suffix = _suffix(seg, build_dir, idx)

    if seg["kind"] == "image":
        inputs = ["-loop", "1", "-i", seg["path"]]
        if seg["efecto"] == "kenburns":
            # Foto a pantalla completa con zoom lento (aquí sí llena recortando,
            # que en fotos se ve bien).
            graph = (
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"scale={W*2}:{H*2},"
                f"zoompan=z='min(zoom+0.0009,1.30)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}"
                f"{suffix}[v]"
            )
        else:
            graph = f"{_contain_blur('0:v')},fps={FPS}{suffix}[v]"
    else:  # video
        # -ss ANTES de -i: salta rápido al punto relevante que se eligió.
        inputs = (["-ss", f"{inicio:.2f}"] if inicio > 0 else []) + ["-i", seg["path"]]
        graph = f"{_contain_blur('0:v')},fps={FPS}{suffix}[v]"

    cmd = ["ffmpeg", "-y", *inputs, "-t", f"{dur}",
           "-filter_complex", graph, "-map", "[v]", "-r", f"{FPS}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-an", out]
    _run(cmd, cwd=build_dir)
    return out


def _concat(seg_files: list, build_dir: str) -> str:
    list_path = os.path.join(build_dir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for s in seg_files:
            f.write(f"file '{s}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
          "-c", "copy", "video.mp4"], cwd=build_dir)
    return "video.mp4"


def _audio_graph(plan: dict, build_dir: str, voice_rel: str):
    """Devuelve (inputs_extra, filtro_audio, tiene_audio).

    voice_rel: nombre relativo (en build_dir) del mp3 de voz ya listo, o None.
    """
    music = plan["musica"]
    music_path = music["path"]
    vol = music["volumen"]

    inputs, filt = [], None
    have_voice = bool(voice_rel)
    have_music = bool(music_path)

    if have_voice:
        inputs += ["-i", voice_rel]
    if have_music:
        inputs += ["-i", music_path]

    if have_voice and have_music:
        # video=0, voz=1, música=2
        filt = (f"[2:a]volume={vol},aloop=loop=-1:size=2e9[m];"
                f"[1:a][m]amix=inputs=2:duration=longest:dropout_transition=0[a]")
    elif have_voice:
        filt = "[1:a]anull[a]"
    elif have_music:
        filt = f"[1:a]volume={vol},aloop=loop=-1:size=2e9[a]"

    return inputs, filt, (have_voice or have_music)


def render(plan: dict, build_dir: str, out_path: str,
           voice_path: str = None, ass_path: str = None) -> str:
    """Renderiza el reel completo. Devuelve out_path.

    voice_path / ass_path: rutas absolutas (opcionales). Se copian al build_dir
    con nombre simple para evitar problemas de escape en FFmpeg.
    """
    os.makedirs(build_dir, exist_ok=True)

    # 1) Normalizar cada segmento
    seg_files = [_render_segment(s, build_dir, i)
                 for i, s in enumerate(plan["segmentos"])]

    # 2) Concatenar
    video_rel = _concat(seg_files, build_dir)

    # 3) Preparar voz y subtítulos dentro de build_dir (nombres simples)
    voice_rel = None
    if voice_path and os.path.isfile(voice_path):
        voice_rel = "voice.mp3"
        dst = os.path.join(build_dir, voice_rel)
        if os.path.abspath(voice_path) != os.path.abspath(dst):
            import shutil
            shutil.copy2(voice_path, dst)

    subs_rel = None
    if ass_path and os.path.isfile(ass_path) and plan["subtitulos"]["activo"]:
        subs_rel = "subs.ass"
        dst = os.path.join(build_dir, subs_rel)
        if os.path.abspath(ass_path) != os.path.abspath(dst):
            import shutil
            shutil.copy2(ass_path, dst)

    # 4) Paso final: subtítulos + mezcla de audio + CIERRE SUAVE (fundidos)
    total = float(plan["duracion_total"])
    a_inputs, a_filt, have_audio = _audio_graph(plan, build_dir, voice_rel)

    # Video: subtítulos (si hay) + fundido de entrada y de salida, para que ni
    # arranque ni termine de golpe.
    vchain = []
    if subs_rel:
        vchain.append(f"subtitles={subs_rel}")
    vchain.append("fade=t=in:st=0:d=0.5")
    vchain.append(f"fade=t=out:st={max(0.0, total - 0.8):.2f}:d=0.8")
    fc_parts = [f"[0:v]{','.join(vchain)}[v]"]
    vmap = "[v]"

    # Audio: mezcla + fundido de entrada/salida (evita el corte seco al final).
    if a_filt:
        a_filt = a_filt.rsplit("[a]", 1)[0] + "[a0]"
        a_filt += (f";[a0]afade=t=in:st=0:d=0.3,"
                   f"afade=t=out:st={max(0.0, total - 1.0):.2f}:d=1.0[a]")
        fc_parts.append(a_filt)

    cmd = ["ffmpeg", "-y", "-i", video_rel, *a_inputs,
           "-filter_complex", ";".join(fc_parts), "-map", vmap]
    if have_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    # Siempre re-encodeamos el video (por los fundidos). Corte de duración EXACTO.
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-t", f"{total:.2f}", "-movflags", "+faststart", "reel.mp4"]
    _run(cmd, cwd=build_dir)

    final_build = os.path.join(build_dir, "reel.mp4")
    if os.path.abspath(final_build) != os.path.abspath(out_path):
        import shutil
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.copy2(final_build, out_path)
    return out_path