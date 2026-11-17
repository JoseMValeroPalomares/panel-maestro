# CLAUDE.md · Estudio (`estudio/`)

Se carga al trabajar en esta carpeta; las reglas generales y la sección «Ojo» están en el `CLAUDE.md` de la raíz.

- **Estudio (`estudio/`)**: actúa como *cliente* websocket hacia el ESP32 (dónde está lo dice `core/red.py`, nunca una IP fija; `esp32_ws_url()` se resuelve en cada intento), hace de puente `/estudio/ws` entre la web y la placa (topes del firmware, 4 pestañas, cierres 4404/4429/4502), lee Spotify vía `playerctl`/MPRIS, y arranca `IcloudSyncBridge` (CalDAV, estado en `calendar_sync_state.json`) y `NoteReviewBridge` (envía una nota cada 15 min, usa `SERVER_BASE_URL` de `.env`). Sirve su front estático en `/` de la sub-app.
