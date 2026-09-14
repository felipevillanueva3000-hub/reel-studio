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


def _drawtext(texto: str, build_dir: str, idx: int) -> str:
    """Escribe el texto a un archivo (evita el infierno de escapes) y devuelve
    el fragmento de filtro drawtext que lo dibuja centrado abajo-centro."""
    txt_path = os.path.join(build_dir, f"txt_{idx}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(texto.upper())
    font = config.font_file()
    fontfile = f"fontfile='{font}':" if font else ""
    return (
        f"drawtext={fontfile}textfile='txt_{idx}.txt':"
        f"fontcolor=white:fontsize=72:borderw=4:bordercolor=black@0.85:"
        f"box=1:boxcolor=black@0.35:boxborderw=24:"
        f"x=(w-text_w)/2:y=h*0.70:line_spacing=10"
    )


def _fade(dur: float) -> str:
    d = 0.4
    return f"fade=t=in:st=0:d={d},fade=t=out:st={max(0.0, dur - d):.2f}:d={d}"


def _render_segment(seg: dict, build_dir: str, idx: int) -> str:
    """Normaliza un segmento a build_dir/seg_{idx}.mp4 (video sin audio)."""
    out = f"seg_{idx}.mp4"
    dur = seg["dur"]
    frames = max(1, int(round(dur * FPS)))
    chain = []

    if seg["kind"] == "image":
        if seg["efecto"] == "kenburns":
            # Cubrir 9:16, subir resolución y aplicar zoom lento suave.
            chain.append(
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"scale={W*2}:{H*2},"
                f"zoompan=z='min(zoom+0.0009,1.30)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}"
            )
        else:
            chain.append(
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")
        inputs = ["-loop", "1", "-i", seg["path"]]
    else:  # video
        chain.append(
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}")
        inputs = ["-i", seg["path"]]

    if seg["texto"]:
        chain.append(_drawtext(seg["texto"], build_dir, idx))
    if seg["transicion"] == "fade":
        chain.append(_fade(dur))
    chain.append("setsar=1")
    chain.append("format=yuv420p")
    vf = ",".join(chain)

    cmd = ["ffmpeg", "-y", *inputs, "-t", f"{dur}",
           "-vf", vf, "-r", f"{FPS}",
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

    # 4) Paso final: subtítulos (video) + mezcla de audio
    a_inputs, a_filt, have_audio = _audio_graph(plan, build_dir, voice_rel)

    fc_parts = []
    if subs_rel:
        fc_parts.append(f"[0:v]subtitles={subs_rel}[v]")
        vmap = "[v]"
    else:
        vmap = "0:v"
    if a_filt:
        fc_parts.append(a_filt)

    cmd = ["ffmpeg", "-y", "-i", video_rel, *a_inputs]
    if fc_parts:
        cmd += ["-filter_complex", ";".join(fc_parts)]
    cmd += ["-map", vmap]
    if have_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    # Si aplicamos subtítulos re-encodeamos; si no, copiamos el video tal cual.
    if subs_rel:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    # Corte de duración EXACTO (ya conocemos el total por el plan). Más robusto
    # que -shortest cuando la música va en loop infinito.
    total = float(plan["duracion_total"])
    cmd += ["-t", f"{total:.2f}", "-movflags", "+faststart", "reel.mp4"]
    _run(cmd, cwd=build_dir)

    final_build = os.path.join(build_dir, "reel.mp4")
    if os.path.abspath(final_build) != os.path.abspath(out_path):
        import shutil
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.copy2(final_build, out_path)
    return out_path
