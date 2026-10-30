// Listas de tareas (categorías con elementos, algunos diarios que se desmarcan cada día).
//
// Todo vive en un archivo, /listas.json, escrito de forma atómica. La primera vez se
// importan las listas del formato anterior (/checklists/_index.json + un .json por
// categoría); esos archivos no se borran.
#pragma once
#include <stdint.h>

namespace lists {

constexpr int MAX_CATEGORIES = 16;
constexpr int MAX_ITEMS = 240;  // entre todas las categorías
constexpr const char* FILE_PATH = "/listas.json";

struct Category { uint16_t id; char name[32]; };
struct Item { uint16_t id, cat; char text[56]; bool done, daily; };

void load();
void dailyTick(int32_t today);  // desmarca las diarias al cambiar de día

int categoryCount();
const Category& category(int i);
int categoryIndex(const char* name);       // -1 si no existe
int itemsOf(uint16_t catId, int* outIdx, int maxOut);  // índices en el orden de la lista
const Item& item(int i);
void progress(uint16_t catId, int& done, int& total);

// Operaciones (la web identifica la categoría por nombre y el elemento por id o por posición)
bool addCategory(const char* name);
bool deleteCategory(const char* name);
bool addItem(const char* catName, const char* text, bool daily);
bool editItem(const char* catName, int id, int index, const char* text, bool daily);
bool deleteItem(const char* catName, int id, int index);
bool toggleItem(const char* catName, int id, int index);
bool toggleItemById(uint16_t id);

void broadcastCategories();
void broadcastItems(const char* catName);

}  // namespace lists
