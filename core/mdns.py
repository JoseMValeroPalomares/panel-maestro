"""Resolver mínimo de mDNS (RFC 6762): «¿qué IP tiene panel-estudio.local?» sin avahi ni dependencias.

Manda una pregunta A por multidifusión a 224.0.0.251:5353 desde cada interfaz con IPv4 privada y escucha la respuesta.
Pide respuesta por unidifusión (bit QU) y además se une al grupo, así vale con y sin cortafuegos con estado. Es E/S
bloqueante (hasta `timeout` s): desde asyncio, con `asyncio.to_thread`."""

from __future__ import annotations

import ipaddress
import select
import socket
import struct
import subprocess
import time

GRUPO = "224.0.0.251"
PUERTO = 5353
_TIPO_A = 1


def _pregunta(nombre: str) -> bytes:
    cabecera = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)  # id 0 (mDNS), una pregunta
    etiquetas = b"".join(bytes([len(p)]) + p for p in (x.encode("idna") for x in nombre.rstrip(".").split(".")))
    return cabecera + etiquetas + b"\x00" + struct.pack(">HH", _TIPO_A, 0x8001)  # clase IN + QU (respuesta directa)


def _leer_nombre(datos: bytes, pos: int, saltos: int = 0) -> tuple[str, int]:
    """Nombre DNS (con punteros de compresión) → («a.b.local», posición siguiente)."""
    partes = []
    fin = None
    while True:
        if pos >= len(datos) or saltos > 20:
            raise ValueError("nombre DNS mal formado")
        n = datos[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(datos):
                raise ValueError("puntero DNS cortado")
            if fin is None:
                fin = pos + 2
            pos = ((n & 0x3F) << 8) | datos[pos + 1]
            saltos += 1
            continue
        partes.append(datos[pos + 1 : pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    return ".".join(partes), fin if fin is not None else pos


def respuestas_a(datos: bytes) -> list[tuple[str, str]]:
    """[(nombre en minúsculas, IPv4)] de los registros A de un paquete DNS. Un paquete roto da lista vacía."""
    try:
        _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", datos[:12])
        if not flags & 0x8000:
            return []  # es una pregunta (la nuestra, de vuelta por el grupo)
        pos = 12
        for _ in range(qd):
            _, pos = _leer_nombre(datos, pos)
            pos += 4
        out = []
        for _ in range(an + ns + ar):
            nombre, pos = _leer_nombre(datos, pos)
            tipo, _clase, _ttl, largo = struct.unpack(">HHIH", datos[pos : pos + 10])
            pos += 10
            if tipo == _TIPO_A and largo == 4:
                out.append((nombre.lower(), socket.inet_ntoa(datos[pos : pos + 4])))
            pos += largo
        return out
    except (ValueError, struct.error, IndexError, OSError):  # OSError: registro A cortado (inet_ntoa)
        return []


def ips_locales() -> list[str]:
    """IPv4 privadas de este equipo (192.168.x, 10.x, 172.16–31.x), sin bucle local ni la de Tailscale (100.64/10)."""
    vistas: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            vistas.append(str(info[4][0]))
    except OSError:
        pass
    for destino in ("192.168.1.1", "10.255.255.255", "172.16.0.1"):  # UDP sin enviar nada: solo elige interfaz
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((destino, 9))
            vistas.append(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:  # todas las interfaces, si el sistema las enseña (Linux)
        r = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=2)
        for linea in r.stdout.splitlines():
            trozos = linea.split()
            if "inet" in trozos:
                vistas.append(trozos[trozos.index("inet") + 1].split("/")[0])
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for ip in vistas:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_private and not a.is_loopback and not a.is_link_local and ip not in out:
            out.append(ip)
    return out


def resolver(nombre: str, timeout: float = 1.5, interfaces: list[str] | None = None) -> str | None:
    """IPv4 de `nombre` (p. ej. «panel-estudio.local») o None si nadie contesta en `timeout` segundos."""
    nombre = nombre.rstrip(".").lower()
    if not nombre.endswith(".local"):
        nombre += ".local"
    paquete = _pregunta(nombre)
    socks = []
    try:
        for ip in interfaces if interfaces is not None else ips_locales():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                s.bind((ip, 0))
                s.setblocking(False)
                s.sendto(paquete, (GRUPO, PUERTO))
                socks.append(s)
            except OSError:
                continue
        try:  # además, escuchar en el grupo: hay quien contesta por multidifusión aunque se pida directa
            g = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            g.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                g.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            g.bind(("", PUERTO))
            for ip in interfaces if interfaces is not None else ips_locales():
                try:
                    g.setsockopt(
                        socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GRUPO) + socket.inet_aton(ip)
                    )
                except OSError:
                    pass
            g.setblocking(False)
            socks.append(g)
        except OSError:
            pass
        if not socks:
            return None
        fin = time.monotonic() + timeout
        reenviado = False
        while (queda := fin - time.monotonic()) > 0:
            listos, _, _ = select.select(socks, [], [], min(queda, 0.4))
            for s in listos:
                try:
                    datos, _origen = s.recvfrom(4096)
                except OSError:
                    continue
                for quien, ip in respuestas_a(datos):
                    if quien == nombre:
                        return ip
            if not listos and not reenviado and queda < timeout / 2:  # un paquete perdido en la wifi: segunda pregunta
                reenviado = True
                for s in socks[:-1]:
                    try:
                        s.sendto(paquete, (GRUPO, PUERTO))
                    except OSError:
                        pass
        return None
    finally:
        for s in socks:
            s.close()
