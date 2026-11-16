#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrae del material del curso los archivos que el emulador necesita.

El repositorio NO incluye material del curso (tabla de opcodes de
MinkiAssembler ni imagenes de los sprites): cada estudiante lo toma de los
archivos que ya descargo de Canvas.

Uso::

    python3 preparar_materiales.py RUTA/IIC2343_ProyectoBaseACF_7.zip \\
                                   RUTA/MinkiAssemblerPkg-v2.0.2.zip

Acepta ZIP o carpetas ya extraidas, en cualquier orden. Copia, sin
modificarlos:

* ``minki_opcodes.json``  -> junto a este script
* los 12 ``.coe`` de los sprites (background, good_ammo, nave_azul,
  nave_principal; canales RED, GREEN y BLUE) -> carpeta ``coe/``

No pisa archivos existentes salvo que se pase ``--force``. Solo usa la
biblioteca estandar.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DESTINO_COE = AQUI / "coe"
DESTINO_JSON = AQUI / "minki_opcodes.json"

SPRITES = ("background", "good_ammo", "nave_azul", "nave_principal")
CANALES = ("RED", "GREEN", "BLUE")
COE_ESPERADOS = [f"{s}_{c}.coe" for s in SPRITES for c in CANALES]
JSON_ESPERADO = "minki_opcodes.json"


def _candidatos(fuente: Path):
    """Itera (nombre_base, ruta_interna, lector) de un ZIP o de una carpeta."""
    if fuente.is_dir():
        for ruta in fuente.rglob("*"):
            if ruta.is_file():
                yield ruta.name, str(ruta), (lambda r=ruta: r.read_bytes())
    elif zipfile.is_zipfile(fuente):
        with zipfile.ZipFile(fuente) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                nombre = Path(info.filename).name

                def leer(f=fuente, n=info.filename):
                    with zipfile.ZipFile(f) as z:
                        return z.read(n)

                yield nombre, f"{fuente.name}:{info.filename}", leer
    else:
        raise SystemExit(f"error: {fuente} no es un ZIP ni una carpeta")


def _buscar(fuentes: list[Path]) -> dict[str, list[tuple[str, bytes]]]:
    """Devuelve, por nombre buscado, las copias encontradas (origen, bytes)."""
    buscados = set(COE_ESPERADOS) | {JSON_ESPERADO}
    hallados: dict[str, list[tuple[str, bytes]]] = {n: [] for n in buscados}
    for fuente in fuentes:
        for nombre, origen, leer in _candidatos(fuente):
            if nombre in buscados:
                hallados[nombre].append((origen, leer()))
    return hallados


def _elegir(nombre: str, copias: list[tuple[str, bytes]]) -> tuple[str, bytes] | None:
    if not copias:
        return None
    distintas = {datos for _, datos in copias}
    if len(distintas) > 1:
        print(f"aviso: {nombre} aparece {len(copias)} veces con contenido distinto; "
              f"se usa {copias[0][0]}", file=sys.stderr)
    return copias[0]


def _escribir(destino: Path, datos: bytes, force: bool) -> str:
    if destino.exists():
        if destino.read_bytes() == datos:
            return "ya estaba"
        if not force:
            return "OMITIDO (existe y es distinto; usa --force)"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return "copiado"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extrae del material del curso los archivos que necesita el emulador.")
    parser.add_argument("fuentes", nargs="+", type=Path,
                        help="ZIP(s) o carpeta(s): proyecto base de ACF7 y paquete MinkiAssembler")
    parser.add_argument("--force", action="store_true",
                        help="sobrescribir archivos existentes que sean distintos")
    args = parser.parse_args(argv)

    for fuente in args.fuentes:
        if not fuente.exists():
            raise SystemExit(f"error: no existe {fuente}")

    hallados = _buscar(args.fuentes)
    faltan = []

    elegido = _elegir(JSON_ESPERADO, hallados[JSON_ESPERADO])
    if elegido is None:
        faltan.append(JSON_ESPERADO)
    else:
        try:
            tabla = json.loads(elegido[1].decode("utf-8"))
            if not isinstance(tabla, dict) or not tabla:
                raise ValueError("no es un objeto JSON con mnemonicos")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SystemExit(f"error: {elegido[0]} no parece la tabla de opcodes: {exc}")
        estado = _escribir(DESTINO_JSON, elegido[1], args.force)
        print(f"{JSON_ESPERADO}: {estado}  ({len(tabla)} mnemonicos, desde {elegido[0]})")

    for nombre in COE_ESPERADOS:
        elegido = _elegir(nombre, hallados[nombre])
        if elegido is None:
            faltan.append(nombre)
            continue
        if not elegido[1].lstrip().lower().startswith(b"memory_initialization_radix"):
            raise SystemExit(f"error: {elegido[0]} no parece un .coe de Xilinx")
        estado = _escribir(DESTINO_COE / nombre, elegido[1], args.force)
        print(f"coe/{nombre}: {estado}")

    if faltan:
        print("\nFALTAN estos archivos (revisa que pasaste el ZIP correcto):", file=sys.stderr)
        for nombre in faltan:
            print(f"  - {nombre}", file=sys.stderr)
        return 1

    print("\nListo. Prueba con: python3 cli.py selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
