"""
Casillas «- [ ]» de las notas como elementos de la lista única (tabla inbox).

El .md manda sobre el texto, el estado, el orden y el anidado de cada casilla;
su fila en `inbox` (note_id + note_task + note_index) guarda lo que el .md no
tiene: un id estable (tablero, deshacer), prioridad, fecha y notas.
sync_note_items() rehace las filas de una nota a partir de su texto:
  1. empareja cada casilla con la fila del mismo texto (la de posición más cercana);
  2. las que quedan, por posición (así sobrevive a un cambio de texto);
  3. crea filas para las casillas nuevas y borra las de casillas que ya no están.
Anidado: una casilla sangrada bajo otra es su paso. Solo hay un nivel, así que
un nieto cuelga del antepasado de primer nivel.

NoteDoc edita el archivo línea a línea (frontmatter y resto del texto quedan
byte a byte iguales). Sin dependencias de app.main: lo usa el indexador.
"""
import re
import sqlite3

TASK_RE = re.compile(r"^(\s*)([-*+]) \[([ xX])\] (.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
INDENT = "  "


def _indent(line: str) -> int:
    s = line.expandtabs(4)
    return len(s) - len(s.lstrip(" "))


def parse_tasks(content: str) -> list[dict]:
    """Casillas en orden: k (posición), line, indent, text, done, parent (k del padre o None).
    Se ignoran las de los bloques de código, igual que al pintar la nota."""
    lines = (content or "").splitlines()
    tasks, by_line, fence = [], {}, False
    for i, raw in enumerate(lines):
        if FENCE_RE.match(raw):
            fence = not fence
            continue
        m = None if fence else TASK_RE.match(raw)
        if m:
            t = {"k": len(tasks), "line": i, "indent": _indent(raw), "text": m.group(4), "done": m.group(3) != " ", "parent": None}
            tasks.append(t)
            by_line[i] = t
    for t in tasks:
        if not t["indent"]:
            continue
        for j in range(t["line"] - 1, -1, -1):
            if not lines[j].strip():
                continue
            ind = _indent(lines[j])
            if ind >= t["indent"]:
                continue
            p = by_line.get(j)
            if p:
                t["parent"] = p["k"] if p["parent"] is None else p["parent"]
            break
    return tasks


# ─────────────────────────────────────────────
# Filas de la tabla inbox
# ─────────────────────────────────────────────

def sync_note_items(conn: sqlite3.Connection, note_id: str, content: str | None, pins: dict[int, int] | None = None) -> None:
    """Rehace las filas de las casillas de una nota (content=None: la nota ya no tiene casillas visibles).
    pins = {posición: id} fija filas que se acaban de escribir (si hay textos repetidos, el texto no basta)."""
    tasks = parse_tasks(content) if content is not None else []
    rows = conn.execute("SELECT id, note_task, note_index FROM inbox WHERE note_id=? AND note_task IS NOT NULL ORDER BY note_index, id",
                        (note_id,)).fetchall()
    free = {r["id"]: r for r in rows}
    match: dict[int, int] = {}
    for k, rid in (pins or {}).items():
        if rid in free and k < len(tasks):
            match[k] = rid
            del free[rid]
    far = 10 ** 6
    for t in tasks:
        if t["k"] in match:
            continue
        cands = [r for r in free.values() if r["note_task"] == t["text"]]
        if cands:
            r = min(cands, key=lambda r: abs((far if r["note_index"] is None else r["note_index"]) - t["k"]))
            match[t["k"]] = r["id"]
            del free[r["id"]]
    for t in tasks:
        if t["k"] not in match:
            r = next((r for r in free.values() if r["note_index"] == t["k"]), None)
            if r:
                match[t["k"]] = r["id"]
                del free[r["id"]]
    n = len(tasks)
    for t in tasks:
        if t["k"] not in match:
            cur = conn.execute("INSERT INTO inbox (content, item_type, status, note_id, note_task, note_index, sort_order) "
                               "VALUES (?, 'tarea', 'pending', ?, ?, ?, 0)", (t["text"], note_id, t["text"], t["k"]))
            match[t["k"]] = cur.lastrowid
    # Casillas marcadas o desmarcadas en el .md: al historial de completados (revisión semanal)
    before = {r["id"]: r["status"] for r in conn.execute(
        f"SELECT id, status FROM inbox WHERE id IN ({','.join('?' * len(match)) or 'NULL'})", list(match.values()))}
    for t in tasks:
        rid, new_status = match[t["k"]], "processed" if t["done"] else "pending"
        if rid in before and before[rid] != new_status:
            from app.routines import log
            log(conn, {"id": rid, "content": t["text"], "item_type": "tarea"}, "done" if t["done"] else "reopen")
    for t in tasks:
        conn.execute("UPDATE inbox SET content=?, note_task=?, note_index=?, status=?, item_type='tarea', sort_order=?, parent_id=? WHERE id=?",
                     (t["text"], t["text"], t["k"], "processed" if t["done"] else "pending", float(n - t["k"]),
                      match[t["parent"]] if t["parent"] is not None else None, match[t["k"]]))
    for rid in free:  # casillas que ya no están; sus hijos sueltos no se pierden
        conn.execute("UPDATE inbox SET parent_id=NULL WHERE parent_id=?", (rid,))
        conn.execute("DELETE FROM inbox WHERE id=?", (rid,))
    # Enlaces [[tarea:N]] de la nota (app/links.py): el mismo .md manda
    from app.links import sync_note_links
    sync_note_links(conn, note_id, content)


def note_has_items(row) -> bool:
    return bool(row) and not row["encrypted"] and row["status"] != "indice"


def sync_all_note_items(conn: sqlite3.Connection) -> None:
    """Todas las notas de la caché (al arrancar) y limpieza de filas de notas que ya no existen."""
    notes = {r["id"]: r for r in conn.execute("SELECT id, content, encrypted, status FROM notes")}
    for nid, row in notes.items():
        sync_note_items(conn, nid, row["content"] if note_has_items(row) else None)
    for r in conn.execute("SELECT DISTINCT note_id FROM inbox WHERE note_task IS NOT NULL").fetchall():
        if r["note_id"] not in notes:
            sync_note_items(conn, r["note_id"], None)


# ─────────────────────────────────────────────
# Edición del .md
# ─────────────────────────────────────────────

class TaskMissing(Exception):
    """La casilla ya no está donde se esperaba (la nota cambió por otro lado)."""


class NoteDoc:
    """Archivo de una nota cargado como líneas (con sus finales de línea)."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
        m = FRONTMATTER_RE.match(raw)
        self.head = m.group(0) if m else ""
        self.lines = raw[len(self.head):].splitlines(keepends=True)
        self.eol = "\r\n" if "\r\n" in raw else "\n"

    def text(self) -> str:
        return "".join(self.lines)

    def tasks(self) -> list[dict]:
        return parse_tasks(self.text())

    def task(self, k: int, text: str | None = None) -> dict:
        ts = self.tasks()
        if k is None or not 0 <= k < len(ts) or (text is not None and ts[k]["text"] != text):
            same = [t for t in ts if t["text"] == text] if text is not None else []
            if len(same) == 1:
                return same[0]
            raise TaskMissing()
        return ts[k]

    def _set(self, i: int, fn) -> None:
        body = self.lines[i].rstrip("\r\n")
        self.lines[i] = fn(body) + self.lines[i][len(body):]

    def set_done(self, t: dict, done: bool) -> None:
        self._set(t["line"], lambda s: TASK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)} [{'x' if done else ' '}] {m.group(4)}", s))

    def set_text(self, t: dict, text: str) -> None:
        self._set(t["line"], lambda s: TASK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)} [{m.group(3)}] {text}", s))

    def block(self, t: dict) -> tuple[int, int]:
        """Líneas de la casilla y lo que cuelga de ella (pasos, texto sangrado)."""
        end = t["line"] + 1
        last = end
        while end < len(self.lines):
            ln = self.lines[end].rstrip("\r\n")
            if ln.strip():
                if _indent(ln) <= t["indent"]:
                    break
                last = end + 1
            end += 1
        return t["line"], last

    def take(self, t: dict) -> tuple[int, list[str]]:
        """Quita la casilla con su bloque; devuelve dónde estaba y sus líneas tal cual."""
        a, b = self.block(t)
        out = self.lines[a:b]
        del self.lines[a:b]
        return a, out

    def anchor(self, before: dict | None = None, parent: dict | None = None) -> tuple[int, int]:
        """(línea, sangría) donde insertar: antes de una casilla, al final de los pasos de
        una casilla, o tras la última casilla de primer nivel (o al final del archivo)."""
        if before is not None:
            return before["line"], before["indent"]
        if parent is not None:
            return self.block(parent)[1], parent["indent"] + len(INDENT)
        tops = [t for t in self.tasks() if t["parent"] is None]
        if tops:
            return self.block(tops[-1])[1], tops[-1]["indent"]
        return len(self.lines), 0

    def insert(self, at: int, lines: list[str], indent: int, base: int | None = None) -> list[int]:
        """Inserta líneas (de un bloque o nuevas) con la sangría pedida. Devuelve las
        posiciones (k) de las casillas insertadas, en orden."""
        if not lines:
            return []
        if base is None:
            base = min(_indent(ln) for ln in lines if ln.strip())
        out = []
        for ln in lines:
            body = ln.rstrip("\r\n")
            if body.strip():
                body = " " * indent + body.expandtabs(4)[min(base, _indent(body)):]
            out.append(body + self.eol)
        if at >= len(self.lines) and self.lines and not self.lines[-1].endswith(("\n", "\r")):
            self.lines[-1] += self.eol
        self.lines[at:at] = out
        return [t["k"] for t in self.tasks() if at <= t["line"] < at + len(out)]

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(self.head + "".join(self.lines))


def task_line(text: str, done: bool = False) -> str:
    return f"- [{'x' if done else ' '}] {text}"
