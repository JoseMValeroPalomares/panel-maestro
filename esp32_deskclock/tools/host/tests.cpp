// Tests de la lógica del firmware en el PC:  make -C tools/host test
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <string>

#include "../../src/app/protocol.h"
#include "../../src/core/util.h"
#include "../../src/gfx/font.h"
#include "../../src/model/calendar.h"
#include "../../src/model/lists.h"
#include "../../src/model/media.h"
#include "../../src/model/notes.h"
#include "../../src/model/pomodoro.h"
#include "../../src/ui/ui.h"
#include "../../src/ui/ui_internal.h"
#include "host.h"
#include "host_canvas.h"

static int failures = 0, checks = 0;
#define CHECK(cond)                                                       \
  do {                                                                    \
    checks++;                                                             \
    if (!(cond)) { failures++; fprintf(stderr, "FALLO %s:%d  %s\n", __FILE__, __LINE__, #cond); } \
  } while (0)

static void send(const std::string& json) { protocol::handleText(json.c_str(), json.size()); }

static std::string readFile(const char* p) {
  char* d = nullptr;
  size_t n = 0;
  if (!fsReadFile(p, &d, &n)) return "";
  std::string s(d, n);
  free(d);
  return s;
}

static void writeRaw(const char* p, const std::string& data) {
  FILE* f = fopen((host::root + p).c_str(), "wb");
  fwrite(data.data(), 1, data.size(), f);
  fclose(f);
}

static void freshSd(const char* name) {
  host::root = std::string("/tmp/esp32-tests-") + name;
  std::string cmd = "rm -rf '" + host::root + "' && mkdir -p '" + host::root + "'";
  if (system(cmd.c_str()) != 0) abort();
  host::prefs.clear();
  host::sent.clear();
  host::sdOk = true;
}

static void setDate(int y, int m, int d, int hh = 10, int mm = 0) {
  host::timeValid = true;
  host::localTime = {};
  host::localTime.tm_year = y - 1900;
  host::localTime.tm_mon = m - 1;
  host::localTime.tm_mday = d;
  host::localTime.tm_hour = hh;
  host::localTime.tm_min = mm;
  host::localTime.tm_wday = (weekdayMon0(y, m, d) + 1) % 7;
}

// ─────────────────────────────────────────────
static void testText() {
  const char* s = "ñá€x";
  CHECK(utf8Next(s) == 0xF1);
  CHECK(utf8Next(s) == 0xE1);
  CHECK(utf8Next(s) == 0x20AC);
  CHECK(utf8Next(s) == 'x');
  const char* bad = "\xFF" "a";
  CHECK(utf8Next(bad) == 0xFFFD && *bad == 'a');

  // Ajuste de línea: nunca pasa del ancho y no corta palabras que caben
  TextLine lines[6];
  char tail[200];
  const char* txt = "Cuando la membrana alcanza el umbral se abren los canales de sodio dependientes de voltaje";
  int n = wrapText(FONT_BODY, txt, 200, lines, 6, tail, sizeof tail);
  CHECK(n >= 3);
  for (int i = 0; i < n; i++) {
    CHECK(textWidth(FONT_BODY, lines[i].start, lines[i].len) <= 200);
    CHECK(lines[i].len == 0 || lines[i].start[lines[i].len - 1] != ' ');
  }
  // Recorte con «…» cuando sobra texto
  n = wrapText(FONT_BODY, txt, 200, lines, 2, tail, sizeof tail);
  CHECK(n == 2 && lines[1].start == tail && strstr(tail, "\xE2\x80\xA6"));
  CHECK(textWidth(FONT_BODY, tail) <= 200);
  // Palabra más larga que la línea: se corta sin bucle infinito
  n = wrapText(FONT_BODY, "Supercalifragilisticoespialidoso", 60, lines, 6, tail, sizeof tail);
  CHECK(n >= 2);
  char out[64];
  ellipsize(FONT_LABEL, "Examen de Electrónica Analógica II", 120, out, sizeof out);
  CHECK(textWidth(FONT_LABEL, out) <= 120 && strstr(out, "\xE2\x80\xA6"));
  ellipsize(FONT_LABEL, "Corto", 120, out, sizeof out);
  CHECK(!strcmp(out, "Corto"));
  // Glifos que la fuente no trae → sustituto, nunca nulo
  CHECK(fontGlyph(FONT_BODY, 0x2248) != nullptr);  // ≈
  CHECK(textWidth(FONT_CLOCK, "18:45 h") > textWidth(FONT_CLOCK, "18:45"));  // la «h» no existe ahí: se salta sin fallar
}

static void testUtil() {
  char out[40];
  slugify("Física II / Práctica: «ñandú»", out, sizeof out);
  CHECK(!strcmp(out, "fisica-ii-practica-nandu"));
  slugify("../../etc/passwd", out, sizeof out);
  CHECK(!strchr(out, '/') && !strchr(out, '.'));
  CHECK(weekdayMon0(2026, 10, 19) == 0);  // lunes
  CHECK(daysInMonth(2028, 2) == 29 && daysInMonth(2100, 2) == 28);
  int y, m, d;
  civilFromDays(daysFromCivil(2026, 12, 31) + 1, y, m, d);
  CHECK(y == 2027 && m == 1 && d == 1);
  CHECK(!parseIsoDate("2026-02-30", y, m, d) && parseIsoDate("2026-03-29", y, m, d));
  char rel[24];
  relativeDayEs(1, rel, sizeof rel);
  CHECK(!strcmp(rel, "mañana"));
  char cap[16] = "miércoles";
  capitalizeEs(cap);
  CHECK(!strcmp(cap, "Miércoles"));
  char cap2[16] = "\xC3\xA1rbol";  // árbol
  capitalizeEs(cap2);
  CHECK(!strcmp(cap2, "\xC3\x81rbol"));
  CHECK(parseHexColor565("#FF0000", 0) == 0xF800);
  char small[5];
  copyStr(small, "aaañ", sizeof small);  // cabrían 4 bytes: no deja la «ñ» partida
  CHECK(!strcmp(small, "aaa"));
}

static void testStorage() {
  freshSd("storage");
  CHECK(fsWriteAtomic("/a.json", "uno", 3));
  CHECK(fsWriteAtomic("/a.json", "dos", 3));
  CHECK(readFile("/a.json") == "dos");
  // Corte de luz entre los dos renombrados: solo queda el .tmp completo
  CHECK(fsRename("/a.json", "/a.json.bak"));
  writeRaw("/a.json.tmp", "tres");
  CHECK(readFile("/a.json") == "tres");
}

static void testCalendar() {
  freshSd("calendar");
  setDate(2026, 10, 19);
  // Archivo del firmware anterior: mismo formato
  writeRaw("/eventos.json", R"([{"uid":"x1","date":"2026-10-25","title":"Viaje","type":"evento"},
                                 {"date":"2026-10-20","title":"Sin uid","type":"examen"},
                                 {"uid":"mal","date":"2026-13-40","title":"Fecha rota","type":"evento"}])");
  calendar::load();
  CHECK(calendar::count() == 2);
  CHECK(!strcmp(calendar::at(0).title, "Sin uid") && calendar::at(0).uid[0]);  // ordenados y con uid nuevo
  // Editar por uid aunque el índice haya cambiado
  send(R"({"type":"calendar_add","date":"2026-10-19","title":"Hoy","etype":"entrega"})");
  CHECK(calendar::count() == 3 && !strcmp(calendar::at(0).title, "Hoy"));
  send(R"({"type":"calendar_edit","uid":"x1","index":0,"date":"2026-11-01","title":"Viaje largo","etype":"evento"})");
  int idx[2];
  CHECK(calendar::eventsOn(daysFromCivil(2026, 11, 1), idx, 2) == 1 && !strcmp(calendar::at(idx[0]).title, "Viaje largo"));
  CHECK(!strcmp(calendar::at(0).title, "Hoy"));  // el de índice 0 no se ha tocado
  // Índice (web antigua) sigue funcionando
  send(R"({"type":"calendar_delete","index":0})");
  CHECK(calendar::count() == 2 && strcmp(calendar::at(0).title, "Hoy"));
  // Sincronización completa desde iCloud
  send(R"({"type":"calendar_sync_full","events":[{"uid":"i1","date":"2026-10-21","title":"Examen de Física","type":"examen"}]})");
  CHECK(calendar::count() == 1 && calendar::firstFrom(todayDays()) == 0);
  CHECK(readFile("/eventos.json").find("Examen de Física") != std::string::npos);
  calendar::load();
  CHECK(calendar::count() == 1);
  // Archivo corrupto: se aparta, no se pisa
  writeRaw("/eventos.json", "{roto");
  calendar::load();
  CHECK(calendar::count() == 0 && fsExists("/eventos.ilegible.json"));
}

static void testLists() {
  freshSd("lists");
  setDate(2026, 10, 19);
  // Formato anterior
  fsMkdir("/checklists");
  writeRaw("/checklists/_index.json", R"(["Casa","Física II"])");
  writeRaw("/checklists/Casa.json", R"([{"text":"Fregar","done":true,"daily":true},{"text":"Barrer","done":false,"daily":false}])");
  writeRaw("/checklists/Física II.json", R"([{"text":"Tema 4","done":false,"daily":false}])");
  lists::load();
  CHECK(lists::categoryCount() == 2);
  int idx[10];
  CHECK(lists::itemsOf(lists::category(0).id, idx, 10) == 2 && lists::item(idx[0]).done);
  CHECK(fsExists("/listas.json") && fsExists("/checklists/Casa.json"));  // los antiguos no se borran
  lists::load();  // segunda vez: lee el nuevo, no vuelve a importar
  CHECK(lists::categoryCount() == 2);
  // Ids estables: tocar «Barrer» por id aunque la web mande otro índice
  const uint16_t barrer = lists::item(idx[1]).id;
  send("{\"type\":\"checklist_toggle_item\",\"category\":\"Casa\",\"id\":" + std::to_string(barrer) + ",\"index\":0}");
  CHECK(lists::item(idx[1]).done && lists::item(idx[0]).done);
  // Operar en otra categoría no cambia lo que se ve de esta (antes había una sola caché)
  send(R"({"type":"checklist_add_item","category":"Física II","text":"Tema 5","daily":false})");
  CHECK(lists::itemsOf(lists::category(0).id, idx, 10) == 2);
  // Nombres raros: no tocan rutas de la SD
  send(R"({"type":"checklist_add_category","name":"../../hack"})");
  CHECK(lists::categoryIndex("../../hack") == 2 && !fsExists("/hack.json"));
  // Reinicio diario: solo las diarias, una vez al día
  lists::dailyTick(daysFromCivil(2026, 10, 20));
  lists::itemsOf(lists::category(0).id, idx, 10);
  CHECK(!lists::item(idx[0]).done && lists::item(idx[1]).done);
  send(R"({"type":"checklist_delete_category","name":"Casa"})");
  CHECK(lists::categoryCount() == 2 && lists::categoryIndex("Casa") < 0);
}

static void testPomodoro() {
  freshSd("pomo");
  setDate(2026, 10, 19);
  host::ms = 1000;
  pomodoro::load();
  pomodoro::setMinutes(1, 1);
  pomodoro::toggle();
  CHECK(pomodoro::run() == pomodoro::RUNNING && pomodoro::remainingSec() == 60);
  host::ms += 30000;
  pomodoro::toggle();  // pausa
  host::ms += 100000;
  CHECK(pomodoro::remainingSec() == 30);
  pomodoro::toggle();
  host::ms += 30001;
  pomodoro::tick();
  pomodoro::Phase f;
  CHECK(pomodoro::takeFinished(f) && f == pomodoro::WORK && pomodoro::phase() == pomodoro::BREAK);
  CHECK(!pomodoro::takeFinished(f));
  CHECK(pomodoro::streak() == 1);
  pomodoro::reset();
  pomodoro::setMinutes(500, 0);
  CHECK(pomodoro::workMin() == 180 && pomodoro::breakMin() == 1);
}

// La nota de repaso: ocupa la pantalla, no se pisa con el reloj y vuelve al reloj al acabar
static void testReview() {
  freshSd("review");
  setDate(2026, 10, 19, 18, 45);
  host::ms = 5000;
  static HostCanvas canvas;
  ui::begin(&canvas);
  ui::goTo(ui::CALENDAR);
  send(R"({"type":"review_note","note_id":"n1","title":"Título","category":"Cat","snippet":"Texto"})");
  ui::tick();
  CHECK(ui::st.modal == ui::M_NONE && review::pending());  // en otra pantalla espera
  ui::goTo(ui::CLOCK);
  ui::tick();
  CHECK(ui::st.modal == ui::M_REVIEW && review::showing());
  // Con la nota delante, el minuto que cambia no repinta el reloj encima
  static Scene a, b;
  a.reset(0); ui::build(a);
  host::localTime.tm_min = 46;
  b.reset(0); ui::build(b);
  bool same = a.count() == b.count();
  for (int i = 0; same && i < a.count(); i++) same = a.prim(i).hash == b.prim(i).hash || a.prim(i).kind == Prim::RECT;
  CHECK(same);
  host::ms += review::SHOW_MS + 10;
  ui::tick();
  CHECK(ui::st.modal == ui::M_NONE && !review::showing() && !review::pending());
  // OK pide abrirla en el PC y se ve la confirmación
  send(R"({"type":"review_note","note_id":"n2","title":"Otra","category":"","snippet":"…"})");
  ui::tick();
  host::sent.clear();
  ui::key(ui::K_OK);
  CHECK(!host::sent.empty() && host::sent.back().find("open_note_request") != std::string::npos);
  CHECK(review::openRequested());
  ui::key(ui::K_BACK);
  ui::tick();
  CHECK(ui::st.modal == ui::M_NONE);
}

// Al cambiar el minuto solo se repinta la zona de la hora, no la pantalla entera
// Pantalla de notas: pide la lista al entrar, abre una, se desplaza y la abre en el PC
static bool sentHas(const char* what) {
  for (const std::string& m : host::sent)
    if (m.find(what) != std::string::npos) return true;
  return false;
}

static void testNotes() {
  freshSd("notes");
  setDate(2026, 10, 19, 18, 45);
  static HostCanvas canvas;
  ui::begin(&canvas);
  ui::goTo(ui::CLOCK);
  host::sent.clear();
  ui::key(ui::K_0);
  CHECK(ui::current() == ui::NOTES && sentHas("notes_list_request"));
  CHECK(notes::listState() == notes::LOADING);
  // Sin respuesta: se vuelve a pedir al rato, no en cada fotograma
  host::sent.clear();
  ui::tick();
  CHECK(!sentHas("notes_list_request"));
  host::ms += 6000;
  ui::tick();
  CHECK(sentHas("notes_list_request"));
  send(R"({"type":"notes_list","notes":[{"id":"a","title":"Uno","category":"X"},{"id":"","title":"sin id"},)"
       R"({"id":"b","title":"Dos","category":"X - Y"},{"id":"c","title":"Tres","category":"Z"}]})");
  CHECK(notes::count() == 3 && notes::listState() == notes::READY);
  ui::key(ui::K_DOWN);
  host::sent.clear();
  ui::key(ui::K_OK);
  CHECK(ui::st.notesReading && notes::openIndex() == 1 && sentHas("\"note_id\":\"b\""));
  // Una respuesta de otra nota se ignora
  send(R"({"type":"note_content","note_id":"a","text":"no"})");
  CHECK(notes::contentState() == notes::LOADING);
  std::string longText = "{\"type\":\"note_content\",\"note_id\":\"b\",\"text\":\"";
  for (int i = 0; i < 40; i++) longText += "Párrafo número " + std::to_string(i) + " con algo de texto para leer.\\n\\n";
  longText += "\"}";
  send(longText);
  CHECK(notes::contentState() == notes::READY);
  static Scene sc;
  sc.reset(0); ui::build(sc);
  CHECK(!sc.full() && ui::st.readLines > ui::st.readPage);
  for (int i = 0; i < 500; i++) ui::key(ui::K_DOWN, true);
  sc.reset(0); ui::build(sc);
  CHECK(ui::st.readLine == ui::st.readLines - ui::st.readPage);  // no pasa del final
  host::sent.clear();
  ui::key(ui::K_OK);
  CHECK(sentHas("open_note_request") && sentHas("\"b\"") && notes::openRequested());
  // → pasa a la siguiente y vuelve a empezar arriba; ← desde la primera da la vuelta
  ui::key(ui::K_RIGHT);
  CHECK(notes::openIndex() == 2 && ui::st.readLine == 0);
  ui::key(ui::K_RIGHT);
  ui::key(ui::K_LEFT);
  CHECK(notes::openIndex() == 2);
  ui::key(ui::K_BACK);
  CHECK(!ui::st.notesReading && ui::current() == ui::NOTES);
  // En la lista, las flechas laterales cambian de pantalla en el orden de SCREEN_ORDER
  ui::key(ui::K_LEFT);
  CHECK(ui::current() == ui::LISTS);
  ui::key(ui::K_RIGHT);
  CHECK(ui::current() == ui::NOTES && !ui::st.notesReading);
  ui::key(ui::K_RIGHT);
  CHECK(ui::current() == ui::POMODORO);
}

// Interruptor del repaso automático (desde la web): se guarda y la nota espera al 9
static void testReviewToggle() {
  freshSd("review-toggle");
  static HostCanvas canvas;
  ui::begin(&canvas);
  ui::goTo(ui::CLOCK);
  host::sent.clear();
  send(R"({"type":"review_set","enabled":false})");
  CHECK(!ui::reviewAuto() && host::prefs["review_auto"] == 0 && sentHas("review_state"));
  send(R"({"type":"review_note","note_id":"n9","title":"T","category":"C","snippet":"S"})");
  ui::tick();
  CHECK(ui::st.modal == ui::M_NONE && review::pending());
  ui::key(ui::K_9);
  CHECK(ui::st.modal == ui::M_REVIEW);
  ui::key(ui::K_BACK);
  ui::begin(&canvas);  // tras reiniciar sigue desactivado
  CHECK(!ui::reviewAuto());
  send(R"({"type":"review_set","enabled":true})");
  send(R"({"type":"review_note","note_id":"n10","title":"T","category":"C","snippet":"S"})");
  ui::tick();
  CHECK(ui::st.modal == ui::M_REVIEW);
  ui::key(ui::K_BACK);
  host::sent.clear();
  send(R"({"type":"get_state"})");
  CHECK(sentHas("review_state"));
}

static void testPartialRedraw() {
  freshSd("redraw");
  setDate(2026, 10, 19, 18, 45);
  static HostCanvas canvas;
  ui::begin(&canvas);
  ui::goTo(ui::CLOCK);
  host::ms += 1000;
  ui::invalidate();
  ui::tick();
  canvas.pixels = 0;
  host::localTime.tm_min = 46;
  host::ms += 1000;
  ui::key(ui::K_9);  // fuerza fotograma (no hay nota: no hace nada más)
  ui::tick();
  CHECK(canvas.pixels > 0 && canvas.pixels < SCREEN_WIDTH * SCREEN_HEIGHT / 2);
  canvas.pixels = 0;
  host::ms += 1000;
  ui::key(ui::K_9);
  ui::tick();
  CHECK(canvas.pixels == 0);  // nada ha cambiado: nada se pinta
}

static void testProtocolRobust() {
  freshSd("proto");
  send("no es json");
  send(R"({"type":"desconocido"})");
  send(R"({"type":"calendar_add","date":"ayer","title":"x"})");
  CHECK(!host::sent.empty() && host::sent.back().find("\"error\"") != std::string::npos);
  send(R"({"type":"set_screen","screen":99})");
  CHECK(ui::current() < ui::SCREEN_COUNT);
  // Carátula de tamaño incoherente: se descarta sin romper nada
  uint8_t* bad = (uint8_t*)malloc(10);
  bad[0] = 0; bad[1] = 50; bad[2] = 0; bad[3] = 50;
  protocol::handleBinary(bad, 10);
  uint16_t w, h; uint32_t v;
  CHECK(music::coverPixels(w, h, v) == nullptr);
  // Fondo sin SD: avisa y no falla
  host::sdOk = false;
  uint8_t* bg = (uint8_t*)calloc(1, 4 + 160 * 120 * 2);
  bg[1] = 160; bg[3] = 120;
  protocol::handleBinary(bg, 4 + 160 * 120 * 2);
  CHECK(!look::hasImage());
  host::sdOk = true;
}

int main() {
  setenv("HOST_QUIET", "1", 1);
  testText();
  testUtil();
  testStorage();
  testCalendar();
  testLists();
  testPomodoro();
  testReview();
  testNotes();
  testReviewToggle();
  testPartialRedraw();
  testProtocolRobust();
  printf("%d comprobaciones, %d fallos\n", checks, failures);
  return failures ? 1 : 0;
}
