"""Nexus AI - Module Tools
Kumpulan tools canggih yang dapat dieksekusi oleh Nexus AI secara otomatis dan gratis.
"""
import ast
import contextlib
import csv
import io
import json
import math
import operator as op
import re
import statistics
import ipaddress
import socket
import subprocess
import sys
from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import urllib3.util.connection as urllib3_cn
    urllib3_cn.HAS_IPV6 = False
except Exception:
    pass

import requests
# pyrefly: ignore[missing-import]
from bs4 import BeautifulSoup

# Import modul eksternal dengan penanganan fallback aman
try:
    # pyrefly: ignore[missing-import]
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        DDGS = None  # type: ignore

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

try:
    from docx import Document  # type: ignore
except Exception:
    Document = None  # type: ignore

# ---------------------------------------------------------------- kalkulator presisi
_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
    ast.USub: op.neg, ast.UAdd: op.pos,
}
_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "abs": abs, "round": round, "ceil": math.ceil, "floor": math.floor,
    "factorial": math.factorial, "gcd": math.gcd,
    "pi": math.pi, "e": math.e,
}


def _eval_expr(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        kiri, kanan = _eval_expr(node.left), _eval_expr(node.right)
        if isinstance(node.op, ast.Pow) and abs(kanan) > 1000:
            raise ValueError("Pangkat terlalu besar (maks 1000).")
        return _OPS[type(node.op)](kiri, kanan)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_expr(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUNCS:
        return _FUNCS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval_expr(a) for a in node.args])
    raise ValueError(f"Ekspresi atau fungsi tidak didukung: {ast.dump(node)}")


def kalkulator(ekspresi: str) -> str:
    """Menghitung ekspresi matematika aman secara presisi."""
    try:
        clean_expr = ekspresi.strip().replace("^", "**")
        clean_expr = re.sub(r"(\d+)\s*!", r"factorial(\1)", clean_expr)
        parsed = ast.parse(clean_expr, mode="eval")
        hasil = _eval_expr(parsed.body)
        return f"{hasil}"
    except Exception as e:
        return f"Error kalkulator: {e}"


# ---------------------------------------------------------------- waktu & tanggal
def waktu_sekarang(zona: str = "Asia/Jakarta") -> str:
    """Mendapatkan informasi tanggal, hari, waktu, dan zona waktu saat ini."""
    try:
        target_tz = ZoneInfo(zona)
        sekarang = datetime.now(target_tz)
        hari_map = {
            "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
            "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
        }
        bulan_map = {
            "January": "Januari", "February": "Februari", "March": "Maret",
            "April": "April", "May": "Mei", "June": "Juni",
            "July": "Juli", "August": "Agustus", "September": "September",
            "October": "Oktober", "November": "November", "December": "Desember"
        }
        hari = hari_map.get(sekarang.strftime("%A"), sekarang.strftime("%A"))
        bulan = bulan_map.get(sekarang.strftime("%B"), sekarang.strftime("%B"))
        format_tgl = sekarang.strftime(f"{hari}, %d {bulan} %Y | Pukul %H:%M:%S %Z")
        return format_tgl
    except Exception:
        return "Zona waktu tidak valid. Gunakan format seperti 'Asia/Jakarta', 'Asia/Makassar', 'Asia/Jayapura', 'UTC'."


# ---------------------------------------------------------------- pencarian web (DuckDuckGo)
def cari_web(kueri: str, jumlah: int = 5) -> str:
    """Mencari informasi terkini dari internet menggunakan DuckDuckGo."""
    if DDGS is None:
        return "Modul pencarian web belum terpasang."
    try:
        ddgs_inst = DDGS()
        hasil = list(ddgs_inst.text(kueri, max_results=jumlah))
            
        if not hasil:
            return f"Tidak ditemukan hasil penelusuran untuk kueri: '{kueri}'."
            
        output = [f"=== Hasil Pencarian Web untuk: '{kueri}' ==="]
        for i, h in enumerate(hasil, 1):
            title = h.get("title", "Tanpa Judul")
            href = h.get("href", "")
            body = h.get("body", "").strip()
            output.append(f"[{i}] {title}\nURL: {href}\nRingkasan: {body}")
            
        return "\n\n".join(output)
    except Exception as e:
        return f"Gagal melakukan pencarian web: {e}"


# ---------------------------------------------------------------- pembaca url web
def _url_aman(url: str) -> tuple[bool, str]:
    """Tolak URL non-http(s) dan host internal/privat (perlindungan SSRF)."""
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False, "Hanya URL http/https yang didukung."
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "Akses ke alamat jaringan internal diblokir."
        return True, ""
    except Exception as e:
        return False, f"URL tidak dapat diverifikasi: {e}"


