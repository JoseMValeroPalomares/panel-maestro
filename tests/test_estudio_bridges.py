"""Puentes de Estudio con el ESP32: carátula, fragmento del repaso y fusión con iCloud.
Sin red: todo lo que se prueba son funciones puras o un WebSocket simulado."""
import asyncio
import json
import struct
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from PIL import Image

from estudio import icloud_sync, note_review
from estudio.main import IMG_H, IMG_W, build_cover_frame, rgb_to_565


# ---------------------------------------------------------------- carátula
def test_caratula_120x120_rgb565_big_endian():
    img = Image.new("RGB", (300, 300), (255, 0, 0))
    frame = build_cover_frame(img)
    assert (IMG_W, IMG_H) == (120, 120)
    assert struct.unpack(">HH", frame[:4]) == (120, 120)
    assert len(frame) == 4 + 120 * 120 * 2  # lo que exige music::setCover
    assert struct.unpack(">H", frame[4:6])[0] == rgb_to_565(255, 0, 0) == 0xF800


def test_caratula_no_cuadrada_se_recorta_sin_deformar():
    # 400x200 azul con un cuadrado rojo de 200x200 en el centro: al recortar queda
    # solo el rojo; si se estirase, los bordes saldrían azules.
    img = Image.new("RGB", (400, 200), (0, 0, 255))
    img.paste((255, 0, 0), (100, 0, 300, 200))
    frame = build_cover_frame(img)
    px = lambda x, y: struct.unpack_from(">H", frame, 4 + (y * 120 + x) * 2)[0]
    for x in (2, 60, 117):  # el píxel extremo puede llevar algo de suavizado
        assert px(x, 60) >> 11 >= 30 and px(x, 60) & 0x1F <= 2


def test_caratula_no_choca_con_el_fondo_personalizado():
    # El firmware trata 160x120 como fondo de pantalla, no como carátula
    assert (IMG_W, IMG_H) != (160, 120)


# ---------------------------------------------------------------- repaso
def test_limpia_markdown_del_fragmento():
    raw = (
        "- [ ] Repasar **la ley de Ohm** con [[Electricidad|electricidad]] y [apuntes](https://x.y)\n"
        "> según el `libro` de _Física_ ![fig](a.png) #tema/fisica <br>"
    )
    assert note_review.clean_snippet(raw) == (
        "Repasar la ley de Ohm con electricidad y apuntes según el libro de Física tema/fisica"
    )


def test_no_rompe_snake_case_ni_asteriscos_sueltos():
    assert note_review.clean_snippet("usa mi_variable_larga y 2 * 3 = 6") == "usa mi_variable_larga y 2 * 3 = 6"


def test_bloques_candidatos_sin_codigo_titulos_ni_tablas():
    content = (
        "---\ntitle: x\n---\n# Título\n\nPrimer párrafo útil.\n\n```python\nprint('no')\n\nmas codigo\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n## Otra\nSegundo párrafo.\n\n---\n"
    )
    assert note_review._candidate_blocks(content) == ["Primer párrafo útil.", "Segundo párrafo."]


def test_recorte_por_palabras_y_por_bytes():
    t = note_review.truncate_snippet("palabra " * 60)
    assert len(t) <= note_review.SNIPPET_MAX_CHARS + 1 and t.endswith("palabra…")
    largo = note_review.truncate_snippet("ñ" * 400)  # 2 bytes por carácter
    assert len(largo.encode()) <= note_review.SNIPPET_MAX_BYTES


def test_elige_nota_consolidada_y_payload(client):
    snippet = note_review._pick_random_consolidated_snippet()
    assert snippet is not None and snippet["snippet"]
    assert "#" not in snippet["snippet"]
    payload = json.loads(note_review._build_review_payload(snippet))
    assert payload["type"] == "review_note"
    assert set(payload) == {"type", "note_id", "title", "category", "snippet"}


