// Renderiza todas las pantallas con datos de ejemplo y las guarda como PNG.
//   make -C tools/host preview OUT=/ruta/capturas
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <string>

#include "../../src/app/protocol.h"
#include "../../src/model/calendar.h"
#include "../../src/model/lists.h"
#include "../../src/model/media.h"
#include "../../src/model/pomodoro.h"
#include "../../src/ui/ui.h"
#include "../../src/ui/ui_internal.h"
#include "host.h"
#include "host_canvas.h"

static HostCanvas canvas;
static std::string out = ".";

static void send(const char* json) { protocol::handleText(json, strlen(json)); }

static void shot(const char* name) {
  ui::invalidate();
  ui::tick();
  const std::string p = out + "/" + name + ".png";
  if (!canvas.savePng(p.c_str())) fprintf(stderr, "no se pudo guardar %s\n", p.c_str());
  else printf("%s\n", p.c_str());
}

static uint8_t* fakeCover(int w, int h) {
  uint8_t* f = (uint8_t*)malloc(4 + w * h * 2);
  f[0] = w >> 8; f[1] = w & 255; f[2] = h >> 8; f[3] = h & 255;
  for (int y = 0; y < h; y++)
    for (int x = 0; x < w; x++) {
      const float d = hypotf(x - w * 0.35f, y - h * 0.4f) / w;
      const uint16_t c = rgb565((uint8_t)(220 - 120 * d), (uint8_t)(90 + 60 * (float)y / h), (uint8_t)(140 + 80 * d));
      f[4 + (y * w + x) * 2] = c >> 8;
      f[5 + (y * w + x) * 2] = c & 255;
    }
  return f;
}

