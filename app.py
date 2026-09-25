import os
import sqlite3
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "fundacion.db"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

app = FastAPI(title="Colombia Prospera")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: set[str] = set()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mensajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                email TEXT NOT NULL,
                mensaje TEXT NOT NULL,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voluntarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                area TEXT NOT NULL,
                nota TEXT,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aliados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organizacion TEXT NOT NULL,
                email TEXT NOT NULL,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS donaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                email TEXT NOT NULL,
                monto INTEGER NOT NULL,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS boletin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                creado TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS noticias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                titulo TEXT NOT NULL,
                fecha TEXT NOT NULL,
                texto TEXT NOT NULL,
                imagen TEXT NOT NULL
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM noticias").fetchone()[0]
        if count == 0:
            seed = [
                ("educacion", "Título de noticia", "2026-01-01", "Texto de referencia.", "edu.jpg"),
                ("campo", "Título de noticia", "2026-01-01", "Texto de referencia.", "campo.jpg"),
                ("territorio", "Título de noticia", "2026-01-01", "Texto de referencia.", "hero-3.jpg"),
                ("educacion", "Título de noticia", "2026-01-01", "Texto de referencia.", "news-becas.jpg"),
                ("campo", "Título de noticia", "2026-01-01", "Texto de referencia.", "impact.jpg"),
                ("territorio", "Título de noticia", "2026-01-01", "Texto de referencia.", "news-agua.jpg"),
            ]
            conn.executemany(
                "INSERT INTO noticias (categoria, titulo, fecha, texto, imagen) VALUES (?,?,?,?,?)",
                seed,
            )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ok(**extra):
    return JSONResponse({"ok": True, **extra})


def err(msg: str, status: int = 400):
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


def logged_in(request: Request) -> bool:
    token = request.cookies.get("cp_admin")
    return bool(token and token in SESSIONS)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/noticias")
def api_noticias():
    with db() as conn:
        rows = conn.execute(
            "SELECT categoria, titulo, fecha, texto, imagen FROM noticias ORDER BY fecha DESC, id DESC"
        ).fetchall()
    return [
        {
            "cat": r["categoria"],
            "title": r["titulo"],
            "date": r["fecha"],
            "text": r["texto"],
            "img": "/static/" + r["imagen"],
        }
        for r in rows
    ]


@app.post("/api/contacto")
async def api_contacto(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()
    msg = str(payload.get("msg") or "").strip()
    if len(name) < 2 or "@" not in email or len(msg) < 12:
        return err("Datos incompletos.")
    with db() as conn:
        conn.execute(
            "INSERT INTO mensajes (nombre, email, mensaje, creado) VALUES (?,?,?,?)",
            (name, email, msg, now_iso()),
        )
    return ok()


@app.post("/api/voluntariado")
async def api_voluntariado(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    role = str(payload.get("role") or "").strip()
    note = str(payload.get("note") or "").strip()
    if len(name) < 2 or not role:
        return err("Datos incompletos.")
    with db() as conn:
        conn.execute(
            "INSERT INTO voluntarios (nombre, area, nota, creado) VALUES (?,?,?,?)",
            (name, role, note, now_iso()),
        )
    return ok()


@app.post("/api/aliado")
async def api_aliado(payload: dict = Body(...)):
    org = str(payload.get("org") or "").strip()
    email = str(payload.get("email") or "").strip()
    if len(org) < 2 or "@" not in email:
        return err("Datos incompletos.")
    with db() as conn:
        conn.execute(
            "INSERT INTO aliados (organizacion, email, creado) VALUES (?,?,?)",
            (org, email, now_iso()),
        )
    return ok()


@app.post("/api/donacion")
async def api_donacion(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip()
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if len(name) < 2 or "@" not in email:
        return err("Datos incompletos.")
    if amount < 10000:
        return err("Monto mínimo: $10.000.")
    with db() as conn:
        conn.execute(
            "INSERT INTO donaciones (nombre, email, monto, creado) VALUES (?,?,?,?)",
            (name, email, amount, now_iso()),
        )
    return ok()


@app.post("/api/boletin")
async def api_boletin(payload: dict = Body(...)):
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        return err("Correo no válido.")
    with db() as conn:
        exists = conn.execute("SELECT id FROM boletin WHERE email = ?", (email,)).fetchone()
        if exists:
            return err("Ya registrado.", 409)
        conn.execute("INSERT INTO boletin (email, creado) VALUES (?,?)", (email, now_iso()))
    return ok()


def render_login(error: str = "") -> HTMLResponse:
    html = (TEMPLATES / "login.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__ERROR__", error))


def render_admin(stats: str, sections: str) -> HTMLResponse:
    html = (TEMPLATES / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__STATS__", stats).replace("__SECTIONS__", sections))


def table(title: str, headers: list[str], rows: list[tuple]) -> str:
    if not rows:
        body = f'<p class="empty">Sin registros.</p>'
    else:
        head = "".join(f"<th>{h}</th>" for h in headers)
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        body = f"<table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table>"
    return f"<section><h2>{title}</h2>{body}</section>"


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not logged_in(request):
        return render_login()
    with db() as conn:
        msgs = conn.execute("SELECT creado, nombre, email, mensaje FROM mensajes ORDER BY id DESC").fetchall()
        vols = conn.execute("SELECT creado, nombre, area, nota FROM voluntarios ORDER BY id DESC").fetchall()
        allies = conn.execute("SELECT creado, organizacion, email FROM aliados ORDER BY id DESC").fetchall()
        gifts = conn.execute("SELECT creado, nombre, email, monto FROM donaciones ORDER BY id DESC").fetchall()
        news = conn.execute("SELECT creado, email FROM boletin ORDER BY id DESC").fetchall()
        counts = {
            "Mensajes": len(msgs),
            "Voluntarios": len(vols),
            "Aliados": len(allies),
            "Donaciones": len(gifts),
            "Boletín": len(news),
        }
    stats = "".join(f'<div class="stat"><b>{v}</b>{k}</div>' for k, v in counts.items())
    sections = "".join(
        [
            table("Contacto", ["Fecha", "Nombre", "Correo", "Mensaje"], [tuple(r) for r in msgs]),
            table("Voluntariado", ["Fecha", "Nombre", "Área", "Nota"], [tuple(r) for r in vols]),
            table("Aliados", ["Fecha", "Organización", "Correo"], [tuple(r) for r in allies]),
            table(
                "Donaciones (intención)",
                ["Fecha", "Nombre", "Correo", "Monto"],
                [(r[0], r[1], r[2], f"${r[3]:,}".replace(",", ".")) for r in gifts],
            ),
            table("Boletín", ["Fecha", "Correo"], [tuple(r) for r in news]),
        ]
    )
    return render_admin(stats, sections)


@app.post("/admin/login")
def admin_login(password: str = Form(...)):
    if not secrets.compare_digest(password, ADMIN_PASSWORD):
        return render_login('<p class="err">Contraseña incorrecta.</p>')
    token = secrets.token_urlsafe(32)
    SESSIONS.add(token)
    res = RedirectResponse("/admin", status_code=303)
    res.set_cookie(
        "cp_admin",
        token,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("RENDER") == "true",
    )
    return res


@app.get("/admin/salir")
def admin_logout(request: Request, response: Response):
    token = request.cookies.get("cp_admin")
    if token:
        SESSIONS.discard(token)
    res = RedirectResponse("/admin", status_code=303)
    res.delete_cookie("cp_admin")
    return res
