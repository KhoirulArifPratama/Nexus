"""Nexus AI - Antarmuka Web Profesional (Streamlit)

Struktur:
  app.py      -> UI & state
  agent.py    -> engine (Gemini streaming + function calling, fallback)
  tools.py    -> kumpulan tools
  styles.css  -> seluruh tema visual
"""
from __future__ import annotations

import json
import html
import os
import queue
import threading
import time
import uuid
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

from agent import (  # noqa: E402
    DEFAULT_MODEL_NAME, DEFAULT_PERSONA, MODELS, PERSONAS, GenerationControl,
    get_gemini_key, jalankan_agent_stream, transkripsi_audio_vn,
)
from tools import ekstrak_teks  # noqa: E402

DATA_DIR = os.path.join(BASE_DIR, "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
LOGO = os.path.join(BASE_DIR, "nexus_logo.png")
MAKS_DOKUMEN_CHAR = 16000

st.set_page_config(
    page_title="Nexus",
    page_icon=LOGO if os.path.exists(LOGO) else "⚡",
    layout="wide",
    initial_sidebar_state="auto",
)

# ------------------------------------------------------------------ Tema
with open(os.path.join(BASE_DIR, "styles.css"), encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ------------------------------------------------------------------ Persistensi sesi
def muat_sesi() -> dict:
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def simpan_sesi() -> None:
    """Simpan ke disk (tanpa bytes audio) secara atomik."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        bersih = {}
        for sid, s in st.session_state.sessions.items():
            bersih[sid] = {
                **s,
                "riwayat": [{k: v for k, v in m.items() if k != "audio_bytes"} for m in s["riwayat"]],
            }
        tmp = SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(bersih, f, ensure_ascii=False)
        os.replace(tmp, SESSIONS_FILE)
    except OSError:
        pass  # gagal simpan tidak boleh merusak percakapan


def sesi_baru() -> str:
    sid = uuid.uuid4().hex[:10]
    st.session_state.sessions[sid] = {
        "title": "Obrolan baru", "riwayat": [], "files": [], "updated": time.time(),
    }
    st.session_state.current = sid
    return sid


def sesi_aktif() -> dict:
    if st.session_state.current not in st.session_state.sessions:
        sesi_baru()
    return st.session_state.sessions[st.session_state.current]


def judul_dari(teks: str) -> str:
    t = " ".join(teks.split())
    return t if len(t) <= 38 else t[:36] + "…"


def nama_grup(ts: float) -> str:
    hari = (datetime.now().date() - datetime.fromtimestamp(ts).date()).days
    if hari <= 0:
        return "Hari ini"
    if hari == 1:
        return "Kemarin"
    return "7 hari terakhir" if hari <= 7 else "Lebih lama"


def salam() -> str:
    try:
        from zoneinfo import ZoneInfo
        jam = datetime.now(ZoneInfo("Asia/Jakarta")).hour
    except Exception:  # tzdata tidak tersedia
        jam = datetime.now().hour
    if jam < 11:
        return "Selamat pagi"
    if jam < 15:
        return "Selamat siang"
    if jam < 18:
        return "Selamat sore"
    return "Selamat malam"


if "sessions" not in st.session_state:
    st.session_state.sessions = muat_sesi()
    st.session_state.current = None
    st.session_state.pending = None
    st.session_state.need_reply = False
    st.session_state.cari = ""
if not st.session_state.current:
    # Buka sesi terbaru yang berisi pesan, atau mulai baru
    terisi = [(s.get("updated", 0), sid) for sid, s in st.session_state.sessions.items() if s["riwayat"]]
    if terisi:
        st.session_state.current = max(terisi)[1]
    else:
        sesi_baru()

sesi = sesi_aktif()
riwayat: list = sesi["riwayat"]

# ------------------------------------------------------------------ Sidebar
with st.sidebar:
    st.markdown(
        '<div class="brand"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="gb1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f7cff"/><stop offset="100%" stop-color="#8b5cf6"/></linearGradient></defs><rect width="64" height="64" rx="15" fill="url(#gb1)"/><text x="32" y="45" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-weight="bold" font-size="38" fill="white">N</text></svg><div><div class="brand-name">Nexus</div>'
        '<div class="brand-sub">Asisten AI</div></div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Obrolan Baru", icon=":material/add:", type="primary", use_container_width=True):
        if riwayat:  # jangan menumpuk sesi kosong
            sesi_baru()
        st.session_state.pending = None
        st.rerun()

    st.markdown('<div class="side-label">Riwayat</div>', unsafe_allow_html=True)
    kata = st.text_input("Cari", key="cari", placeholder="Cari obrolan…", label_visibility="collapsed")

    tampil = [
        (sid, s) for sid, s in sorted(st.session_state.sessions.items(), key=lambda x: x[1].get("updated", 0), reverse=True)
        if s["riwayat"] and kata.lower() in s["title"].lower()
    ]
    if not tampil:
        st.caption("Belum ada riwayat." if not kata else "Tidak ada hasil.")
    grup_terakhir = None
    for sid, s in tampil[:40]:
        grup = nama_grup(s.get("updated", 0))
        if grup != grup_terakhir:
            st.markdown(f'<div class="side-label">{grup}</div>', unsafe_allow_html=True)
            grup_terakhir = grup
        aktif = sid == st.session_state.current
        c1, c2 = st.columns([8, 2], vertical_alignment="center")
        with c1:
            if st.button(s["title"], key=f"{'hact' if aktif else 'h'}_{sid}", use_container_width=True):
                st.session_state.current = sid
                st.rerun()
        with c2:
            if st.button("", key=f"d_{sid}", icon=":material/delete:", help="Hapus obrolan"):
                del st.session_state.sessions[sid]
                if aktif:
                    st.session_state.current = None
                simpan_sesi()
                st.rerun()

    st.markdown('<div class="side-label">Pengaturan</div>', unsafe_allow_html=True)
    with st.expander("Model & karakter", icon=":material/tune:"):
        if "model_name" not in st.session_state:
            st.session_state.model_name = (
                DEFAULT_MODEL_NAME if get_gemini_key() else "Cloud Cadangan"
            )
        elif not st.session_state.get("model_default_migrated"):
            if st.session_state.model_name == "Gemini Flash":
                st.session_state.model_name = DEFAULT_MODEL_NAME
            st.session_state.model_default_migrated = True
        model_name = st.selectbox("Model", list(MODELS), key="model_name")
        st.caption(MODELS[model_name]["desc"])
        persona_name = st.selectbox("Karakter", list(PERSONAS), key="persona_name")
        pakai_tools = st.toggle("Izinkan Nexus memakai tools", value=True, key="pakai_tools",
                                help="Pencarian web, cuaca, kalkulator, Wikipedia, Python, dan lainnya.")
        if pakai_tools and model_name.startswith("Cloud"):
            st.caption("Mesin cadangan tidak mendukung tools.")
    if not get_gemini_key() and not model_name.startswith("Cloud"):
        st.info(
            "GEMINI_API_KEY belum dikonfigurasi; jawaban akan dialihkan ke mesin cadangan. "
            "Atur key di file .env atau Streamlit Secrets.",
            icon=":material/info:",
        )

    if sesi["files"]:
        st.markdown('<div class="side-label">Dokumen aktif</div>', unsafe_allow_html=True)
        for fn in sesi["files"]:
            st.caption(f":material/description: {fn}")

    if riwayat:
        st.markdown('<div class="side-label">Ekspor</div>', unsafe_allow_html=True)
        md = [f"# {sesi['title']}\n*Diekspor {datetime.now():%d %b %Y %H:%M}*\n"]
        for m in riwayat:
            if m.get("content"):
                md.append(f"**{'Anda' if m['role'] == 'user' else 'Nexus'}**\n\n{m['content']}\n")
        st.download_button("Unduh (.md)", "\n".join(md), f"nexus_{datetime.now():%Y%m%d_%H%M}.md",
                           "text/markdown", icon=":material/download:", use_container_width=True)

def _ambil(obj, nama, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(nama, default)
    return getattr(obj, nama, default)


def render_pesan(m: dict) -> None:
    if m["role"] == "user":
        with st.chat_message("user"):
            st.markdown('<span class="u-mark"></span>', unsafe_allow_html=True)
            if m.get("audio_bytes"):
                st.audio(m["audio_bytes"], format="audio/wav")
            st.markdown(m["content"])
    else:
        with st.chat_message("assistant"):
            if m.get("error"):
                st.markdown(f'<div class="err-box">{m["error"]}</div>', unsafe_allow_html=True)
            if m.get("content"):
                st.markdown(m["content"])


def thinking_markup(status: str = "") -> str:
    label = html.escape(status or "Nexus sedang berpikir")
    detail = "Menyusun jawaban terbaik untukmu" if not status else "Mohon tunggu sebentar"
    return (
        '<div class="thinking">'
        '<span class="thinking-orb" aria-hidden="true"><span></span></span>'
        '<span class="thinking-copy">'
        f"<strong>{label}</strong><em>{detail}</em>"
        "</span></div>"
    )


hero_slot = st.empty()
if not riwayat:
    hero_slot.markdown(
        f'<div class="hero"><div class="hero-mark"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="gb2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#4f7cff"/><stop offset="100%" stop-color="#8b5cf6"/></linearGradient></defs><rect width="64" height="64" rx="15" fill="url(#gb2)"/><text x="32" y="45" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-weight="bold" font-size="38" fill="white">N</text></svg></div>'
        f'<div class="hero-hi">{salam()}</div>'
        '<div class="hero-q">Apa yang bisa saya bantu hari ini?</div>'
        '<div class="hero-caps"><span>Cari di web</span><span>Baca dokumen</span>'
        '<span>Pesan suara</span><span>Hitung &amp; Python</span><span>Cuaca</span></div></div>',
        unsafe_allow_html=True,
    )
else:
    for m in riwayat:
        render_pesan(m)

turn_slot = st.container()
with st.container():
    masukan = st.chat_input(
        "Tanyakan apa saja, lampirkan dokumen, atau rekam suara…",
        accept_file=True,
        file_type=["pdf", "docx", "csv", "json", "txt", "md"],
        accept_audio=True,
        audio_sample_rate=16000,
    )
st.markdown(
    '<div class="chat-disclaimer">Nexus dapat membuat kesalahan. Verifikasi informasi penting.</div>',
    unsafe_allow_html=True,
)

teks_user, audio_bytes, nama_dok, isi_dok = "", None, [], []
hasil_audio = None
pesan_ditambahkan = False
if masukan:
    if isinstance(masukan, str):
        teks_user = masukan.strip()
    else:
        teks_user = (_ambil(masukan, "text", "") or "").strip()
        audio = _ambil(masukan, "audio")
        if audio:
            audio_bytes = audio.getvalue()
        for uf in _ambil(masukan, "files", []) or []:
            nama_dok.append(uf.name)
            try:
                isi = ekstrak_teks(uf.name, uf.getvalue())[:MAKS_DOKUMEN_CHAR]
                isi_dok.append(f"[Lampiran Dokumen: '{uf.name}']\n{isi}")
            except Exception as e:  # noqa: BLE001
                st.toast(f"Gagal membaca {uf.name}: {e}", icon="⚠️")
elif st.session_state.pending:
    teks_user, st.session_state.pending = st.session_state.pending, None

if teks_user or audio_bytes or isi_dok:
    if audio_bytes:
        with st.spinner("Mentranskripsi pesan suara…"):
            try:
                hasil_audio = transkripsi_audio_vn(audio_bytes)
            except (RuntimeError, ValueError) as e:
                st.error(str(e))
                audio_bytes = None

    teks_prompt = teks_user
    if hasil_audio:
        teks_suara = (
            f"Bahasa terdeteksi: {hasil_audio['detected_language']}\n"
            f"Ucapan asli: {hasil_audio['transcription']}\n"
            f"Terjemahan Indonesia: {hasil_audio['translation_id']}"
        )
        teks_prompt = (
            (f"Pesan teks tambahan dari pengguna: {teks_user}\n\n" if teks_user else "")
            + "Pengguna mengirim pesan suara. Pahami dan jawab maksud/pertanyaan di dalamnya. "
            "Gunakan terjemahan Indonesia bila ucapan bukan berbahasa Indonesia.\n"
            + teks_suara
        )
        tampil_user = (
            (f"{teks_user}\n\n" if teks_user else "")
            + f"**Pesan suara ({hasil_audio['detected_language']}):**\n"
            + f"> {hasil_audio['transcription']}\n\n"
            + f"**Terjemahan Indonesia:** {hasil_audio['translation_id']}"
        )
    else:
        tampil_user = teks_user

    if isi_dok:
        perintah = teks_user or "Analisis dokumen ini dan jelaskan poin-poin utamanya."
        agent_prompt = teks_prompt or perintah
        agent_prompt += "\n\n" + "\n\n".join(isi_dok)
        tampil_user = f"**Lampiran:** {', '.join(nama_dok)}\n\n{tampil_user}".strip() if tampil_user else f"**Lampiran:** {', '.join(nama_dok)}"
        for fn in nama_dok:
            if fn not in sesi["files"]:
                sesi["files"].append(fn)
    else:
        agent_prompt = teks_prompt

    if teks_prompt or isi_dok:
        entri = {"role": "user", "content": tampil_user, "agent_prompt": agent_prompt, "ts": time.time()}
        if audio_bytes:
            entri["audio_bytes"] = audio_bytes
        riwayat.append(entri)
        pesan_ditambahkan = True
        if sesi["title"] == "Obrolan baru":
            sesi["title"] = judul_dari(teks_user or ", ".join(nama_dok))
        sesi["updated"] = time.time()
        st.session_state.need_reply = True


# ------------------------------------------------------------------ Generate jawaban (streaming nyata)
if st.session_state.need_reply:
    if pesan_ditambahkan:
        hero_slot.empty()
    st.session_state.need_reply = False
    with turn_slot:
        if pesan_ditambahkan:
            render_pesan(riwayat[-1])
        with st.chat_message("assistant"):
            indikator = st.empty()
            indikator.markdown(thinking_markup(), unsafe_allow_html=True)
            tools_dipakai: list = []
            meta = {"error": None, "provider": ""}
            event_queue: queue.Queue = queue.Queue()
            control = GenerationControl()
            riwayat_agent = list(riwayat)
            api_key = get_gemini_key()

            def proses_agent():
                try:
                    for ev in jalankan_agent_stream(
                        riwayat_agent, model_name, persona_name, pakai_tools,
                        control=control, api_key=api_key,
                    ):
                        event_queue.put(ev)
                except Exception as e:
                    event_queue.put({"type": "error", "text": f"Gagal membuat jawaban: {e}"})
                finally:
                    event_queue.put(None)

            pekerja = threading.Thread(target=proses_agent, daemon=True)
            pekerja.start()

            def aliran():
                potongan: list[str] = []
                selesai = False
                try:
                    while True:
                        try:
                            ev = event_queue.get(timeout=0.25)
                        except queue.Empty:
                            indikator.markdown(thinking_markup(), unsafe_allow_html=True)
                            continue
                        if ev is None:
                            selesai = True
                            break
                        t = ev["type"]
                        if t == "text":
                            indikator.empty()
                            potongan.append(ev["text"])
                            yield ev["text"]
                        elif t == "status":
                            indikator.markdown(thinking_markup(ev["text"]), unsafe_allow_html=True)
                        elif t == "tool":
                            tools_dipakai.append({
                                "name": ev["name"], "args": ev["args"], "hasil": ev["hasil"],
                            })
                        elif t == "error":
                            meta["error"] = ev["text"]
                        elif t == "done":
                            meta["provider"] = ev.get("provider", "")
                finally:
                    if not selesai:
                        control.cancel()
                        if potongan:
                            riwayat.append({
                                "role": "assistant", "content": "".join(potongan),
                                "tools": tools_dipakai, "provider": "stopped",
                                "error": None, "stopped": True, "ts": time.time(),
                            })
                            sesi["updated"] = time.time()
                            simpan_sesi()
                        pekerja.join(timeout=0.25)

            jawaban = st.write_stream(aliran())
            indikator.empty()
            jawaban = jawaban if isinstance(jawaban, str) else "".join(str(x) for x in jawaban or [])
            if meta["error"]:
                st.markdown(f'<div class="err-box">{meta["error"]}</div>', unsafe_allow_html=True)

    riwayat.append({
        "role": "assistant", "content": jawaban, "tools": tools_dipakai,
        "provider": meta["provider"], "error": meta["error"], "ts": time.time(),
    })
    sesi["updated"] = time.time()
    simpan_sesi()
    st.rerun()  # render ulang agar judul riwayat di sidebar ikut diperbarui
