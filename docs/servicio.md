# El servicio del panel (systemd de usuario)

El panel real corre como servicio de usuario `panel-maestro`. Hay **una sola plantilla**, la del repo:
`scripts/systemd/panel-maestro.service`. `./install.sh --service` cambia `@PANEL_DIR@` por la carpeta del proyecto, la
copia a `~/.config/systemd/user/` (si ya había otra distinta, la guarda antes como `*.bak-panel-<fecha>`), recarga
systemd y reinicia el servicio.

```bash
./install.sh --service                       # instala o actualiza la unidad y reinicia el panel
systemctl --user status panel-maestro        # estado
journalctl --user -u panel-maestro -f        # registro en vivo
systemd-analyze --user security panel-maestro
```

La unidad arranca `start.sh`, que lee del `.env` `PANEL_HOST`, `PANEL_PORT`, `PANEL_SSL_CERT` y `PANEL_SSL_KEY`
(ver [HTTPS.md](HTTPS.md)). Así la unidad no cambia al pasar a HTTPS o a Tailscale: solo el `.env`.

## Protecciones

Cada una se probó por separado y todas juntas con `systemd-run --user` contra una copia de los datos en el puerto 8811,
comprobando lo que el panel necesita: D-Bus de la sesión (`playerctl`), `git` en `~/dotfiles`, `git ls-remote` por SSH
(subida de dotfiles y del panel), lectura de `/run/media` (Universidad), escritura en el repo, `/tmp`, el socket de
Wayland y abrir el navegador (una nota que pide el ESP32), además de guardar notas y hacer copias.

| Protección | ¿Va? | Por qué |
|---|---|---|
| `UMask=0077` | sí | Lo nuevo nace 600/700 (también lo pone `main.py`) |
| `NoNewPrivileges`, `RestrictSUIDSGID` | sí | Nada que lance el panel puede ganar privilegios |
| `RestrictRealtime`, `LockPersonality`, `SystemCallArchitectures=native` | sí | Sin efecto en el panel |
| `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK` | sí | Red, D-Bus/Wayland y resolución de nombres |
| `PrivateTmp`, `ProtectSystem`, `ProtectKernel*`, `ProtectControlGroups`, `ProtectHostname`, `ProtectClock`, `ProtectProc`, `BindPaths` | no | En un servicio de **usuario** activan `PrivateUsers`: ssh ve `/etc/ssh` como de «nobody», se niega a leerlo y falla la subida de dotfiles y del panel |
| `CapabilityBoundingSet=` | no | El gestor de usuario no puede aplicarlo: el servicio no arranca (218/CAPABILITIES) |
| `ProtectHome` | no | El panel lee y escribe en `~` (dotfiles, `~/.ssh`) |
| `PrivateDevices`, `MemoryDenyWriteExecute`, `RestrictNamespaces`, `SystemCallFilter` | no | Si Firefox arranca desde el servicio (nota del ESP32) se quedaría sin GPU, sin JIT o sin su propio sandbox |

Puntuación de `systemd-analyze --user security` (14-11-2026): **9,4 UNSAFE** con la unidad antigua → **8,3 EXPOSED**
con la plantilla. No baja más sin `PrivateUsers`, que rompe ssh.

## Unidades antiguas

- La unidad que había antes llamaba a `uvicorn` directamente con `After=graphical-session.target`. La plantilla usa
  `start.sh` y `After=network-online.target`.
- `panel-estudio-server.service` (deshabilitada) apunta a `~/Documents/electro/…`, ya archivado: se puede borrar
  (`systemctl --user disable panel-estudio-server; rm ~/.config/systemd/user/panel-estudio-server.service;
  systemctl --user daemon-reload`).
