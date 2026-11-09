# -*- coding: utf-8 -*-
"""
Conversor a Markdown (local) con MarkItDown.
- Instala markitdown[all] y ftfy automáticamente si faltan.
- Convierte archivos de una carpeta, archivos arrastrados o videos de YouTube.
- Repara tildes y símbolos raros (mojibake: "canciÃ³n" -> "canción").
- Divide libros y documentos largos en un .md por capítulo (marcadores del PDF,
  índice del libro, líneas "Capítulo N" o encabezados Markdown).
Uso:  py app.py   y abre http://127.0.0.1:8765
"""
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

PORT = 8765
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- dependencias

def ensure_deps():
    needed = []
    for mod, pkg in (("markitdown", "markitdown[all]"), ("ftfy", "ftfy"), ("pypdf", "pypdf")):
        try:
            importlib.import_module(mod)
        except ImportError:
            needed.append(pkg)
    if needed:
        print(f"Instalando: {', '.join(needed)} (puede tardar unos minutos)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *needed])
        importlib.invalidate_caches()


ensure_deps()

import ftfy  # noqa: E402
from markitdown import MarkItDown  # noqa: E402

MD = MarkItDown(enable_plugins=False)

EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls", ".csv", ".json", ".xml",
    ".html", ".htm", ".txt", ".epub", ".zip", ".msg", ".ipynb", ".rtf",
    ".jpg", ".jpeg", ".png", ".mp3", ".wav", ".m4a",
}

# ------------------------------------------------------------------ limpieza

def clean_text(text: str, fix: bool, compact: bool) -> str:
    if fix:
        # Repara mojibake (Ã¡ -> á, â€œ -> "), comillas tipográficas, ligaduras, anchos raros
        text = ftfy.fix_text(text, normalization="NFC")
        text = text.replace(" ", " ").replace("​", "").replace("﻿", "")
        text = unicodedata.normalize("NFC", text)
    if compact:
        text = re.sub(r"!\[[^\]]*\]\(data:[^)]+\)", "", text)   # imágenes base64 incrustadas
        text = re.sub(r"[ \t]+\n", "\n", text)                   # espacios al final de línea
        text = re.sub(r"[ \t]{2,}", " ", text)                   # espacios repetidos
        text = re.sub(r"\n{3,}", "\n\n", text)                   # líneas en blanco repetidas
        text = re.sub(r"\|(\s*\|)+\s*$", "|", text, flags=re.M)   # celdas vacías al final de tablas
        text = text.strip() + "\n"
    return text


def convert(source: str, opts: dict) -> str:
    kwargs = {}
    if "youtube.com" in source or "youtu.be" in source:
        kwargs["youtube_transcript_languages"] = [l.strip() for l in opts.get("langs", "es,en").split(",") if l.strip()]
    result = MD.convert(source, **kwargs)
    text = result.text_content or ""
    if result.title and not text.lstrip().startswith("#"):
        text = f"# {result.title}\n\n{text}"
    return clean_text(text, opts.get("fix", True), opts.get("compact", True))


def save_md(src: Path, text: str, out_dir: str | None) -> str:
    folder = Path(out_dir) if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (src.stem + ".md")
    if dest.resolve() == src.resolve():
        dest = folder / (src.stem + ".converted.md")
    dest.write_text(text, encoding="utf-8")
    return str(dest)