def baca_halaman_web(url: str) -> str:
    """Mengambil dan mengekstrak teks utama dari sebuah halaman URL web."""
    aman, alasan = _url_aman(url)
    if not aman:
        return f"Gagal membaca URL '{url}': {alasan}"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r = requests.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Bersihkan elemen non-konten
        for elem in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "svg"]):
            elem.decompose()
            
        title = soup.title.string.strip() if soup.title and soup.title.string else "Tanpa Judul"
        
        # Ambil teks paragraf dan heading
        paragraphs = []
        for p in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            txt = p.get_text(strip=True)
            if txt and len(txt) > 25:
                paragraphs.append(txt)
                
        if not paragraphs:
            teks = " ".join(soup.get_text(separator=" ").split())
        else:
            teks = "\n".join(paragraphs)
            
        teks_terpotong = teks[:7500]
        return f"=== Judul: {title} ===\nURL: {url}\n\nKonten:\n{teks_terpotong}"
    except Exception as e:
        return f"Gagal membaca URL '{url}': {e}"


# ---------------------------------------------------------------- ensiklopedia Wikipedia
def ringkasan_wikipedia(kueri: str, bahasa: str = "id") -> str:
    """Mencari ringkasan ensiklopedia Wikipedia yang terverifikasi dan faktual."""
    search_url = f"https://{bahasa}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": kueri,
        "format": "json",
        "utf8": 1,
        "srlimit": 1
    }
    headers = {"User-Agent": "NexusAI/3.0 (contact: nexus-ai@example.com)"}
    try:
        r = requests.get(search_url, params=params, headers=headers, timeout=10)
        data = r.json()
        results = data.get("query", {}).get("search", [])
        
        if not results:
            if bahasa == "id":
                return ringkasan_wikipedia(kueri, bahasa="en")
            return f"Tidak ditemukan artikel Wikipedia untuk '{kueri}'."
            
        title = results[0]["title"]
        summary_url = f"https://{bahasa}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}"
        s_res = requests.get(summary_url, headers=headers, timeout=10)
        s_data = s_res.json()
        
        extract = s_data.get("extract", "Tidak ada ringkasan teks.")
        page_url = s_data.get("content_urls", {}).get("desktop", {}).get("page", "")
        
        return f"=== Wikipedia: {title} ({bahasa.upper()}) ===\n{extract}\n\nSumber Resmi: {page_url}"
    except Exception as e:
        return f"Gagal mencari di Wikipedia: {e}"


# ---------------------------------------------------------------- cuaca real-time (Open-Meteo)
def cuaca(kota: str) -> str:
    """Mengambil data cuaca saat ini dan prakiraan 3 hari untuk suatu kota."""
    try:
        g = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": kota, "count": 1, "language": "id"},
            timeout=10,
        ).json()
        
        if not g.get("results"):
            return f"Kota atau wilayah '{kota}' tidak ditemukan pada sistem geocoding."
            
        k = g["results"][0]
        nama_lokasi = f"{k.get('name')}, {k.get('admin1', '')} {k.get('country', '')}".strip()
        
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": k["latitude"],
                "longitude": k["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto",
                "forecast_days": 3,
            },
            timeout=10,
        ).json()
        
        cur = w.get("current", {})
        daily = w.get("daily", {})
        
        laporan = [
            f"=== Informasi Cuaca: {nama_lokasi} ===",
            f"• Suhu Saat Ini: {cur.get('temperature_2m')} °C (Terasa seperti {cur.get('apparent_temperature')} °C)",
            f"• Kelembapan Udara: {cur.get('relative_humidity_2m')} %",
            f"• Kecepatan Angin: {cur.get('wind_speed_10m')} km/jam",
            f"• Curah Hujan Sekarang: {cur.get('precipitation')} mm",
            "\nPrakiraan Cuaca 3 Hari Kedepan:"
        ]
        
        dates = daily.get("time", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        p_sum = daily.get("precipitation_sum", [])
        
        for i in range(len(dates)):
            laporan.append(f"- {dates[i]}: Min {t_min[i]}°C / Max {t_max[i]}°C | Prediksi Hujan: {p_sum[i]} mm")
            
        return "\n".join(laporan)
    except Exception as e:
        return f"Gagal mengambil data cuaca untuk '{kota}': {e}"


# ---------------------------------------------------------------- eksekusi python aman
def eksekusi_python(kode: str) -> str:
    """Menjalankan snippet Python di proses terpisah (mode isolated, timeout 8 detik).

    Catatan: ini membatasi waktu & output, tetapi BUKAN sandbox keamanan penuh.
    Untuk produksi multi-user, jalankan di container/VM terisolasi.
    """
    larang = ("import os", "import sys", "import subprocess", "import socket",
              "import shutil", "__import__", "open(", "eval(", "exec(")
    if any(k in kode for k in larang):
        return "Kode ditolak: penggunaan modul/fungsi sistem tidak diizinkan."
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", kode],
            capture_output=True, text=True, timeout=8,
        )
        keluaran = (proc.stdout or "").strip()
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            return f"Error eksekusi Python: {err[-1] if err else 'tidak diketahui'}"
        return keluaran[:4000] or "Kode berhasil dieksekusi tanpa output (gunakan print())."
    except subprocess.TimeoutExpired:
        return "Eksekusi dihentikan: melebihi batas waktu 8 detik."
    except Exception as e:
        return f"Error eksekusi Python: {type(e).__name__}: {e}"


