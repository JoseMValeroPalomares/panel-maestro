#include "lists.h"

#include <ArduinoJson.h>
#include <stdlib.h>
#include <string.h>

#include "../core/util.h"
#include "../platform/platform.h"

namespace lists {

static Category cats[MAX_CATEGORIES];
static int nCats = 0;
static Item items[MAX_ITEMS];
static int nItems = 0;
static uint16_t nextId = 1;

int categoryCount() { return nCats; }
const Category& category(int i) { return cats[i]; }
const Item& item(int i) { return items[i]; }

int categoryIndex(const char* name) {
  if (!name) return -1;
  for (int i = 0; i < nCats; i++)
    if (!strcmp(cats[i].name, name)) return i;
  return -1;
}

int itemsOf(uint16_t catId, int* outIdx, int maxOut) {
  int k = 0;
  for (int i = 0; i < nItems && k < maxOut; i++)
    if (items[i].cat == catId) outIdx[k++] = i;
  return k;
}

void progress(uint16_t catId, int& done, int& total) {
  done = total = 0;
  for (int i = 0; i < nItems; i++)
    if (items[i].cat == catId) { total++; if (items[i].done) done++; }
}

// ── Persistencia ──────────────────────────────────────────────────────
static void save() {
  JsonDocument doc;
  doc["version"] = 1;
  doc["next_id"] = nextId;
  JsonArray ca = doc["categories"].to<JsonArray>();
  for (int c = 0; c < nCats; c++) {
    JsonObject co = ca.add<JsonObject>();
    co["id"] = cats[c].id;
    co["name"] = cats[c].name;
    JsonArray ia = co["items"].to<JsonArray>();
    for (int i = 0; i < nItems; i++) {
      if (items[i].cat != cats[c].id) continue;
      JsonObject io = ia.add<JsonObject>();
      io["id"] = items[i].id;
      io["text"] = items[i].text;
      io["done"] = items[i].done;
      io["daily"] = items[i].daily;
    }
  }
  const size_t len = measureJson(doc);
  char* buf = (char*)malloc(len + 1);
  if (!buf) { logf("listas: sin memoria para guardar"); return; }
  serializeJson(doc, buf, len + 1);
  if (!fsWriteAtomic(FILE_PATH, buf, len)) logf("listas: no se pudo guardar en la SD");
  free(buf);
}

static bool addCategoryRaw(const char* name, uint16_t id) {
  if (nCats >= MAX_CATEGORIES || !name || !*name || categoryIndex(name) >= 0) return false;
  cats[nCats].id = id ? id : nextId++;
  copyStr(cats[nCats].name, name, sizeof cats[nCats].name);
  nCats++;
  return true;
}

static bool addItemRaw(uint16_t catId, const char* text, bool done, bool daily, uint16_t id) {
  if (nItems >= MAX_ITEMS || !text || !*text) return false;
  Item& it = items[nItems++];
  it.id = id ? id : nextId++;
  it.cat = catId;
  copyStr(it.text, text, sizeof it.text);
  it.done = done;
  it.daily = daily;
  return true;
}

static bool readJson(const char* path, JsonDocument& doc) {
  char* data = nullptr;
  size_t len = 0;
  if (!fsReadFile(path, &data, &len)) return false;
  const DeserializationError err = deserializeJson(doc, data, len);
  free(data);
  if (err) logf("listas: %s ilegible (%s)", path, err.c_str());
  return !err;
}

// Formato anterior: /checklists/_index.json (nombres) + /checklists/<nombre>.json (elementos)
static bool migrateOld() {
  JsonDocument index;
  if (!readJson("/checklists/_index.json", index)) return false;
  int imported = 0;
  for (JsonVariantConst v : index.as<JsonArrayConst>()) {
    const char* name = v | "";
    if (!addCategoryRaw(name, 0)) continue;
    const uint16_t cid = cats[nCats - 1].id;
    char path[96];
    snprintf(path, sizeof path, "/checklists/%s.json", name);
    JsonDocument doc;
    if (!readJson(path, doc)) continue;
    for (JsonObjectConst o : doc.as<JsonArrayConst>()) {
      if (addItemRaw(cid, o["text"] | "", o["done"] | false, o["daily"] | false, 0)) imported++;
    }
  }
  logf("listas: importadas %d categorías y %d tareas del formato anterior", nCats, imported);
  save();
  return true;
}

void load() {
  nCats = nItems = 0;
  nextId = 1;
  JsonDocument doc;
  if (!readJson(FILE_PATH, doc)) {
    if (!fsExists(FILE_PATH)) migrateOld();
    else fsRename(FILE_PATH, "/listas.ilegible.json");  // se aparta antes de que un guardado lo pise
    return;
  }
  uint16_t maxId = 0;
  for (JsonObjectConst co : doc["categories"].as<JsonArrayConst>()) {
    const uint16_t cid = co["id"] | 0;
    if (!cid || !addCategoryRaw(co["name"] | "", cid)) continue;
    if (cid > maxId) maxId = cid;
    for (JsonObjectConst io : co["items"].as<JsonArrayConst>()) {
      const uint16_t iid = io["id"] | 0;
      if (iid && addItemRaw(cid, io["text"] | "", io["done"] | false, io["daily"] | false, iid) && iid > maxId) maxId = iid;
    }
  }
  const uint16_t stored = doc["next_id"] | 1;
  nextId = stored > maxId ? stored : (uint16_t)(maxId + 1);
  logf("listas: %d categorías, %d tareas", nCats, nItems);
}

void dailyTick(int32_t today) {
  if (!today) return;  // sin hora todavía
  const int32_t last = prefGet("lists_reset", 0);
  if (last == today) return;
  bool changed = false;
  for (int i = 0; i < nItems; i++)
    if (items[i].daily && items[i].done) { items[i].done = false; changed = true; }
  prefSet("lists_reset", today);
  if (changed) {
    save();
    broadcastCategories();
    logf("listas: tareas diarias desmarcadas");
  }
}

// ── Operaciones ───────────────────────────────────────────────────────
static int findItem(const char* catName, int id, int index) {
  if (id > 0) {
    for (int i = 0; i < nItems; i++)
      if (items[i].id == id) return i;
    return -1;
  }
  const int c = categoryIndex(catName);
  if (c < 0) return -1;
  int idx[MAX_ITEMS];
  const int k = itemsOf(cats[c].id, idx, MAX_ITEMS);
  return index >= 0 && index < k ? idx[index] : -1;
}

static const char* catNameOf(const Item& it) {
  for (int c = 0; c < nCats; c++)
    if (cats[c].id == it.cat) return cats[c].name;
  return "";
}

bool addCategory(const char* name) {
  if (!addCategoryRaw(name, 0)) { broadcastCategories(); return false; }
  save();
  broadcastCategories();
  return true;
}

bool deleteCategory(const char* name) {
  const int c = categoryIndex(name);
  if (c < 0) { broadcastCategories(); return false; }
  const uint16_t cid = cats[c].id;
  int w = 0;
  for (int i = 0; i < nItems; i++)
    if (items[i].cat != cid) items[w++] = items[i];
  nItems = w;
  memmove(&cats[c], &cats[c + 1], sizeof(Category) * (nCats - c - 1));
  nCats--;
  save();
  broadcastCategories();
  return true;
}

bool addItem(const char* catName, const char* text, bool daily) {
  const int c = categoryIndex(catName);
  if (c < 0 || !addItemRaw(cats[c].id, text, false, daily, 0)) return false;
  save();
  broadcastItems(catName);
  broadcastCategories();
  return true;
}

bool editItem(const char* catName, int id, int index, const char* text, bool daily) {
  const int i = findItem(catName, id, index);
  if (i < 0 || !text || !*text) { broadcastItems(catName); return false; }
  copyStr(items[i].text, text, sizeof items[i].text);
  items[i].daily = daily;
  save();
  broadcastItems(catNameOf(items[i]));
  return true;
}

bool deleteItem(const char* catName, int id, int index) {
  const int i = findItem(catName, id, index);
  if (i < 0) { broadcastItems(catName); return false; }
  const char* owner = catNameOf(items[i]);
  char ownerName[32];
  copyStr(ownerName, owner, sizeof ownerName);
  memmove(&items[i], &items[i + 1], sizeof(Item) * (nItems - i - 1));
  nItems--;
  save();
  broadcastItems(ownerName);
  broadcastCategories();
  return true;
}

bool toggleItem(const char* catName, int id, int index) {
  const int i = findItem(catName, id, index);
  if (i < 0) { broadcastItems(catName); return false; }
  return toggleItemById(items[i].id);
}

bool toggleItemById(uint16_t id) {
  for (int i = 0; i < nItems; i++) {
    if (items[i].id != id) continue;
    items[i].done = !items[i].done;
    save();
    broadcastItems(catNameOf(items[i]));
    broadcastCategories();
    return true;
  }
  return false;
}

// ── Estado → web ──────────────────────────────────────────────────────
static void send(JsonDocument& doc) {
  const size_t len = measureJson(doc);
  char* buf = (char*)malloc(len + 1);
  if (!buf) return;
  serializeJson(doc, buf, len + 1);
  netBroadcast(buf, len);
  free(buf);
}

void broadcastCategories() {
  JsonDocument doc;
  doc["type"] = "checklist_categories";
  JsonArray arr = doc["categories"].to<JsonArray>();
  for (int c = 0; c < nCats; c++) {
    int done, total;
    progress(cats[c].id, done, total);
    JsonObject o = arr.add<JsonObject>();
    o["id"] = cats[c].id;
    o["name"] = cats[c].name;
    o["done"] = done;
    o["total"] = total;
  }
  send(doc);
}

void broadcastItems(const char* catName) {
  const int c = categoryIndex(catName);
  if (c < 0) return;
  JsonDocument doc;
  doc["type"] = "checklist_items";
  doc["category"] = cats[c].name;
  JsonArray arr = doc["items"].to<JsonArray>();
  for (int i = 0; i < nItems; i++) {
    if (items[i].cat != cats[c].id) continue;
    JsonObject o = arr.add<JsonObject>();
    o["id"] = items[i].id;
    o["text"] = items[i].text;
    o["done"] = items[i].done;
    o["daily"] = items[i].daily;
  }
  send(doc);
}

}  // namespace lists