def stats(text: str) -> dict:
    return {"chars": len(text), "tokens": max(1, len(text) // 4)}

# ------------------------------------------------------------------ capítulos

CHAPTER_RE = re.compile(
    r"^\s*(?:#+\s*)?(cap[ií]tulo|chapter|parte|part|lecci[oó]n|unidad|tema|libro|book)\s+"
    r"([0-9]{1,3}|[ivxlcdm]{1,7}|[a-záéíóúñ]+)\b[\s.:\-–—]*(.{0,80})$",
    re.I,
)
TOC_HEAD_RE = re.compile(
    r"^\s*(?:#+\s*)?(índice( general)?|indice( general)?|contenidos?|tabla de contenidos?|sumario|"
    r"contents|table of contents)\s*:?\s*$",
    re.I,
)
TOC_LINE_RE = re.compile(r"^(.{3,90}?)\s*(?:[.·…_ \-]{2,}|\s)(\d{1,4})$")
LEADER_RE = re.compile(r"[.·…_]{3,}\s*\d{1,4}\s*$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _slug(title: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f#\[\]()]', "", title)
    s = re.sub(r"\s+", "_", s.strip()).strip("._")
    return s[:60].rstrip("._") or "capitulo"


def _heading(title: str, body: str) -> str:
    body = body.strip()
    if _norm(body.split("\n", 1)[0].lstrip("# ")) == _norm(title):
        body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    return f"# {title}\n\n{body}\n"


def _pdf_outline(path: Path):
    """[(título, página_inicial)] a partir de los marcadores (bookmarks) del PDF."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    try:
        outline = reader.outline
    except Exception:  # noqa: BLE001
        return reader, []

    def entry(it):
        try:
            return (str(it.title).strip(), reader.get_destination_page_number(it))
        except Exception:  # noqa: BLE001
            return None

    top = [e for it in outline if not isinstance(it, list) and (e := entry(it))]
    if len(top) < 3:
        # Pocas entradas arriba (p. ej. "Parte I", "Parte II"): bajar al nivel de capítulos.
        flat, items = [], list(outline)
        for i, it in enumerate(items):
            if isinstance(it, list):
                continue
            children = items[i + 1] if i + 1 < len(items) and isinstance(items[i + 1], list) else None
            kids = [e for c in (children or []) if not isinstance(c, list) and (e := entry(c))]
            flat += kids if kids else [e for e in [entry(it)] if e]
        if len(flat) > len(top):
            top = flat

    seen, result = set(), []
    for title, page in sorted(top, key=lambda e: e[1]):
        if page is not None and page >= 0 and page not in seen and title:
            seen.add(page)
            result.append((title, page))
    return reader, result


def pdf_chapters(path: Path, opts: dict):
    """Convierte cada capítulo del PDF por separado usando sus marcadores."""
    from pypdf import PdfWriter
    reader, marks = _pdf_outline(path)
    if len(marks) < 2:
        return []
    n = len(reader.pages)
    ranges = [(t, p, marks[i + 1][1] if i + 1 < len(marks) else n) for i, (t, p) in enumerate(marks)]
    if marks[0][1] > 0:
        ranges.insert(0, ("Preliminares", 0, marks[0][1]))
    chapters = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (title, start, end) in enumerate(ranges):
            writer = PdfWriter()
            for p in range(start, max(end, start + 1)):
                writer.add_page(reader.pages[p])
            part = Path(tmp) / f"parte_{i}.pdf"
            with open(part, "wb") as f:
                writer.write(f)
            body = clean_text(MD.convert(str(part)).text_content or "", opts.get("fix", True), opts.get("compact", True))
            chapters.append((title, _heading(title, body)))
    return chapters


def _toc(lines):
    """Busca el índice al principio del texto. Devuelve (títulos, línea_final_del_índice)."""
    limit = max(80, len(lines) // 5)
    start = next((i + 1 for i, l in enumerate(lines[:limit]) if TOC_HEAD_RE.match(l)), None)
    if start is None:
        return [], -1
    titles, end, miss = [], -1, 0
    for j in range(start, min(len(lines), start + 500)):
        l = lines[j].strip().lstrip("#*- ").strip()
        if not l:
            continue
        m = TOC_LINE_RE.match(l)
        if m and not m.group(1).strip(" .").isdigit():
            titles.append(m.group(1).strip(" .·…_-"))
            end, miss = j, 0
        else:
            miss += 1
            if miss >= 4 and titles:
                break
    return titles, end


def split_text(text: str):
    """Divide un Markdown ya convertido. Devuelve (método, [(título, texto)])."""
    lines = text.split("\n")
    toc_titles, toc_end = _toc(lines)
    marks = []  # (línea_inicio, título, líneas_de_título)

    # 1) Encabezados Markdown (Word, EPUB, HTML…)
    for level in ("#", "##"):
        hs = [(i, l.lstrip("#").strip(), 1) for i, l in enumerate(lines)
              if re.match(rf"^{level}\s+\S", l) and i > toc_end]
        if len(hs) >= 3 or (len(hs) >= 2 and level == "##"):
            marks, method = hs, "encabezados del documento"
            break

    # 2) Índice del libro: buscar cada título del índice en el cuerpo
    if not marks and len(toc_titles) >= 2:
        cursor, found = toc_end + 1, []
        for t in toc_titles:
            nt = _norm(t)
            for i in range(cursor, len(lines)):
                nl = _norm(lines[i].lstrip("# "))
                if not nl or len(lines[i]) > len(t) + 40:
                    continue
                if nl == nt or nl.startswith(nt) or (nt.startswith(nl) and len(nl) >= 8 and CHAPTER_RE.match(lines[i])):
                    found.append((i, t, 1))
                    cursor = i + 1
                    break
        if len(found) >= 2:
            marks, method = found, "índice del libro"

    # 3) Líneas tipo "Capítulo 3", "CAPÍTULO III — Título", "Parte 2"
    if not marks:
        seen, found = set(), []
        for i, l in enumerate(lines):
            if i <= toc_end or len(l) > 100 or LEADER_RE.search(l):
                continue
            m = CHAPTER_RE.match(l)
            if not m:
                continue
            key = (_norm(m.group(1)), _norm(m.group(2)))
            if key in seen:
                continue
            seen.add(key)
            title, used = l.strip().lstrip("# ").strip(), 1
            if not m.group(3).strip():  # el título suele venir en la línea siguiente
                nxt = next((k for k in range(i + 1, min(i + 4, len(lines))) if lines[k].strip()), None)
                if nxt is not None and len(lines[nxt].strip()) <= 80 and not CHAPTER_RE.match(lines[nxt]):
                    title, used = f"{title}. {lines[nxt].strip().lstrip('# ')}", nxt - i + 1
            found.append((i, title, used))
        if len(found) >= 2:
            marks, method = found, "líneas «Capítulo N»"

    if not marks:
        return None, []

    chapters = []
    pre = "\n".join(lines[: marks[0][0]]).strip()
    if len(pre) > 200:
        chapters.append(("Preliminares", _heading("Preliminares", pre)))
    for k, (i, title, used) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        body = "\n".join(lines[i + used: end])
        chapters.append((title, _heading(title, body)))
    return method, chapters


def split_parts(text: str, n) -> list:
    """Divide el texto en n partes de tamaño parecido, cortando en párrafos (o frases) cercanos."""
    text = text.strip()
    n = max(2, min(int(n or 2), 200))
    size = len(text) / n
    cuts = [0]
    for k in range(1, n):
        target, win = int(size * k), max(1, int(size * 0.15))
        lo, hi = max(cuts[-1] + 1, target - win), min(len(text), target + win)
        best = target
        # Preferencia: fin de párrafo real > fin de frase > línea en blanco > salto de línea > espacio.
        # (pdfminer deja líneas en blanco entre cada renglón; solo cuentan como párrafo tras un punto.)
        for sep in (r"[.!?…:][\"»”')]?[ \t]*\n\s*\n", r"[.!?…][\"»”')]?\s+", r"\n\s*\n", r"\n", r" "):
            pos = [lo + m.end() for m in re.finditer(sep, text[lo:hi])]
            if pos:
                best = min(pos, key=lambda p: abs(p - target))
                break
        cuts.append(max(best, cuts[-1] + 1))
    cuts.append(len(text))
    pieces = [p for p in (text[a:b].strip() for a, b in zip(cuts, cuts[1:])) if p]
    total = len(pieces)
    return [(f"Parte {i} de {total}", f"# Parte {i} de {total}\n\n{p}\n") for i, p in enumerate(pieces, 1)]


def save_chapters(stem: str, chapters, folder: Path, kind: str = "capitulos") -> str:
    d = folder / f"{stem}_{kind}"
    d.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(chapters))))
    index = [f"# {stem} — índice de {'partes' if kind == 'partes' else 'capítulos'}\n"]
    for i, (title, body) in enumerate(chapters, 1):
        name = f"{i:0{width}d}_{_slug(title)}.md"
        (d / name).write_text(body, encoding="utf-8")
        index.append(f"{i}. [{title}](<{name}>) · ~{stats(body)['tokens']:,} tokens")
    (d / f"{0:0{width}d}_indice.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return str(d)


def process(src: Path, opts: dict, out_dir: Path | None) -> dict:
    """Convierte un archivo y, si se pide, lo divide.
    opts["splitMode"]: "none" | "chapters" (detectar capítulos) | "parts" (opts["parts"] partes iguales).
    out_dir=None => no guardar."""
    mode = opts.get("splitMode") or ("chapters" if opts.get("split") else "none")
    method, chapters, text = None, [], None
    if mode == "chapters" and src.suffix.lower() == ".pdf":
        chapters = pdf_chapters(src, opts)
        if chapters:
            method = "marcadores del PDF"
            text = "\n".join(body for _, body in chapters)
    if text is None:
        text = convert(str(src), opts)
        if mode == "chapters":
            method, chapters = split_text(text)
        elif mode == "parts":
            chapters = split_parts(text, opts.get("parts", 2))
            method = "partes iguales" if len(chapters) > 1 else None
            chapters = chapters if len(chapters) > 1 else []
    save = opts.get("save") and out_dir is not None
    res = {"markdown": text, "saved": None, **stats(text)}
    if chapters:
        res["method"] = method
        res["mode"] = mode
        res["chapters"] = [{"title": t, "markdown": b, **stats(b)} for t, b in chapters]
        if save:
            res["saved"] = save_chapters(src.stem, chapters, out_dir, "partes" if mode == "parts" else "capitulos")
        return res
    if mode == "parts":
        res["note"] = "El texto es demasiado corto para dividirlo; se dejó en un solo archivo."
    elif mode == "chapters":
        res["note"] = "No se detectaron capítulos; se dejó en un solo archivo."
    if save:
        res["saved"] = save_md(out_dir / src.name, text, str(out_dir))
    return res

# --------------------------------------------------------------------- servidor

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        try:
            if self.path == "/api/list":
                d = self._json()
                folder = Path(d.get("folder", "").strip().strip('"'))
                if not folder.is_dir():
                    return self._send(400, {"error": f"La carpeta no existe: {folder}"})
                pattern = "**/*" if d.get("recursive") else "*"
                files = [
                    {"path": str(p), "name": str(p.relative_to(folder)), "size": p.stat().st_size}
                    for p in sorted(folder.glob(pattern))
                    if p.is_file() and p.suffix.lower() in EXTS
                ]
                return self._send(200, {"files": files})

            if self.path == "/api/convert":
                d = self._json()
                opts = d.get("opts", {})
                if d.get("url"):
                    text = convert(d["url"].strip(), opts)
                    saved = None
                    if opts.get("save") and opts.get("outDir"):
                        name = re.sub(r"[^\w-]+", "_", d["url"].split("v=")[-1].split("/")[-1])[:40] or "youtube"
                        saved = save_md(Path(opts["outDir"]) / f"youtube_{name}", text, opts["outDir"])
                    return self._send(200, {"markdown": text, "saved": saved, **stats(text)})
                src = Path(d["path"])
                out = Path(opts["outDir"]) if opts.get("outDir") else src.parent
                return self._send(200, process(src, opts, out))

            if self.path == "/api/upload":
                name = unquote(self.headers.get("X-Filename", "archivo"))
                opts = json.loads(unquote(self.headers.get("X-Opts", "{}")))
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / Path(name).name
                    p.write_bytes(data)
                    out = Path(opts["outDir"]) if opts.get("outDir") else None
                    res = process(p, opts, out)
                return self._send(200, res)

            self._send(404, {"error": "no encontrado"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"

    class Server(ThreadingHTTPServer):
        # En Windows, reutilizar la dirección deja que varias copias compartan el puerto
        # y responda una versión vieja. Así, una segunda copia falla con un aviso claro.
        allow_reuse_address = os.name != "nt"

    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Ya hay un conversor abierto en {url}.\n"
              "Cierra esa ventana (o pulsa Ctrl+C en ella) y vuelve a ejecutar iniciar.bat.")
        sys.exit(1)
    print(f"Conversor listo en {url}  (Ctrl+C para salir)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    server.serve_forever()
