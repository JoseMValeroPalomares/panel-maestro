"""
Panel de demostración con datos inventados, en un directorio temporal: tus datos ni se leen ni se tocan.

    python -m scripts.demo              # http://127.0.0.1:8900 (Ctrl+C para y lo borra todo)
    python -m scripts.demo --capturas   # rehace las capturas de docs/img/ (requirements-dev.txt y Chromium de Playwright)
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PORT = 8900
BASE = f"http://127.0.0.1:{PORT}"
IMG_DIR = ROOT / "docs" / "img"

NOTES = {
    "leyes-de-newton": ("Leyes de Newton", "Física - Mecánica", ["física", "repaso"], """
# Leyes de Newton

1. **Inercia:** sin fuerza neta, un cuerpo mantiene su velocidad.
2. **Dinámica:** la fuerza neta es masa por aceleración.
3. **Acción y reacción:** toda fuerza tiene su pareja, igual y de sentido contrario.

$$\\vec{F} = m\\,\\vec{a}$$

Relacionado: [[energia-y-trabajo]].

- [ ] Hacer los problemas del tema 2
- [x] Pasar a limpio los apuntes
"""),
    "energia-y-trabajo": ("Energía y trabajo", "Física - Mecánica", ["física"], """
# Energía y trabajo

El trabajo de una fuerza es $W = \\int \\vec{F} \\cdot d\\vec{r}$ y la energía cinética, $E_c = \\frac{1}{2} m v^2$.

Parte de [[leyes-de-newton]]; se usa mucho en [[circuitos-rc]].
"""),
    "circuitos-rc": ("Circuitos RC", "Electrónica", ["electrónica", "repaso"], """
# Circuitos RC

La tensión del condensador sube con constante de tiempo $\\tau = RC$.

```python
import math

def carga(t, v0, r, c):
    return v0 * (1 - math.exp(-t / (r * c)))
```

Ver también [[energia-y-trabajo]].
"""),
    "listas-en-python": ("Listas en Python", "Programación - Python", ["python"], """
# Listas en Python

```python
pares = [n for n in range(10) if n % 2 == 0]
```

Las listas son mutables; las tuplas, no. Siguiente: [[diccionarios-en-python]].
"""),
    "diccionarios-en-python": ("Diccionarios en Python", "Programación - Python", ["python"], """
# Diccionarios en Python

Tablas hash: buscar por clave cuesta O(1) de media. Vienen de [[listas-en-python]].
"""),
    "ideas-para-el-viaje": ("Ideas para el viaje", "Personal", ["viajes"], """
# Ideas para el viaje