# ---------------------------------------------------------------- scratchpad memory
_SCRATCHPAD = {}


def catatan_scratchpad(aksi: str, kunci: str = "", konten: str = "") -> str:
    """Menyimpan atau membaca catatan/memori sementara sesi ini."""
    aksi = aksi.lower().strip()
    if aksi == "simpan":
        if not kunci:
            return "Kunci catatan tidak boleh kosong."
        _SCRATCHPAD[kunci] = konten
        return f"Catatan '{kunci}' berhasil disimpan ke memori Nexus."
    elif aksi == "baca":
        if kunci in _SCRATCHPAD:
            return f"Catatan [{kunci}]:\n{_SCRATCHPAD[kunci]}"
        return f"Catatan '{kunci}' tidak ditemukan di memori."
    elif aksi == "daftar":
        if not _SCRATCHPAD:
            return "Memori catatan masih kosong."
        return "Daftar catatan tersimpan:\n" + "\n".join(f"- {k}" for k in _SCRATCHPAD.keys())
    elif aksi == "hapus":
        if kunci in _SCRATCHPAD:
            del _SCRATCHPAD[kunci]
            return f"Catatan '{kunci}' berhasil dihapus."
        return f"Catatan '{kunci}' tidak ditemukan."
    return "Aksi tidak valid. Pilihan aksi: 'simpan', 'baca', 'daftar', 'hapus'."


# ---------------------------------------------------------------- registry tools
FUNCTIONS = {
    "kalkulator": kalkulator,
    "waktu_sekarang": waktu_sekarang,
    "cari_web": cari_web,
    "baca_halaman_web": baca_halaman_web,
    "ringkasan_wikipedia": ringkasan_wikipedia,
    "cuaca": cuaca,
    "eksekusi_python": eksekusi_python,
    "catatan_scratchpad": catatan_scratchpad,
}


def _tool(name: str, desc: str, props: dict, required: list):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


TOOLS = [
    _tool(
        "kalkulator",
        "Menghitung ekspresi matematika presisi, misal '(12.5 + 4) * 3', 'sqrt(144)', 'log10(1000)', 'sin(pi/2)'.",
        {"ekspresi": {"type": "string", "description": "Formula atau ekspresi matematika"}},
        ["ekspresi"]
    ),
    _tool(
        "waktu_sekarang",
        "Mendapatkan waktu, hari, tanggal, dan zona waktu saat ini.",
        {"zona": {"type": "string", "description": "Zona waktu IANA, default 'Asia/Jakarta' (contoh: 'Asia/Makassar', 'UTC', 'America/New_York')"}},
        []
    ),
    _tool(
        "cari_web",
        "Mencari informasi berita, fakta, atau data terbaru dari internet secara langsung via DuckDuckGo.",
        {"kueri": {"type": "string", "description": "Kata kunci pencarian yang spesifik"}},
        ["kueri"]
    ),
    _tool(
        "baca_halaman_web",
        "Membaca dan mengekstrak teks isi konten utama dari tautan URL website.",
        {"url": {"type": "string", "description": "URL lengkap yang ingin dibaca (contoh: https://example.com/artikel)"}},
        ["url"]
    ),
    _tool(
        "ringkasan_wikipedia",
        "Mencari ensiklopedia terverifikasi di Wikipedia mengenai tokoh, sejarah, sains, konsep, atau istilah.",
        {
            "kueri": {"type": "string", "description": "Topik atau judul ensiklopedia yang ingin dicari"},
            "bahasa": {"type": "string", "description": "Kode bahasa: 'id' untuk Indonesia, 'en' untuk Inggris (default 'id')"}
        },
        ["kueri"]
    ),
    _tool(
        "cuaca",
        "Melihat cuaca saat ini beserta prakiraan suhu dan hujan 3 hari ke depan untuk kota tertentu.",
        {"kota": {"type": "string", "description": "Nama kota atau wilayah (contoh: 'Bandung', 'Tokyo', 'London')"}},
        ["kota"]
    ),
    _tool(
        "eksekusi_python",
        "Menjalankan kode Python ringan secara aman untuk analisis data, manipulasi string, logika, atau algoritma.",
        {"kode": {"type": "string", "description": "Snippet kode Python yang valid"}},
        ["kode"]
    ),
    _tool(
        "catatan_scratchpad",
        "Menyimpan atau membaca catatan kunci dalam sesi ini agar Nexus dapat mengingat instruksi atau informasi penting.",
        {
            "aksi": {"type": "string", "description": "Aksi yang diinginkan: 'simpan', 'baca', 'daftar', atau 'hapus'"},
            "kunci": {"type": "string", "description": "Nama kunci/kategori catatan (opsional bila aksi 'daftar')"},
            "konten": {"type": "string", "description": "Teks isi catatan (wajib bila aksi 'simpan')"}
        },
        ["aksi"]
    ),
]


