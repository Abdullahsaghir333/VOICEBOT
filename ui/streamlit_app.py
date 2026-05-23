"""Streamlit UI for the Voice AI outbound calling agent."""

import os
from datetime import datetime, timedelta

import httpx
import streamlit as st

API_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8001")

st.set_page_config(
    page_title="Voice AI — Appointment Reminder",
    page_icon="📞",
    layout="wide",
)

st.title("📞 Voice AI Agent")
st.caption("Appointment reminder — Twilio → Deepgram → Groq → Edge TTS")

def _check_api() -> tuple[bool, str]:
    """Ping FastAPI backend (must be run_api.bat on port 8000)."""
    try:
        health = httpx.get(f"{API_URL}/health", timeout=3.0)
        if health.status_code == 200:
            return True, ""
        return False, f"HTTP {health.status_code}"
    except httpx.ConnectError:
        return False, "Connection refused — is run_api.bat running?"
    except httpx.ReadTimeout:
        return False, "Timed out — API may be stuck; restart run_api.bat"
    except Exception as exc:
        return False, str(exc)


if "api_ok" not in st.session_state:
    st.session_state.api_ok, st.session_state.api_error = _check_api()

col_status, col_config, col_refresh = st.columns([1, 2, 1])
with col_status:
    st.metric("API", "Online" if st.session_state.api_ok else "Offline")
with col_config:
    if st.session_state.api_ok:
        try:
            cfg = httpx.get(f"{API_URL}/config/public", timeout=3.0).json()
            st.caption(f"Backend: `{API_URL}` · Webhook: `{cfg.get('public_base_url')}`")
        except Exception:
            st.caption(f"Backend: `{API_URL}`")
    else:
        st.warning(
            f"**Cannot reach the API** at `{API_URL}`\n\n"
            f"_{st.session_state.api_error}_\n\n"
            "1. Open a **separate** terminal and run: `run_api.bat`\n"
            "2. Wait for: `Connected to MongoDB` and `Application startup complete`\n"
            "3. Click **Refresh** → or press **R** in Streamlit\n\n"
            "Test in browser: [http://localhost:8000/health](http://localhost:8000/health) — should show "
            '`{"status":"ok",...}`'
        )
with col_refresh:
    if st.button("Refresh", help="Re-check API connection"):
        st.session_state.api_ok, st.session_state.api_error = _check_api()
        st.rerun()

api_ok = st.session_state.api_ok

tab_call, tab_appts, tab_history = st.tabs(["Place call", "Appointments", "Call history"])

