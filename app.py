"""reel-studio — interfaz para armar reels a partir de material propio.

Flujo pensado para alguien SIN experiencia en edición:
  1) Sube tus fotos, clips y (si quieres) tu voz y tu música.
  2) Escribe qué quieres.
  3) La IA propone un PLAN -> tú lo revisas y ajustas.
  4) Apruebas -> se arma el reel -> lo ves y lo descargas.

Correr local:   streamlit run app.py
"""
import os
import traceback

import streamlit as st

# Puente de secrets -> variables de entorno. En Streamlit Community Cloud los
# valores se cargan en st.secrets; los copiamos a os.environ para que el resto
# del código (que lee os.environ, p. ej. GEMINI_API_KEY) los encuentre igual que
# en local con .env. Debe correr ANTES de importar los módulos de src.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from src import config, storage, inventory, plan_brain, plan_schema, voice, subtitles, renderer
try:
    from src import auth
except Exception:
    auth = None  # el candado de contraseña es opcional; si falta, la app abre igual

st.set_page_config(page_title="reel-studio", page_icon="🎬", layout="centered")

if auth:
    auth.require_password()  # no pide nada si APP_PASSWORD no está definida

store = storage.get_storage()
ss = st.session_state
ss.setdefault("session_id", storage.new_session_id())
ss.setdefault("asset_paths", [])
ss.setdefault("inventory", [])
ss.setdefault("plan", None)
ss.setdefault("out_path", None)

MODOS = {
    "Generar voz con IA": "tts",
    "Subir mi propia voz": "voz_subida",
    "Solo música (sin narración)": "solo_musica",
    "Sin audio": "ninguno",
}

TONOS = {
    "Experiencia personal": ("Cuéntalo como una experiencia que vivimos en primera "
                             "persona (fuimos, vimos, la pasamos bien); cercano y "
                             "auténtico, NADA promocional."),
    "Informativo": ("Tono informativo y claro: explica qué es el lugar y qué se ve, "
                    "con contexto."),
    "Divertido / casual": ("Tono divertido, casual y con energía, ideal para redes."),
    "Promoción / invitación": ("Tono que invita a visitar el lugar."),
}

st.title("🎬 reel-studio")
st.caption("Sube tu material, di qué quieres, revisa la propuesta y descarga tu reel.")

# ----------------------------------------------------------------------------
# 1) Subir material
# ----------------------------------------------------------------------------
st.header("1 · Sube tu material")
media = st.file_uploader(
    "Fotos y videos (puedes subir varios)",
    type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "m4v", "webm"],
    accept_multiple_files=True,
)
col_a, col_b = st.columns(2)
with col_a:
    voz_file = st.file_uploader("Tu voz (opcional)", type=["mp3", "wav", "m4a", "aac"])
with col_b:
    musica_file = st.file_uploader("Música (opcional)", type=["mp3", "wav", "m4a", "aac"])

if st.button("Cargar material", use_container_width=True):
    paths = []
    for f in (media or []):
        paths.append(store.save_upload(ss.session_id, f.name, f.getvalue()))
    if voz_file:
        paths.append(store.save_upload(ss.session_id, voz_file.name, voz_file.getvalue()))
    if musica_file:
        paths.append(store.save_upload(ss.session_id, musica_file.name, musica_file.getvalue()))
    if not paths:
        st.warning("No subiste nada todavía.")
    else:
        ss.asset_paths = paths
        ss.inventory = inventory.build_inventory(paths)
        ss.plan = None
        ss.out_path = None
        st.success(f"Cargados {len(paths)} archivos.")

if ss.inventory:
    with st.expander("Ver material cargado", expanded=False):
        for it in ss.inventory:
            d = f"{it['duration']}s" if it.get("duration") else "imagen"
            st.write(f"• **{it['file']}** — {it['kind']} · {d}")

# ----------------------------------------------------------------------------
# 2) Instrucciones
# ----------------------------------------------------------------------------
st.header("2 · Di qué quieres")
modo_label = st.radio("¿De dónde sale la voz?", list(MODOS.keys()), horizontal=False)
modo_voz = MODOS[modo_label]

voz_tts = config.TTS_VOICE
if modo_voz == "tts":
    voz_tts = st.selectbox(
        "Voz IA",
        ["es-MX-DaliaNeural", "es-MX-JorgeNeural", "es-MX-RenataNeural"],
        index=0,
    )

estilo_label = st.selectbox("Estilo / tono", list(TONOS.keys()), index=0)
tono = TONOS[estilo_label]

instrucciones = st.text_area(
    "Explica el reel que quieres",
    placeholder=("Ej: reel de nuestra visita al tianguis pirotécnico de "
                 "Chimalhuacán. Empieza ubicando el lugar, muestra los puestos y "
                 "el ambiente, y cierra bien. Con subtítulos."),
    height=130,
)

