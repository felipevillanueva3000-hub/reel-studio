"""Candado por contraseña (opcional).

Si la variable APP_PASSWORD NO está definida, no pide nada — así en tu máquina
local trabajas sin fricción. En Cloud Run público, defines APP_PASSWORD y la app
pide esa clave una vez por sesión. Es un candado de aplicación sencillo, pensado
para que tu esposa "abra el link y escriba una clave", sin logins complicados.
"""
import os

import streamlit as st


def require_password():
    pw = os.environ.get("APP_PASSWORD", "").strip()
    if not pw:
        return  # sin contraseña configurada -> acceso libre (local/dev)
    if st.session_state.get("_authed"):
        return

    st.title("🔒 reel-studio")
    st.caption("Escribe la contraseña para entrar.")
    entered = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if entered == pw:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()