with tab_appts:
    st.subheader("Manage appointments")
    with st.form("new_appointment", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            patient_name = st.text_input("Patient name", "Jane Doe")
            patient_phone = st.text_input("Patient phone (E.164)", "+15551234567")
            provider = st.text_input("Provider", "Dr. Smith")
        with c2:
            clinic = st.text_input("Clinic", "HealthCare Plus Clinic")
            address = st.text_input("Address", "123 Wellness Ave")
            appt_when = st.datetime_input(
                "Appointment time",
                value=datetime.now() + timedelta(days=2),
            )
        if st.form_submit_button("Save appointment", type="primary") and api_ok:
            payload = {
                "patient_name": patient_name,
                "patient_phone": patient_phone,
                "appointment_datetime": appt_when.isoformat(),
                "provider_name": provider,
                "clinic_name": clinic,
                "clinic_address": address,
            }
            r = httpx.post(f"{API_URL}/api/appointments", json=payload, timeout=15.0)
            if r.is_success:
                st.success(f"Saved appointment `{r.json().get('id')}`")
            else:
                st.error(r.text)

    if api_ok:
        appts = httpx.get(f"{API_URL}/api/appointments", timeout=10.0)
        if appts.is_success:
            st.dataframe(appts.json(), use_container_width=True)

with tab_call:
    st.subheader("Trigger outbound call")

    provider = "custom"
    if api_ok:
        pr = httpx.get(f"{API_URL}/api/calls/providers", timeout=5.0)
        if pr.is_success:
            custom = next((p for p in pr.json().get("providers", []) if p["id"] == "custom"), None)
            if custom and not custom.get("configured"):
                st.warning("Custom pipeline not fully configured — check Twilio, Deepgram, and Groq in `.env`.")

    scenario = st.selectbox(
        "Scenario",
        ["appointment_reminder"],
        help="Additional scenarios can be registered in app/scenarios/",
    )

    use_existing = st.radio("Appointment source", ["Existing appointment", "Custom details"], horizontal=True)

    appointment_id = None
    custom = {}
    if api_ok and use_existing == "Existing appointment":
        appts = httpx.get(f"{API_URL}/api/appointments", timeout=10.0)
        options = {}
        if appts.is_success:
            for a in appts.json():
                label = f"{a['patient_name']} — {a['appointment_datetime']}"
                options[label] = a["id"]
        appointment_id = st.selectbox(
            "Select appointment",
            options=list(options.keys()) if options else ["No appointments yet"],
        )
        if options:
            appointment_id = options.get(appointment_id)
    else:
        c1, c2 = st.columns(2)
        with c1:
            custom["patient_name"] = st.text_input("Patient name", "Jane Doe")
            custom["provider_name"] = st.text_input("Provider", "Dr. Smith")
        with c2:
            custom["clinic_name"] = st.text_input("Clinic", "HealthCare Plus Clinic")
            custom["clinic_address"] = st.text_input("Address", "123 Wellness Ave")
            custom["appointment_datetime"] = st.datetime_input(
                "Appointment time",
                value=datetime.now() + timedelta(days=2),
            ).isoformat()

    phone = st.text_input("Phone number to call (E.164)", "+15551234567")

    if st.button("Start call", type="primary", disabled=not api_ok):
        body = {"phone_number": phone, "scenario": scenario, "provider": provider}
        if use_existing == "Existing appointment" and appointment_id:
            body["appointment_id"] = appointment_id
        else:
            body.update(custom)

        with st.spinner("Placing call via Twilio…"):
            r = httpx.post(f"{API_URL}/api/calls/outbound", json=body, timeout=30.0)
        if r.is_success:
            data = r.json()
            ref = data.get("vapi_call_id") or data.get("twilio_call_sid") or "—"
            st.success(f"Call started — ID `{data['id']}` · provider `{data.get('provider')}` · ref `{ref}`")
            st.json(data)
        else:
            st.error(r.text)

with tab_history:
    st.subheader("Recent calls")
    if api_ok:
        r = httpx.get(f"{API_URL}/api/calls", timeout=10.0)
        if r.is_success:
            for call in r.json().get("calls", []):
                with st.expander(
                    f"{call['phone_number']} · {call.get('provider', 'custom')} · {call['status']} · {call.get('outcome') or '—'}"
                ):
                    st.write(f"**Provider:** {call.get('provider', 'custom')}")
                    st.write(f"**Scenario:** {call['scenario']}")
                    st.write(f"**Created:** {call['created_at']}")
                    if call.get("conversation"):
                        st.markdown("**Transcript**")
                        for turn in call["conversation"]:
                            role = turn["role"].upper()
                            line = f"**{role}:** {turn['content']}"
                            m = turn.get("metrics")
                            if m:
                                line += (
                                    f"  _(llm {m.get('llm_ms')}ms · tts {m.get('tts_ms')}ms · "
                                    f"total {m.get('total_ms')}ms · target {m.get('target_ms')}ms)_"
                                )
                            st.markdown(line)
                    else:
                        st.caption("Transcript will appear after the call.")

st.sidebar.markdown("### Setup checklist (venv)")
st.sidebar.markdown(
    """
1. `setup.bat` — install deps into `.\\venv`  
2. `.env` — Twilio, Deepgram, Groq, MongoDB  
3. [FFmpeg](https://ffmpeg.org/) on PATH  
4. `ngrok http 8000` → set `PUBLIC_BASE_URL`  
5. `run_api.bat` + `run_ui.bat`
"""
)