def jalankan_tool(nama: str, argumen: dict) -> str:
    """Mengeksekusi tool berdasarkan nama dan argumen yang diberikan model."""
    fn = FUNCTIONS.get(nama)
    if not fn:
        return f"Tool '{nama}' tidak terdaftar pada sistem Nexus."
    try:
        return str(fn(**argumen))
    except TypeError as e:
        return f"Kesalahan argumen untuk tool '{nama}': {e}"
    except Exception as e:
        return f"Terjadi kesalahan saat menjalankan tool '{nama}': {e}"


# ---------------------------------------------------------------- ekstraksi file
def ekstrak_teks(nama: str, data: bytes) -> str:
    """Mengekstrak teks dari berbagai format file: PDF, DOCX, CSV, JSON, TXT, MD."""
    n = nama.lower()
    
    # 1. Dokumen PDF
    if n.endswith(".pdf"):
        if PdfReader is None:
            return "Modul pypdf belum terpasang."
        try:
            reader = PdfReader(io.BytesIO(data))
            pages_text = []
            for idx, p in enumerate(reader.pages):
                txt = p.extract_text()
                if txt:
                    pages_text.append(f"--- Halaman {idx + 1} ---\n{txt}")
            return "\n\n".join(pages_text) if pages_text else "File PDF terbaca tetapi tidak ada teks yang dapat diekstrak."
        except Exception as e:
            return f"Error membaca PDF '{nama}': {e}"
            
    # 2. Dokumen DOCX
    if n.endswith(".docx"):
        if Document is None:
            return "Modul python-docx belum terpasang."
        try:
            doc = Document(io.BytesIO(data))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs) if paragraphs else "File DOCX terbaca tetapi kosong."
        except Exception as e:
            return f"Error membaca DOCX '{nama}': {e}"
            
    # 3. CSV File
    if n.endswith(".csv"):
        try:
            text_stream = io.StringIO(data.decode("utf-8", errors="ignore"))
            reader = list(csv.reader(text_stream))
            if not reader:
                return "File CSV kosong."
            total_rows = len(reader)
            headers = reader[0]
            preview_rows = reader[1:31]  # ambil maksimal 30 baris pertama
            
            output = [
                f"File CSV: {nama} (Total {total_rows} baris, {len(headers)} kolom)",
                f"Header: {', '.join(headers)}",
                "\nPratinjau Data (maks 30 baris):"
            ]
            for row in preview_rows:
                output.append(" | ".join(row))
            if total_rows > 31:
                output.append(f"\n... ({total_rows - 31} baris lainnya dipotong untuk efisiensi)")
            return "\n".join(output)
        except Exception as e:
            return f"Error membaca CSV '{nama}': {e}"
            
    # 4. JSON File
    if n.endswith(".json"):
        try:
            obj = json.loads(data.decode("utf-8", errors="ignore"))
            return json.dumps(obj, indent=2, ensure_ascii=False)[:15000]
        except Exception as e:
            return f"Error membaca JSON '{nama}': {e}"
            
    # 5. Teks umum (TXT, MD, PY, HTML, dll)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore")
