#!/usr/bin/env python3
"""
Diagnostico del fondo de pantalla dañado en un respaldo local de iPhone.

SOLO LEE. No modifica, borra ni mueve nada del respaldo ni del iPhone.

Uso:
    python3 diagnostico_fondo.py              (busca los respaldos automaticamente)
    python3 diagnostico_fondo.py "RUTA"       (si el respaldo esta en otra carpeta)

Genera el archivo "reporte_fondo.txt" junto a este script. Ese archivo es el
que hay que compartir para preparar la reparacion.
"""

import os
import plistlib
import sqlite3
import sys
from pathlib import Path

# Palabras que identifican archivos del sistema de fondos de pantalla de iOS.
PATRONES = [
    "%PosterBoard%",
    "%PosterKit%",
    "%Poster%",
    "%Wallpaper%",
    "%wallpaper%",
    "%Background%.cpbitmap%",
    "%.cpbitmap%",
    "%LockBackground%",
    "%HomeBackground%",
    "%com.apple.springboard%",
]


def carpetas_de_respaldo():
    home = Path.home()
    candidatos = [
        # macOS
        home / "Library/Application Support/MobileSync/Backup",
        # Windows: iTunes clasico
        Path(os.environ.get("APPDATA", "")) / "Apple Computer/MobileSync/Backup",
        # Windows: iTunes de Microsoft Store / app Dispositivos Apple
        home / "Apple/MobileSync/Backup",
    ]
    return [c for c in candidatos if str(c) and c.is_dir()]


def leer_plist(ruta):
    try:
        with open(ruta, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return {}


def listar_respaldos(raices):
    respaldos = []
    for raiz in raices:
        if (raiz / "Manifest.db").exists():
            respaldos.append(raiz)
            continue
        for sub in sorted(raiz.iterdir()):
            if sub.is_dir() and (sub / "Manifest.db").exists():
                respaldos.append(sub)
    return respaldos


def describir(respaldo):
    info = leer_plist(respaldo / "Info.plist")
    manifest = leer_plist(respaldo / "Manifest.plist")
    return {
        "nombre": info.get("Device Name", "?"),
        "modelo": info.get("Product Type", "?"),
        "ios": info.get("Product Version", "?"),
        "fecha": str(info.get("Last Backup Date", "?")),
        "cifrado": bool(manifest.get("IsEncrypted", False)),
    }


def elegir(respaldos):
    print("\nRespaldos encontrados:\n")
    for i, r in enumerate(respaldos, 1):
        d = describir(r)
        print(f"  [{i}] {d['nombre']} | {d['modelo']} | iOS {d['ios']} | "
              f"{d['fecha']} | {'CIFRADO' if d['cifrado'] else 'sin cifrar'}")
    if len(respaldos) == 1:
        return respaldos[0]
    while True:
        op = input("\nEscribe el numero del respaldo de tu iPhone 17: ").strip()
        if op.isdigit() and 1 <= int(op) <= len(respaldos):
            return respaldos[int(op) - 1]


def main():
    if len(sys.argv) > 1:
        raices = [Path(sys.argv[1]).expanduser()]
    else:
        raices = carpetas_de_respaldo()

    respaldos = listar_respaldos(raices)
    if not respaldos:
        print("No encontre ningun respaldo local.")
        print("Haz primero un respaldo del iPhone en Finder (Mac) o en iTunes /")
        print("Dispositivos Apple (Windows), o pasa la ruta como argumento.")
        sys.exit(1)

    respaldo = elegir(respaldos)
    d = describir(respaldo)
    salida = []
    salida.append(f"Respaldo: {respaldo.name}")
    salida.append(f"Dispositivo: {d['nombre']} ({d['modelo']}), iOS {d['ios']}")
    salida.append(f"Fecha: {d['fecha']}  Cifrado: {d['cifrado']}")

    if d["cifrado"]:
        salida.append("\nEl respaldo esta CIFRADO: su indice no se puede leer sin la")
        salida.append("contraseña. Avisale a Claude para elegir el siguiente paso.")
        terminar(salida)
        return

    con = sqlite3.connect(f"file:{respaldo / 'Manifest.db'}?mode=ro", uri=True)
    total = con.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
    salida.append(f"Archivos en el respaldo: {total}")

    where = " OR ".join(["domain LIKE ? OR relativePath LIKE ?"] * len(PATRONES))
    params = [p for p in PATRONES for _ in (0, 1)]
    filas = con.execute(
        f"SELECT fileID, domain, relativePath, flags FROM Files WHERE {where} "
        "ORDER BY domain, relativePath",
        params,
    ).fetchall()
    con.close()

    salida.append(f"Archivos relacionados con fondos: {len(filas)}\n")
    salida.append("TIPO   TAMAÑO(bytes)  DOMINIO | RUTA")
    for file_id, dominio, ruta, flags in filas:
        tipo = {1: "archivo", 2: "carpeta", 4: "enlace"}.get(flags, str(flags))
        fisico = respaldo / file_id[:2] / file_id
        tam = fisico.stat().st_size if fisico.exists() else "-"
        salida.append(f"{tipo:<7}{str(tam):>13}  {dominio} | {ruta}")

    terminar(salida)


def terminar(lineas):
    texto = "\n".join(lineas)
    print("\n" + texto)
    destino = Path(__file__).resolve().parent / "reporte_fondo.txt"
    destino.write_text(texto + "\n", encoding="utf-8")
    print(f"\nReporte guardado en: {destino}")
    print("Comparte ese archivo con Claude. No se modifico nada.")


if __name__ == "__main__":
    main()
