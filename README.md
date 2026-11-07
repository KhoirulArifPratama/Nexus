# Nexus AI

Asisten AI berbasis web (Streamlit) dengan **function calling**, **streaming sungguhan**,
analisis dokumen, input suara, dan riwayat obrolan yang tersimpan.

## Fitur
- **UI profesional**: tema gelap konsisten, sidebar riwayat dengan pencarian & hapus,
  status koneksi, responsif untuk mobile.
- Akses publik tanpa login.
- **Streaming token asli** dari Gemini (bukan simulasi), dengan indikator "Berpikir..." dan
  status tool yang sedang dijalankan.
- **Function calling native**: model memilih sendiri tool yang dibutuhkan (multi-langkah, maks. 5).
- **Model dipilih dari UI benar-benar dipakai**, dengan fallback otomatis ke model cadangan,
  lalu ke mesin cloud cadangan. Error ditampilkan jujur, bukan ditutupi.
- **Riwayat tersimpan** di `data/sessions.json` (tetap ada setelah restart).
- Tombol **Ulangi jawaban**, ekspor `.md`, lampiran PDF/DOCX/CSV/JSON/TXT/MD, dan pesan suara
  16 kHz yang ditranskripsikan dalam bahasa aslinya, diterjemahkan ke Bahasa Indonesia, lalu dijawab AI.
- **Tools**: pencarian web, pembaca halaman, Wikipedia, cuaca, kalkulator, waktu, Python, catatan.

## Menjalankan
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

Untuk menjalankan secara lokal, isi `GEMINI_API_KEY` di `.env`. Untuk Streamlit Community Cloud,
masukkan API key di **App settings → Secrets**:
```toml
GEMINI_API_KEY = "API-key-Gemini"
```
Simpan kode di repositori GitHub dan pilih `app.py` sebagai entry point. Jangan unggah `.env`
atau `.streamlit/secrets.toml` ke GitHub.

## Struktur
```
app.py       UI & state sesi
agent.py     Engine: Gemini streaming + function calling + fallback
tools.py     Kumpulan tools
styles.css   Seluruh tema visual
data/        Riwayat obrolan (dibuat otomatis, diabaikan git)
```

## Menambah tool baru
1. Tulis fungsinya di `tools.py`, daftarkan di `FUNCTIONS`, dan definisikan skemanya di `TOOLS`.
2. (Opsional) Tambahkan label tampilan di `TOOL_LABEL` pada `agent.py`.
Model akan otomatis menggunakannya bila relevan.

## Keamanan
- **Jangan pernah membagikan file `.env`** atau memasukkannya ke zip/repo. API key dikirim lewat
  header `x-goog-api-key`, tidak lagi di URL.
- Aplikasi ini publik tanpa login; siapa pun yang memiliki URL dapat menggunakannya.
- Riwayat obrolan digunakan bersama dan jangan masukkan informasi sensitif.
- Simpan `secrets.toml` di luar repositori; jangan commit ke GitHub.
- `baca_halaman_web` memblokir alamat jaringan internal (perlindungan SSRF).
- `eksekusi_python` berjalan di proses terpisah dengan timeout 8 detik dan daftar blokir dasar,
  tetapi **bukan sandbox keamanan penuh**. Untuk deployment multi-user, jalankan di container terisolasi.