int main(int argc, char** argv) {
  if (argc > 1) out = argv[1];
  mkdir(out.c_str(), 0755);
  setenv("HOST_QUIET", "1", 1);
  host::root = out + "/sd";
  mkdir(host::root.c_str(), 0755);
  host::localTime = {};
  host::localTime.tm_year = 2026 - 1900; host::localTime.tm_mon = 9; host::localTime.tm_mday = 19;
  host::localTime.tm_hour = 18; host::localTime.tm_min = 45; host::localTime.tm_wday = 1;
  host::sys = SysInfo{true, -58, "192.168.1.73", "panel-estudio", 3, true, true, 15193, 212, true, true, true, 178, 142,
                      3 * 3600 + 25 * 60, 22.4f, 48.0f, 47.0f};

  calendar::load(); lists::load(); pomodoro::load(); look::load();
  ui::begin(&canvas);

  send(R"J({"type":"calendar_sync_full","events":[
    {"uid":"a","date":"2026-10-21","title":"Examen de Electrónica Analógica","type":"examen"},
    {"uid":"b","date":"2026-10-21","title":"Entregar práctica 3","type":"entrega"},
    {"uid":"c","date":"2026-10-24","title":"Cumpleaños de Lucía","type":"evento"},
    {"uid":"d","date":"2026-10-30","title":"Memoria del TFG","type":"entrega"},
    {"uid":"e","date":"2026-10-12","title":"Revisión del examen","type":"evento"}]})J");
  send(R"J({"type":"checklist_add_category","name":"Casa"})J");
  send(R"J({"type":"checklist_add_category","name":"Física II"})J");
  send(R"J({"type":"checklist_add_category","name":"Compra semanal"})J");
  for (const char* t : {"Fregar los platos", "Regar las plantas", "Sacar la basura", "Poner una lavadora", "Ordenar el escritorio", "Cambiar las sábanas"}) {
    const bool daily = strstr(t, "Regar") || strstr(t, "platos");
    char json[200];
    snprintf(json, sizeof json, "{\"type\":\"checklist_add_item\",\"category\":\"Casa\",\"text\":\"%s\",\"daily\":%s}", t, daily ? "true" : "false");
    send(json);
  }
  send(R"J({"type":"checklist_toggle_item","category":"Casa","index":0})J");
  send(R"J({"type":"checklist_toggle_item","category":"Casa","index":2})J");
  send(R"J({"type":"checklist_add_item","category":"Física II","text":"Problemas del tema 4: electromagnetismo","daily":false})J");

  shot("01-reloj");
  host::sys.tempC = NAN;
  shot("01b-reloj-sin-sensor");
  host::sys.tempC = 22.4f;

  // Música
  send(R"J({"type":"nowplaying","status":"playing","title":"Clair de Lune (Suite bergamasque, L. 75)","artist":"Claude Debussy · Alexis Weissenberg","position_sec":96,"duration_sec":312,"accent_color":63488})J");
  protocol::handleBinary(fakeCover(120, 120), 4 + 120 * 120 * 2);
  shot("02-musica");
  send(R"J({"type":"nowplaying","status":"stopped"})J");

  // Repaso
  send(R"J({"type":"review_note","note_id":"potencial-de-accion","title":"Potencial de acción: mecanismo básico","category":"Neurociencia - Fisiología","snippet":"Cuando la membrana alcanza el umbral (≈ −55 mV), se abren los canales de Na⁺ dependientes de voltaje: entra sodio, el interior se vuelve positivo y la señal se propaga sin perder intensidad. Después, los canales de K⁺ devuelven la membrana al reposo… y la bomba sodio-potasio restaura los gradientes."})J");
  ui::tick();
  shot("03-repaso");
  ui::key(ui::K_OK);
  shot("03b-repaso-abriendo");
  ui::key(ui::K_BACK);

  ui::goTo(ui::CALENDAR);
  ui::key(ui::K_RIGHT); ui::key(ui::K_RIGHT);
  shot("04-calendario");
  ui::key(ui::K_OK);
  shot("04b-calendario-dia");
  ui::key(ui::K_BACK);

  ui::goTo(ui::LISTS);
  shot("05-listas");
  ui::key(ui::K_OK);
  ui::key(ui::K_DOWN);
  shot("05b-lista-casa");

  ui::goTo(ui::POMODORO);
  pomodoro::toggle();
  host::ms += (25 * 60 - 18 * 60 - 24) * 1000;
  shot("06-pomodoro");

  ui::goTo(ui::SYSTEM);
  shot("07-ajustes");

  // Notas
  ui::goTo(ui::NOTES);
  shot("10a-notas-cargando");
  send(R"J({"type":"notes_list","notes":[
    {"id":"anatomia-de-la-neurona","title":"Anatomía de la neurona","category":"Neurociencia - Fisiología"},
    {"id":"potencial-de-accion","title":"Potencial de acción: mecanismo básico","category":"Neurociencia - Fisiología"},
    {"id":"ritmos","title":"Ritmos cerebrales a 40 Hz","category":"Neurociencia - Sistemas"},
    {"id":"el-diodo","title":"El diodo","category":"Ingeniería - Electrónica"},
    {"id":"transistor","title":"El transistor bipolar y sus regiones de funcionamiento","category":"Ingeniería - Electrónica"},
    {"id":"luca","title":"LUCA: último ancestro común universal","category":"Biología"}]})J");
  ui::key(ui::K_DOWN);
  shot("10-notas");
  ui::key(ui::K_OK);
  shot("10b-nota-cargando");
  send(R"J({"type":"note_content","note_id":"potencial-de-accion","title":"Potencial de acción: mecanismo básico","category":"Neurociencia - Fisiología","text":"El potencial de acción es un cambio rápido y breve del potencial de membrana que recorre el axón sin perder intensidad.

Cuando la membrana alcanza el umbral (≈ -55 mV), se abren los canales de Na+ dependientes de voltaje: entra sodio y el interior se vuelve positivo.

Después se cierran los de sodio y se abren los de K+, que devuelven la membrana al reposo; hay una breve hiperpolarización.

La bomba sodio-potasio restaura los gradientes gastando ATP: saca tres Na+ por cada dos K+ que mete.

El periodo refractario impide que la señal vuelva hacia atrás y limita la frecuencia de disparo."})J");
  shot("10c-nota");
  for (int i = 0; i < 4; i++) ui::key(ui::K_DOWN);
  shot("10d-nota-bajando");
  ui::key(ui::K_OK);
  shot("10e-nota-abriendo");
  ui::key(ui::K_BACK);

  ui::goTo(ui::CLOCK);
  shot("08-reloj-pomodoro");
  host::ms += 19 * 60 * 1000;
  pomodoro::tick();
  shot("09-aviso-pomodoro");
  return 0;
}