# ---------------------------------------------------------------- iCloud
EV = {"date": "2026-11-02", "title": "Examen", "type": "examen"}


def test_fusion_tres_vias():
    otro = {**EV, "title": "Examen cambiado"}
    merged, ups, dels = icloud_sync._merge(
        icloud_events={"a": EV, "b": EV, "e": otro},
        esp32_events={"a": EV, "c": EV, "d": EV, "e": EV},
        last_state={"a": EV, "b": EV, "d": EV, "e": EV},
    )
    assert merged == {"a": EV, "c": EV, "e": otro}  # d se borró en iCloud; e cambió allí
    assert ups == {"c": EV}                          # c es nuevo en el ESP32
    assert dels == ["b"]                             # b se borró en el ESP32


def test_eventos_del_esp32_sin_uid_reciben_uno():
    evs = icloud_sync._events_from_esp32([{"uid": "", "date": "2026-11-02", "title": " Hola ", "type": "evento"}])
    (uid, ev), = evs.items()
    assert uid.endswith("@panel-estudio") and ev["title"] == "Hola"


def _run(coro):
    # Los tests e2e (Playwright síncrono) dejan un bucle en marcha en el hilo
    # principal y asyncio.run() se niega a anidar: se ejecuta en otro hilo.
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


class _Msg:
    def __init__(self, data):
        self.type, self.data = aiohttp.WSMsgType.TEXT, json.dumps(data)


class _FakeWS:
    """WebSocket que responde con difusiones ajenas antes de la lista."""
    def __init__(self, messages):
        self.messages, self.sent = messages, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send_str(self, s):
        self.sent.append(json.loads(s))

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield _Msg(m)
        await asyncio.sleep(3600)  # el ESP32 no cierra la conexión


class _FakeSession:
    def __init__(self, ws):
        self.ws = ws

    def ws_connect(self, *a, **k):
        return self.ws


def test_lectura_del_calendario_ignora_otras_difusiones():
    ws = _FakeWS([
        {"type": "pomodoro_state", "running": False},
        {"type": "screen", "screen": 1},
        {"type": "calendar_list", "events": [{"uid": "u1", **EV}]},
    ])
    bridge = icloud_sync.IcloudSyncBridge(_FakeSession(ws), "ws://esp32/ws")
    events = _run(bridge._get_esp32_events())
    assert ws.sent == [{"type": "calendar_get"}]
    assert events == {"u1": EV}


def test_lectura_del_calendario_vence_el_plazo(monkeypatch):
    monkeypatch.setattr(icloud_sync, "CALENDAR_REPLY_TIMEOUT_SEC", 0.05)
    bridge = icloud_sync.IcloudSyncBridge(_FakeSession(_FakeWS([{"type": "screen"}])), "ws://esp32/ws")
    assert _run(bridge._get_esp32_events()) is None  # el ciclo se salta, no borra nada


def test_fragmento_sin_formulas_emojis_ni_rayas_sueltas():
    content = "Antes.\n\n$$F = k \\frac{|q_1 q_2|}{r^2}$$\n\nHecho ✅ 🚀 con −5 V\n\n-\n"
    blocks = [note_review.clean_snippet(b) for b in note_review._candidate_blocks(content)]
    assert [b for b in blocks if b] == ["Antes.", "Hecho ✓ con -5 V"]


