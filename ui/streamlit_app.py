"""Streamlit UI for the Voice AI outbound calling agent."""

import os
from datetime import datetime, timedelta

import httpx
import streamlit as st

API_URL = os.getenv("FASTAPI_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Voice AI — Appointment Reminder",
    page_icon="📞",
    layout="wide",
)

st.title("📞 Voice AI Agent")
st.caption("Appointment reminder — Custom pipeline (Twilio/Deepgram/Groq/Edge TTS) or Vapi")

try:
    health = httpx.get(f"{API_URL}/health", timeout=5.0)
    api_ok = health.status_code == 200
except Exception:
    api_ok = False

col_status, col_config = st.columns(2)
with col_status:
    st.metric("API", "Online" if api_ok else "Offline")
with col_config:
    if api_ok:
        cfg = httpx.get(f"{API_URL}/config/public", timeout=5.0).json()
        st.caption(f"Webhook base: `{cfg.get('public_base_url')}`")
    else:
        st.warning(f"Start the API first: `uvicorn app.main:app --reload` at {API_URL}")

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

    providers = []
    if api_ok:
        pr = httpx.get(f"{API_URL}/api/calls/providers", timeout=5.0)
        if pr.is_success:
            providers = pr.json().get("providers", [])

    provider_labels = {
        "custom": "Custom pipeline (Twilio + Deepgram + Groq + Edge TTS)",
        "vapi": "Vapi (managed voice AI)",
    }
    provider_options = [p["id"] for p in providers] or ["custom", "vapi"]
    provider = st.radio(
        "Voice provider",
        options=provider_options,
        format_func=lambda x: provider_labels.get(x, x),
        horizontal=True,
    )
    if providers:
        selected = next((p for p in providers if p["id"] == provider), None)
        if selected and not selected.get("configured"):
            st.warning(f"`{provider}` is not fully configured in .ENV — check API keys.")

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

        label = "Vapi" if provider == "vapi" else "Twilio (custom pipeline)"
        with st.spinner(f"Placing call via {label}…"):
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
2. `.env` / `.ENV` — Twilio and/or Vapi, Groq, MongoDB, Deepgram  
3. [FFmpeg](https://ffmpeg.org/) on PATH (custom pipeline only)  
4. `ngrok http 8000` → `PUBLIC_BASE_URL` (both providers need webhooks)  
5. Vapi dashboard: link Groq + phone number; set Server URL → `/webhooks/vapi`  
6. `run_api.bat` + `run_ui.bat`
"""
)