- [ ] Mirar trenes a Lisboa
- [ ] Reservar el alojamiento
- [ ] Hacer una lista de museos
"""),
}

TASKS = [
    ("Entregar la práctica de electrónica", "tarea", "alta", 1, "Estudios"),
    ("Repasar el tema 3 de física", "tarea", "media", 2, "Estudios"),
    ("Pedir cita en el dentista", "tarea", "media", 3, "Personal"),
    ("Comprar un cable USB-C", "tarea", "baja", None, "Casa"),
    ("Renovar el abono de transporte", "tarea", "alta", 0, "Personal"),
    ("Un script que ordene las fotos por fecha", "idea", None, None, "Proyectos"),
    ("Montar un huerto en el balcón", "idea", None, None, "Casa"),
    ("Aprender acordes de jazz al piano", "idea", None, None, "Personal"),
]

STEPS = {"Entregar la práctica de electrónica": ["Montar el circuito", "Medir con el osciloscopio", "Escribir la memoria"],
         "Repasar el tema 3 de física": ["Resumen del tema", "Ejercicios impares"],
         "Un script que ordene las fotos por fecha": ["Leer la fecha de cada foto", "Crear una carpeta por mes"],
         "Montar un huerto en el balcón": ["Elegir las macetas", "Comprar semillas de tomate"]}

EVENTS = [(0, "10:00", "11:30", "Clase de electrónica"), (0, "17:00", "18:00", "Gimnasio"), (1, "09:30", "11:00", "Laboratorio de física"),
          (1, "19:00", "20:30", "Cena con amigos"), (2, "12:00", "13:00", "Tutoría"), (3, "16:00", "18:00", "Grupo de estudio"),
          (4, "11:00", "12:00", "Dentista"), (5, "10:00", "13:00", "Excursión"), (-1, "18:00", "19:00", "Clase de piano")]

ACCOUNTS = [("Banco", "banco", 1240.50), ("Efectivo", "efectivo", 85), ("Ahorro", "ahorro", 3200)]
MOVEMENTS = [(-1, 3.20, "gasto", "Comida", "Café y tostada"), (-2, 42.75, "gasto", "Supermercado", "Compra semanal"),
             (-4, 18, "gasto", "Transporte", "Abono"), (-6, 24.90, "gasto", "Ocio", "Entradas de cine"),
             (-8, 650, "ingreso", "Nómina", "Trabajo de tarde"), (-10, 15.99, "gasto", "Universidad", "Fotocopias y material"),
             (-12, 38.40, "gasto", "Supermercado", "Compra semanal"), (-40, 31.20, "gasto", "Ocio", "Concierto"),
             (-44, 640, "ingreso", "Nómina", "Trabajo de tarde"), (-48, 52.10, "gasto", "Supermercado", "Compra semanal")]

INGREDIENTS = {  # nombre: categoría, kcal, proteína, hidratos, grasa (por 100 g)
    "Pechuga de pollo": ("Carnes", 110, 23, 0, 2), "Salmón": ("Pescado", 208, 20, 0, 13), "Merluza": ("Pescado", 86, 17, 0, 2),
    "Huevo": ("Huevos", 143, 13, 1, 10), "Lentejas cocidas": ("Legumbres", 116, 9, 20, 0.4), "Garbanzos cocidos": ("Legumbres", 164, 9, 27, 3),
    "Arroz": ("Cereales", 130, 2.7, 28, 0.3), "Pasta": ("Cereales", 158, 5.8, 31, 0.9), "Patata": ("Verduras", 86, 2, 20, 0.1),
    "Pan integral": ("Cereales", 250, 9, 45, 3.5), "Avena": ("Cereales", 380, 13, 66, 7), "Yogur natural": ("Lácteos", 61, 3.5, 4.7, 3.3),
    "Plátano": ("Fruta", 89, 1.1, 23, 0.3), "Manzana": ("Fruta", 52, 0.3, 14, 0.2), "Tomate": ("Verduras", 18, 0.9, 3.9, 0.2),
    "Espinacas": ("Verduras", 23, 2.9, 3.6, 0.4), "Brócoli": ("Verduras", 34, 2.8, 7, 0.4), "Aceite de oliva": ("Grasas", 884, 0, 0, 100),
    "Nueces": ("Frutos secos", 654, 15, 14, 65),
}
MEALS = [
    ("Avena con plátano y nueces", "desayuno", {"Avena": 70, "Plátano": 100, "Nueces": 20, "Yogur natural": 125}),
    ("Tostadas con tomate y huevo", "desayuno", {"Pan integral": 80, "Tomate": 80, "Huevo": 120, "Aceite de oliva": 8}),
    ("Yogur con manzana y avena", "desayuno", {"Yogur natural": 200, "Manzana": 150, "Avena": 40}),
    ("Pollo al horno con patata", "comida", {"Pechuga de pollo": 180, "Patata": 250, "Brócoli": 120, "Aceite de oliva": 10}),
    ("Lentejas estofadas", "comida", {"Lentejas cocidas": 300, "Patata": 100, "Tomate": 80, "Aceite de oliva": 10}),
    ("Pasta con salmón y espinacas", "comida", {"Pasta": 220, "Salmón": 120, "Espinacas": 80, "Aceite de oliva": 8}),
    ("Arroz con pollo y verduras", "comida", {"Arroz": 250, "Pechuga de pollo": 150, "Brócoli": 100, "Aceite de oliva": 10}),
    ("Garbanzos con espinacas", "comida", {"Garbanzos cocidos": 280, "Espinacas": 120, "Tomate": 80, "Aceite de oliva": 10}),
    ("Merluza con ensalada", "cena", {"Merluza": 200, "Tomate": 150, "Patata": 120, "Aceite de oliva": 10}),
    ("Tortilla de espinacas", "cena", {"Huevo": 180, "Espinacas": 120, "Pan integral": 50, "Aceite de oliva": 8}),
    ("Salmón con brócoli", "cena", {"Salmón": 160, "Brócoli": 200, "Arroz": 100}),
    ("Pollo con ensalada de tomate", "cena", {"Pechuga de pollo": 170, "Tomate": 200, "Pan integral": 40, "Aceite de oliva": 10}),
    ("Yogur con nueces", "merienda", {"Yogur natural": 200, "Nueces": 20}),
    ("Plátano y tostada", "merienda", {"Plátano": 120, "Pan integral": 50}),
]
RESOURCES = [("https://example.com/video-fisica", "Física", "Mecánica clásica en 20 minutos", "Un repaso rápido de las leyes de Newton."),
             ("https://example.com/curso-python", "Programación", "Curso de Python desde cero", "Curso gratuito con ejercicios."),
             ("https://example.com/teoria-circuitos", "Electrónica", "Teoría de circuitos", "Apuntes con ejemplos resueltos."),
             ("https://example.com/huerto-urbano", "Casa", "Guía del huerto urbano", "Qué plantar en cada estación.")]

BOARD = {"format": 2, "strokes": [], "nodes": [
    {"id": "a", "kind": "sticky", "x": 60, "y": 60, "w": 200, "h": 110, "text": "Idea: reloj con pantalla e-ink"},
    {"id": "b", "kind": "rect", "x": 340, "y": 80, "w": 180, "h": 70, "text": "Elegir componentes"},
    {"id": "c", "kind": "rect", "x": 600, "y": 80, "w": 180, "h": 70, "text": "Prototipo"},
    {"id": "d", "kind": "diamond", "x": 340, "y": 240, "w": 180, "h": 110, "text": "¿Funciona?"},
    {"id": "e", "kind": "ellipse", "x": 600, "y": 260, "w": 180, "h": 80, "text": "Montar la caja"}],
    "edges": [{"id": "e1", "from": "a", "to": "b", "color": "#89b4fa", "width": 2, "head": "arrow"},
              {"id": "e2", "from": "b", "to": "c", "color": "#89b4fa", "width": 2, "head": "arrow"},
              {"id": "e3", "from": "c", "to": "d", "color": "#89b4fa", "width": 2, "head": "arrow"},
              {"id": "e4", "from": "d", "to": "e", "color": "#a6e3a1", "width": 2, "head": "arrow"}]}

# Página, ruta y espera en ms antes de la captura
PAGES = [("hoy", "/hoy", 900), ("calendario", "/calendario", 1200), ("rutinas", "/rutinas", 900), ("tareas", "/tareas", 900),
         ("inbox", "/inbox", 900), ("notas", "/?note=circuitos-rc", 1600), ("grafo", "/graph", 3500), ("baul", "/vault", 900),
         ("comidas", "/comidas/", 1500), ("economia", "/economia", 1200), ("copias", "/backups", 900)]
PHONE_PAGES = [("hoy", "/hoy", 900), ("comidas", "/comidas/", 1500), ("tareas", "/tareas", 900)]


def demo_env(tmp: Path) -> dict:
    """Todas las rutas al directorio temporal y nada de ESP32, iCloud ni dotfiles."""
    data = tmp / "data"
    return {**os.environ, "PANEL_DATA_DIR": str(data), "PANEL_NOTES_DIR": str(data / "notes"), "PANEL_BRAIN_DB": str(data / "brain.db"),
            "PANEL_COMIDAS_DB": str(tmp / "comidas.db"), "PANEL_UPLOADS_DIR": str(tmp / "uploads"), "PANEL_BACKUPS_DIR": str(tmp / "backups"),
            "PANEL_LOGS_DIR": str(tmp / "logs"), "PANEL_TRASH_DIR": str(data / "trash"), "PANEL_DOTFILES_DIR": str(tmp / "sin-dotfiles"),
            "PANEL_PROJECT_DIR": str(tmp / "sin-proyecto"),
            "PANEL_AUTH_DISABLED": "1", "PANEL_DISABLE_BRIDGES": "1", "ESP32_HOST": "", "ICLOUD_USERNAME": "", "ICLOUD_APP_PASSWORD": "",
            "PANEL_LOG_LEVEL": "WARNING"}


def start_server(tmp: Path) -> subprocess.Popen:
    (tmp / "data" / "notes").mkdir(parents=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                            cwd=ROOT, env=demo_env(tmp), stdout=subprocess.DEVNULL)
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    sys.exit("El panel de demostración no ha arrancado.")


def _ok(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def seed_notes_and_items(c: httpx.Client, today: date) -> None:
    for note_id, (title, category, tags, content) in NOTES.items():
        _ok(c.post(f"/api/notes/{note_id}", json={"title": title, "category": category, "tags": tags, "content": content.strip()}))
    for text, kind, priority, days, category in TASKS:
        due = (today + timedelta(days=days)).isoformat() if days is not None else None
        _ok(c.post("/api/items", json={"text": text, "type": kind, "priority": priority, "due_date": due, "category": category}))
    parents = {i["text"]: i for i in _ok(c.get("/api/items"))["items"]}
    for parent, steps in STEPS.items():
        for step in steps:
            _ok(c.post("/api/items", json={"text": step, "type": parents[parent]["type"], "parent_id": parents[parent]["id"]}))
    for key in ("b:manana", "b:noche"):
        _ok(c.post("/api/routine-templates/apply", json={"key": key}))
    monday = today - timedelta(days=today.weekday())
    for offset, start, end, title in EVENTS:
        day = (today + timedelta(days=offset) if offset == -1 else monday + timedelta(days=offset)).isoformat()
        _ok(c.post("/api/calendar/events", json={"title": title, "start": f"{day}T{start}", "end": f"{day}T{end}"}))


def seed_finance(c: httpx.Client, today: date) -> None:
    accounts = [_ok(c.post("/api/finance/accounts", json={"nombre": n, "tipo": t, "saldo_inicial": s}))["id"] for n, t, s in ACCOUNTS]
    for offset, amount, kind, category, concept in MOVEMENTS:
        _ok(c.post("/api/finance/movements", json={"importe": amount, "tipo": kind, "fecha": (today + timedelta(days=offset)).isoformat(),
                                                   "categoria": category, "concepto": concept, "cuenta_id": accounts[0]}))
    _ok(c.put("/api/finance/budgets/Supermercado", json={"importe": 180}))
    _ok(c.put("/api/finance/budgets/Ocio", json={"importe": 60}))
    _ok(c.post("/api/finance/recurring", json={"concepto": "Música", "importe": 10.99, "categoria": "Ocio", "dia": 5, "cuenta_id": accounts[0]}))
    _ok(c.post("/api/finance/debts", json={"persona": "Lucía", "importe": 12, "direccion": "me-deben", "concepto": "Entradas"}))
    _ok(c.post("/api/finance/wishes", json={"nombre": "Teclado mecánico", "precio": 89, "prioridad": "media"}))


def seed_meals(c: httpx.Client, today: date) -> None:
    ids = {}
    for name, (category, kcal, protein, carbs, fat) in INGREDIENTS.items():
        ids[name] = _ok(c.post("/comidas/api/ingredients", json={"nombre": name, "categoria": category, "kcal_100g": kcal, "proteinas_100g": protein,
                                                                 "carbohidratos_100g": carbs, "grasas_100g": fat}))["id"]
    for name, slot, parts in MEALS:
        _ok(c.post("/comidas/api/meals", json={"nombre": name, "franja": slot, "ingredientes": [{"ingredient_id": ids[k], "gramos": g} for k, g in parts.items()]}))
    week = (today - timedelta(days=today.weekday())).isoformat()
    _ok(c.post("/comidas/api/weekly-plan/generate", json={"semana": week, "franjas": ["desayuno", "comida", "merienda", "cena"]}))


def seed_vault(c: httpx.Client) -> None:
    for url, category, _, _ in RESOURCES:
        _ok(c.post("/api/resources", json={"url": url, "category": category}))
    time.sleep(2)  # la descarga de metadatos va en segundo plano: que acabe antes de poner los títulos
    rows = {r["url"]: r["id"] for r in _ok(c.get("/api/resources"))["resources"]}
    for url, _, title, description in RESOURCES:
        _ok(c.patch(f"/api/resources/{rows[url]}", json={"title": title, "description": description}))


def seed_board(c: httpx.Client) -> None:
    board = _ok(c.post("/api/boards", json={"name": "Proyecto: reloj"}))["id"]
    _ok(c.post(f"/api/boards/{board}/canvas", json={"data": json.dumps(BOARD)}))


def seed(client: httpx.Client) -> None:
    today = date.today()
    _ok(client.put("/api/prefs/calendar-hour-size", json={"value": "fit"}))  # todo el día a la vista
    seed_notes_and_items(client, today)
    seed_finance(client, today)
    seed_meals(client, today)
    seed_vault(client)
    seed_board(client)
    _ok(client.post("/api/backups/run"))


def _chromium() -> str | None:
    found = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))
    return os.environ.get("PLAYWRIGHT_CHROMIUM") or (found[-1] if found else None)


def take_screenshots() -> None:
    from playwright.sync_api import sync_playwright
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    shots = [("", {"width": 1440, "height": 900}, PAGES), ("movil-", {"width": 390, "height": 844}, PHONE_PAGES)]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium(), headless=True)
        for prefix, viewport, pages in shots:
            context = browser.new_context(viewport=viewport, color_scheme="dark", service_workers="block", device_scale_factor=1)
            page = context.new_page()
            for name, path, wait in pages:
                page.goto(BASE + path)
                page.wait_for_timeout(wait)
                page.screenshot(path=IMG_DIR / f"{prefix}{name}.png")
                print(f"  {prefix}{name}.png")
                if name == "tareas" and not prefix:
                    page.click("[data-view=matriz]")
                    page.wait_for_timeout(400)
                    page.screenshot(path=IMG_DIR / "tareas-cuadricula.png")
                    page.click("[data-view=lista]")
            context.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--capturas", action="store_true", help="rehace docs/img/ y termina")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="panel-demo-"))
    proc = start_server(tmp)
    try:
        with httpx.Client(base_url=BASE, timeout=30) as client:
            seed(client)
        if args.capturas:
            take_screenshots()
        else:
            print(f"Panel de demostración en {BASE} (Ctrl+C para terminar y borrarlo)")
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
