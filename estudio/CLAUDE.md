# CLAUDE.md · Estudio (`estudio/`)

Se carga al trabajar en esta carpeta; las reglas generales y la sección «Ojo» están en el `CLAUDE.md` de la raíz.

- **Estudio (`estudio/`)**: actúa como *cliente* websocket hacia el ESP32 (`ESP32_HOST` en `.env`), lee Spotify vía `playerctl`/MPRIS, y arranca `IcloudSyncBridge` (CalDAV, estado en `calendar_sync_state.json`) y `NoteReviewBridge` (envía una nota cada 15 min, usa `SERVER_BASE_URL` de `.env`). Sirve su front estático en `/` de la sub-app.