# ---------------------------------------------------------------- pantalla «Notas» del ESP32
def _nota_db(note_id, **campos):
    from app.database import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        cols = {"id": note_id, "title": note_id, "category": "Pruebas", "status": "consolidado",
                "content": "", "encrypted": 0, **campos}
        conn.execute(f"INSERT INTO notes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))


class _FakeEvent:
    def __init__(self, fails=False):
        self.fails, self.deleted = fails, False

    def delete(self):
        if self.fails:
            raise RuntimeError("412 Precondition Failed")
        self.deleted = True


def test_borrar_en_icloud_usa_el_objeto_del_listado():
    ev = _FakeEvent()
    assert icloud_sync._icloud_delete({"a": ev}, "a") and ev.deleted
    assert icloud_sync._icloud_delete({}, "b")  # ya no estaba en iCloud: nada que hacer
    assert not icloud_sync._icloud_delete({"c": _FakeEvent(fails=True)}, "c")


def test_borrado_fallido_no_resucita_el_evento(monkeypatch, tmp_path):
    state = tmp_path / "estado.json"
    state.write_text(json.dumps({"a": EV, "b": EV}))
    monkeypatch.setattr(icloud_sync, "STATE_FILE", state)
    monkeypatch.setattr(icloud_sync, "_connect_calendar", lambda: None)

    def fetch(cal, objects=None):
        objects.update({"a": _FakeEvent(), "b": _FakeEvent(fails=True)})
        return {"a": EV, "b": EV}
    monkeypatch.setattr(icloud_sync, "_fetch_icloud_events", fetch)

    bridge = icloud_sync.IcloudSyncBridge(None, "ws://esp32/ws")
    pushed = []

    async def esp32_events():
        return {"a": EV}  # «b» se borró en el ESP32

    async def push(merged):
        pushed.append(merged)
    bridge._get_esp32_events, bridge._push_to_esp32 = esp32_events, push
    _run(bridge._sync_once())
    assert pushed == [{"a": EV}]
    assert json.loads(state.read_text()) == {"a": EV, "b": EV}  # «b» se reintenta, no vuelve al ESP32


def test_lista_de_notas_sin_cifradas_ni_indices(client):
    _nota_db("esp-visible", title="Zeta visible", category="Física - ")
    _nota_db("esp-cifrada", title="Secreta", encrypted=1)
    _nota_db("esp-indice", title="Índice", status="indice")
    notas = note_review.list_notes_for_esp32()
    ids = [n["id"] for n in notas]
    assert "esp-visible" in ids and "esp-cifrada" not in ids and "esp-indice" not in ids
    assert next(n for n in notas if n["id"] == "esp-visible")["category"] == "Física"
    claves = [(n["category"].casefold(), n["title"].casefold()) for n in notas]
    assert claves == sorted(claves)
    assert all(len(n["id"].encode()) < 72 and len(n["title"].encode()) < 72 and len(n["category"].encode()) < 48 for n in notas)


def test_texto_de_nota_limpio_y_recortado(client):
    _nota_db("esp-larga", content="# T\n\nPrimer **párrafo**.\n\n```\ncodigo\n```\n\n" + "ñandú " * 2000)
    c = note_review.note_content_for_esp32("esp-larga")
    assert c["type"] == "note_content" and c["note_id"] == "esp-larga"
    assert c["text"].startswith("Primer párrafo.\n\nñandú")
    assert "codigo" not in c["text"] and len(c["text"].encode()) <= note_review.NOTE_TEXT_MAX_BYTES
    _nota_db("esp-cifrada2", content="secreto", encrypted=1)
    assert note_review.note_content_for_esp32("esp-cifrada2") is None
    assert note_review.note_content_for_esp32("no-existe") is None


def test_el_puente_responde_a_las_peticiones_del_esp32(client):
    _nota_db("esp-puente", content="Hola desde el panel.")

    class WS:
        def __init__(self):
            self.sent = []

        async def send_str(self, s):
            self.sent.append(json.loads(s))

        def __aiter__(self):
            async def gen():
                for m in ({"type": "notes_list_request"}, {"type": "note_request", "note_id": "esp-puente"}):
                    yield _Msg(m)
            return gen()

    ws = WS()
    _run(note_review.NoteReviewBridge(None, "ws://esp32/ws")._receiver_loop(ws))
    assert [m["type"] for m in ws.sent] == ["notes_list", "note_content"]
    assert ws.sent[1]["text"] == "Hola desde el panel."
