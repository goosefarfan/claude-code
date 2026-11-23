#!/usr/bin/env python3
"""
Repara un respaldo local (sin cifrar) de iPhone para quitar el fondo de
pantalla dañado ANTES de restaurarlo.

Que hace:
  1. Guarda una copia del indice original del respaldo (Manifest.db).
  2. Quita del indice SOLO las entradas del sistema de fondos:
       - Todo el contenido de PosterBoard (pantallas de bloqueo de iOS 16+),
         incluidos ~50,000 archivos basura que iOS nunca pudo limpiar.
       - El fondo antiguo de SpringBoard (LockBackground / OriginalLockBackground).
  3. No borra ningun archivo del respaldo ni toca nada mas (fotos, apps,
     WhatsApp, ajustes, acomodo de la pantalla de inicio, etc.).

Al restaurar, iOS no recibe esos archivos y crea un fondo nuevo y limpio.

Uso:
    python3 reparar_fondo.py              reparar
    python3 reparar_fondo.py --deshacer   volver a dejar el indice original
"""

import datetime
import plistlib
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

POSTERBOARD = "AppDomain-com.apple.PosterBoard"
# Carpetas base del contenedor de PosterBoard: se conservan vacias.
POSTERBOARD_CONSERVAR = ("", "Documents", "Library", "Library/Preferences",
                         "Library/Application Support")
FONDO_ANTIGUO = (
    "Library/SpringBoard/LockBackground.cpbitmap",
    "Library/SpringBoard/OriginalLockBackground.cpbitmap",
    "Library/SpringBoard/LockBackgroundThumbnail.jpg",
    "Library/SpringBoard/LockBackgroundThumbnaildark.jpg",
    "Library/SpringBoard/HomeBackground.cpbitmap",
    "Library/SpringBoard/OriginalHomeBackground.cpbitmap",
    "Library/SpringBoard/HomeBackgroundThumbnail.jpg",
)

CONDICION = (
    f"(domain = ? AND relativePath NOT IN ({','.join('?' * len(POSTERBOARD_CONSERVAR))}))"
    f" OR (domain = 'HomeDomain' AND relativePath IN ({','.join('?' * len(FONDO_ANTIGUO))}))"
)
PARAMS = (POSTERBOARD, *POSTERBOARD_CONSERVAR, *FONDO_ANTIGUO)


def buscar_respaldo():
    raiz = Path.home() / "Library/Application Support/MobileSync/Backup"
    try:
        respaldos = [p for p in sorted(raiz.iterdir())
                     if p.is_dir() and (p / "Manifest.db").exists()]
    except PermissionError:
        salir("La Terminal no tiene 'Acceso total al disco'. Activalo en Ajustes del "
              "Sistema > Privacidad y seguridad, cierra la Terminal (Cmd+Q) y reintenta.")
    except FileNotFoundError:
        salir(f"No existe la carpeta de respaldos: {raiz}")
    if not respaldos:
        salir("No encontre ningun respaldo.")
    print("\nRespaldos encontrados:\n")
    for i, r in enumerate(respaldos, 1):
        info = leer_plist(r / "Info.plist")
        print(f"  [{i}] {info.get('Device Name', '?')} | iOS {info.get('Product Version', '?')}"
              f" | {info.get('Last Backup Date', '?')}")
    if len(respaldos) == 1:
        return respaldos[0]
    while True:
        op = input("\nNumero del respaldo del iPhone 17: ").strip()
        if op.isdigit() and 1 <= int(op) <= len(respaldos):
            return respaldos[int(op) - 1]


def leer_plist(ruta):
    try:
        with open(ruta, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return {}


def salir(msg):
    print("\n" + msg)
    sys.exit(1)


def copias_originales(respaldo):
    return sorted(respaldo.glob("Manifest.db.original-*"))


def deshacer(respaldo):
    copias = copias_originales(respaldo)
    if not copias:
        salir("No hay copia del indice original para restaurar.")
    ultima = copias[-1]
    shutil.copy2(ultima, respaldo / "Manifest.db")
    print(f"\nListo: se restauro el indice original desde {ultima.name}.")


def reparar(respaldo):
    if leer_plist(respaldo / "Manifest.plist").get("IsEncrypted"):
        salir("Este respaldo esta CIFRADO; este script solo funciona con respaldos sin cifrar.")
    for extra in ("Manifest.db-wal", "Manifest.db-shm"):
        if (respaldo / extra).exists():
            salir(f"Encontre {extra}: parece que Finder sigue usando el respaldo. "
                  "Cierra Finder, espera un minuto y vuelve a intentarlo.")

    # Trabajar sobre una copia temporal; el original solo se reemplaza al final.
    tmp = Path(tempfile.mkdtemp(prefix="reparar_fondo_"))
    trabajo = tmp / "Manifest.db"
    shutil.copy2(respaldo / "Manifest.db", trabajo)

    con = sqlite3.connect(str(trabajo))
    total = con.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
    filas = con.execute(
        f"SELECT domain, relativePath FROM Files WHERE {CONDICION}", PARAMS).fetchall()

    if not filas:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
        salir("No hay entradas de fondo que quitar: este respaldo ya esta reparado. "
              "No se cambio nada.")

    pb = sum(1 for d, _ in filas if d == POSTERBOARD)
    antiguos = [r for d, r in filas if d == "HomeDomain"]
    print(f"\nEl respaldo tiene {total:,} archivos.")
    print(f"Se quitaran del indice {len(filas):,} entradas:")
    print(f"  - {pb:,} de PosterBoard (pantallas de bloqueo y basura acumulada)")
    for r in antiguos:
        print(f"  - Fondo antiguo: {r}")
    print("Todo lo demas se queda igual.")

    if input("\nEscribe SI para continuar: ").strip().upper() != "SI":
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
        salir("Cancelado. No se cambio nada.")

    con.execute(f"DELETE FROM Files WHERE {CONDICION}", PARAMS)
    con.commit()
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    restantes = con.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
    con.close()
    if ok != "ok" or restantes != total - len(filas):
        shutil.rmtree(tmp, ignore_errors=True)
        salir(f"La verificacion fallo ({ok}); no se cambio nada en el respaldo.")

    # Copia de seguridad del indice original, luego reemplazo.
    sello = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    copia = respaldo / f"Manifest.db.original-{sello}"
    shutil.copy2(respaldo / "Manifest.db", copia)
    shutil.copy2(trabajo, respaldo / "Manifest.db")
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nListo. Indice reparado: {total:,} -> {restantes:,} archivos.")
    print(f"Copia del indice original: {copia.name}")
    print("\nSiguiente paso: NO hagas otro respaldo. Desactiva 'Buscar mi iPhone' y en")
    print("Finder presiona 'Restore Backup...' y elige este respaldo.")
    print("Para deshacer: python3 reparar_fondo.py --deshacer")


def main():
    respaldo = buscar_respaldo()
    if "--deshacer" in sys.argv:
        deshacer(respaldo)
    else:
        reparar(respaldo)


if __name__ == "__main__":
    main()
