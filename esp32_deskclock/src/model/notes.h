// Notas del Cerebro para leer en la pantalla «Notas». Viven en el panel: el ESP32 pide
// la lista (título y categoría) y, al abrir una, su texto ya limpio de Markdown.
#pragma once
#include <ArduinoJson.h>
#include <stdint.h>

namespace notes {

constexpr int MAX_NOTES = 160;
constexpr size_t MAX_TEXT = 6000;  // bytes del texto de una nota (el panel ya lo recorta)

struct Entry {
  char id[72];
  char title[72];
  char category[48];
};

enum State : uint8_t { EMPTY, LOADING, READY };

// Lista
void requestList();                       // {"type":"notes_list_request"} (como mucho cada pocos segundos)
void receiveList(JsonArrayConst arr);     // {"type":"notes_list","notes":[{id,title,category}]}
State listState();
int count();
const Entry& at(int i);

// Nota abierta
void open(int i);                         // pide su texto: {"type":"note_request","note_id"}
void receiveContent(JsonObjectConst m);   // {"type":"note_content",note_id,title,category,text}
int openIndex();                          // -1 si no hay ninguna abierta
State contentState();
const char* text();                       // texto de la nota abierta ("" mientras llega)
uint32_t contentVersion();                // cambia al llegar un texto nuevo
void openOnPc();                          // {"type":"open_note_request","note_id"}
bool openRequested();                     // se acaba de pedir (para el mensaje de confirmación)

}  // namespace notes