if st.button("✨ Generar propuesta", type="primary", use_container_width=True,
             disabled=not ss.inventory):
    if not os.environ.get("GEMINI_API_KEY"):
        st.error("Falta la variable GEMINI_API_KEY (la API key de Gemini).")
    elif not instrucciones.strip():
        st.warning("Escribe primero qué quieres.")
    else:
        try:
            with st.spinner("La IA está armando la propuesta…"):
                raw = plan_brain.build_plan(instrucciones, ss.inventory,
                                            modo_voz=modo_voz, voz_tts=voz_tts,
                                            tono=tono)
                ss.plan = plan_schema.normalize(raw, ss.inventory)
                ss.out_path = None
        except plan_schema.PlanError as e:
            st.error(f"La propuesta no era usable: {e}")
        except Exception as e:
            st.error(f"No se pudo generar la propuesta: {e}")

# ----------------------------------------------------------------------------
# 3) Revisar y aprobar el plan
# ----------------------------------------------------------------------------
if ss.plan:
    st.header("3 · Revisa y ajusta")
    plan = ss.plan
    media_assets = [it["file"] for it in ss.inventory if it["kind"] in ("image", "video")]

    import pandas as pd
    df = pd.DataFrame([
        {"asset": s["asset"], "inicio (seg)": s.get("inicio", 0.0),
         "seg (dur)": s["dur"], "efecto": s["efecto"],
         "texto": s["texto"] or "", "transición": s["transicion"]}
        for s in plan["segmentos"]
    ])
    edited = st.data_editor(
        df, use_container_width=True, num_rows="dynamic", key="editor",
        column_config={
            "asset": st.column_config.SelectboxColumn(options=media_assets, required=True),
            "inicio (seg)": st.column_config.NumberColumn(
                min_value=0.0, step=0.5, help="Segundo del clip donde empezar (videos)"),
            "seg (dur)": st.column_config.NumberColumn(min_value=1.0, max_value=300.0, step=0.5),
            "efecto": st.column_config.SelectboxColumn(options=["kenburns", "none"]),
            "transición": st.column_config.SelectboxColumn(options=["fade", "none"]),
        },
    )

    subtitulos_on = st.checkbox("Subtítulos", value=plan["subtitulos"]["activo"])
    vol = st.slider("Volumen de la música", 0.0, 1.0,
                    float(plan["musica"]["volumen"]), 0.02)

    total_est = float(edited["seg (dur)"].fillna(0).sum())
    st.caption(f"Duración estimada: ~{total_est:.0f}s")

    if st.button("✅ Aprobar y generar reel", type="primary", use_container_width=True):
        # Reconstruir el plan crudo desde lo que ella editó y volver a validar.
        raw = {
            "duracion_total": total_est,
            "audio": plan["audio"],
            "musica": {"archivo": plan["musica"]["archivo"], "volumen": vol},
            "subtitulos": {"activo": subtitulos_on, "fuente": "auto"},
            "segmentos": [
                {"asset": r["asset"], "inicio": r.get("inicio (seg)", 0),
                 "dur": r["seg (dur)"], "efecto": r["efecto"],
                 "texto": r["texto"] or None, "transicion": r["transición"]}
                for _, r in edited.iterrows() if r["asset"]
            ],
        }
        try:
            final_plan = plan_schema.normalize(raw, ss.inventory)
            build_dir = store.build_dir(ss.session_id)
            os.makedirs(build_dir, exist_ok=True)

            # --- Voz + subtítulos ---
            voice_path, ass_path = None, None
            a = final_plan["audio"]
            with st.spinner("Preparando audio y subtítulos…"):
                if a["tipo"] == "tts" and a["guion"]:
                    voice_path = os.path.join(build_dir, "voice.mp3")
                    boundaries = voice.synthesize(a["guion"], voice_path,
                                                  a.get("voz_tts"))
                    if final_plan["subtitulos"]["activo"]:
                        ass_path = os.path.join(build_dir, "subs.ass")
                        subtitles.build_ass(ass_path, boundaries=boundaries)
                elif a["tipo"] == "voz_subida" and a["path"]:
                    voice_path = a["path"]
                    if final_plan["subtitulos"]["activo"] and a.get("guion"):
                        ass_path = os.path.join(build_dir, "subs.ass")
                        subtitles.build_ass(ass_path, text=a["guion"],
                                            audio_path=voice_path)

            # --- Render ---
            with st.spinner("Armando el reel (esto tarda un poco)…"):
                out_local = os.path.join(build_dir, "reel_final.mp4")
                renderer.render(final_plan, build_dir, out_local,
                                voice_path=voice_path, ass_path=ass_path)
                ss.out_path = store.publish_output(ss.session_id, out_local)
            st.success("¡Listo!")
        except Exception as e:
            st.error(f"No se pudo generar el reel: {e}")
            st.code(traceback.format_exc())

# ----------------------------------------------------------------------------
# 4) Resultado
# ----------------------------------------------------------------------------
if ss.out_path:
    st.header("4 · Tu reel")
    # En local out_path es una ruta; en GCS es una URL firmada.
    if os.path.isfile(ss.out_path):
        st.video(ss.out_path)
        with open(ss.out_path, "rb") as f:
            st.download_button("⬇️ Descargar reel", f, file_name="reel.mp4",
                               mime="video/mp4", use_container_width=True)
    else:
        st.video(ss.out_path)
        st.markdown(f"[⬇️ Descargar reel]({ss.out_path})")