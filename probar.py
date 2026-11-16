#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba tu programa con UN comando.

    python3 probar.py mi_programa.suasm

Hace todo de una vez:

  1. ensambla tu programa (y te muestra el error, si lo hay);
  2. lo ejecuta en el emulador;
  3. muestra el valor final de tus variables, por nombre;
  4. avisa de errores tipicos (por ejemplo, un salto condicional sin CMP);
  5. dibuja la pantalla, guarda la imagen (PNG, o GIF con --gif) y la ABRE.

Es un atajo sobre ``cli.py``; para el control fino de cada paso usa ``cli.py``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EMU_DIR))

import cli  # noqa: E402
import cpu  # noqa: E402
import suasm  # noqa: E402

# Las direcciones 0 a 6 son LEDs, switches, display, botones y timer: al leerlas
# no devuelven lo guardado, asi que por defecto no se listan como variables.
PRIMERA_DIRECCION_DE_DATOS = 7
RELOJ_HZ = 50_000_000


def _entero(texto: str) -> int:
    return int(texto, 0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probar.py",
        description="Ensambla, ejecuta y dibuja tu programa con un solo comando.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python3 probar.py mi_programa.suasm\n"
            "  python3 probar.py mi_programa.suasm --botones 4          # boton izquierda apretado\n"
            "  python3 probar.py mi_programa.suasm --frames 3           # ejecutar mas tiempo\n"
            "  python3 probar.py mi_programa.suasm --gif                # animacion\n"
            "  python3 probar.py mi_programa.suasm --input 40:buttons:8 # pulsacion en el ciclo 40\n"
        ),
    )
    parser.add_argument("programa", help="archivo .suasm a probar")
    tiempo = parser.add_argument_group("cuanto ejecutar")
    tiempo.add_argument("--frames", type=int, default=None,
                        help="frames a ejecutar (1 frame = 416800 ciclos; por defecto 1, o 12 con --gif)")
    tiempo.add_argument("--ciclos", type=_entero, default=None,
                        help="ciclos exactos a ejecutar (reemplaza a --frames)")
    entradas = parser.add_argument_group("entradas simuladas")
    entradas.add_argument("--switches", type=_entero, default=0x8000,
                          help="switches al inicio (por defecto 0x8000: el switch 15 arriba)")
    entradas.add_argument("--botones", type=_entero, default=0,
                          help="botones apretados: centro=1 arriba=2 izquierda=4 derecha=8 abajo=16")
    entradas.add_argument("--input", action="append", default=[], metavar="CICLO:CAMPO:VALOR",
                          help="cambio de entrada en un ciclo (CAMPO = switches o buttons); repetible")
    imagen = parser.add_argument_group("imagen")
    imagen.add_argument("--gif", action="store_true", help="guardar una animacion en vez de una foto")
    imagen.add_argument("--tomas", type=int, default=8, help="cuadros del GIF (por defecto 8)")
    imagen.add_argument("--escala", type=int, default=1, help="ampliar la imagen N veces")
    imagen.add_argument("--salida", default=None,
                        help="archivo de la imagen (por defecto junto al programa, mismo nombre)")
    imagen.add_argument("--aliens", type=int, default=0, metavar="N",
                        help="dibujar N aliens EXTRA en las direcciones 16+2k / 17+2k (practica)")
    imagen.add_argument("--no-abrir", action="store_true", help="no abrir la imagen al terminar")
    imagen.add_argument("--sin-imagen", action="store_true", help="no dibujar la pantalla")
    parser.add_argument("--ver-todo", action="store_true",
                        help="listar tambien las variables de las direcciones 0 a 6 (E/S)")
    return parser


def _abrir(ruta: Path) -> bool:
    """Abre la imagen con el visor del sistema. Devuelve False si no se pudo."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(ruta))  # type: ignore[attr-defined]
            return True
        comando = "open" if sys.platform == "darwin" else "xdg-open"
        if shutil.which(comando) is None:
            return False
        subprocess.Popen(
            [comando, str(ruta)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def _variables(programa, maquina, ver_todo: bool) -> list[tuple[str, int, str]]:
    filas = []
    for entrada in sorted(programa.data, key=lambda e: programa.symbols[e.name]):
        direccion = programa.symbols[entrada.name]
        if direccion < PRIMERA_DIRECCION_DE_DATOS and not ver_todo:
            continue
        if entrada.size == 1:
            valor = maquina.ram[direccion]
            texto = f"{valor} (0x{valor:04X})"
        else:
            valores = [maquina.ram[direccion + i] for i in range(entrada.size)]
            texto = "[" + ", ".join(str(v) for v in valores) + "]"
        filas.append((entrada.name, direccion, texto))
    return filas


def _guardar_gif(fotos, ruta: Path, escala: int, ms_por_cuadro: int) -> None:
    from PIL import Image

    cuadros = [Image.fromarray(foto, "RGB") for foto in fotos]
    if escala > 1:
        cuadros = [c.resize((c.width * escala, c.height * escala), Image.NEAREST) for c in cuadros]
    cuadros[0].save(ruta, save_all=True, append_images=cuadros[1:], duration=ms_por_cuadro, loop=0)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ruta = Path(args.programa)

    # 1. Ensamblar
    try:
        tabla = suasm.load_opcodes()
        programa = suasm.assemble_file(ruta, tabla)
    except suasm.AsmError as exc:
        print(f"ERROR al ensamblar {ruta}:\n  {exc}", file=sys.stderr)
        return 1
    print(f"Ensamblado OK: {programa.size} palabras de ROM "
          f"({len(programa.data)} variables, el CODE empieza en {programa.code_start:04X}).")

    # 2. Ejecutar
    maquina = cli._build_machine(
        programa,
        switches=args.switches,
        buttons=args.botones,
        flags_mode="hardware",
        warn=True,
        clock_hz=RELOJ_HZ,
        inputs=cli._parse_inputs(args.input),
    )
    if args.ciclos:
        total = args.ciclos
    else:
        frames = args.frames or (12 if args.gif else 1)
        total = frames * cpu.CYCLES_PER_FRAME

    # La inicializacion de DATA escribe en direcciones de E/S como parte del
    # template: no es un error del programa, asi que no se avisa de eso.
    prologo = min(programa.code_start, total)
    maquina.run(prologo)
    maquina.shadow_warnings.clear()
    restante = total - prologo

    # 3. Preparar el dibujo (necesita numpy, Pillow y los .coe)
    gpu = None
    imagenes = None
    aviso_imagen = None
    if not args.sin_imagen:
        try:
            import gpu as gpu_modulo

            imagenes = gpu_modulo.load_sprite_images()
            gpu = gpu_modulo
        except ImportError as exc:
            aviso_imagen = f"falta una libreria ({exc}); instala con: pip install -r requirements.txt"
        except FileNotFoundError as exc:
            aviso_imagen = str(exc)

    fotos = []
    if args.gif and gpu is not None:
        tomas = max(2, args.tomas)
        por_toma = max(1, restante // tomas)
        for _ in range(tomas - 1):
            maquina.run(por_toma)
            fotos.append(gpu.render(maquina, imagenes, extra_enemies=args.aliens))
        maquina.run(max(0, restante - por_toma * (tomas - 1)))
    else:
        maquina.run(restante)

    ms = total / RELOJ_HZ * 1000
    print(f"Ejecutado: {total} ciclos (~{total / cpu.CYCLES_PER_FRAME:.1f} frame, {ms:.1f} ms a 50 MHz). "
          f"Switches=0x{args.switches:04X}, botones={args.botones}.")

    # 4. Variables, salidas y avisos
    print("\nVariables al terminar (nombre, direccion, valor):")
    filas = _variables(programa, maquina, args.ver_todo)
    ancho = max((len(n) for n, _, _ in filas), default=0)
    for nombre, direccion, texto in filas:
        print(f"  {nombre:<{ancho}}  dir {direccion:>3}  =  {texto}")
    if not args.ver_todo:
        print(f"  (las direcciones 0 a {PRIMERA_DIRECCION_DE_DATOS - 1} son entradas/salidas; "
              f"--ver-todo las muestra)")
    print(f"\nDisplay = 0x{maquina.display:04X}    LEDs = 0x{maquina.leds:04X}")

    if maquina.flag_warnings or maquina.shadow_warnings:
        print("\nAVISOS:")
        for linea in maquina.warnings_text().splitlines():
            print(f"  - {linea}")

    # 5. Imagen
    if args.sin_imagen:
        return 0
    if gpu is None:
        print(f"\nNo se pudo dibujar la imagen: {aviso_imagen}")
        return 0

    cuadro = gpu.render(maquina, imagenes, extra_enemies=args.aliens)
    sufijo = ".gif" if args.gif else ".png"
    salida = Path(args.salida) if args.salida else ruta.with_suffix(sufijo)
    try:
        if args.gif:
            fotos.append(cuadro)
            ms_cuadro = max(50, int((restante // max(2, args.tomas)) / RELOJ_HZ * 1000))
            _guardar_gif(fotos, salida, args.escala, ms_cuadro)
        else:
            cli._save_png(cuadro, salida, args.escala)
    except ImportError as exc:
        print(f"\nNo se pudo guardar la imagen: falta {exc}. Instala con: pip install -r requirements.txt")
        return 0

    print(f"\nImagen guardada en: {salida}")
    if not args.no_abrir:
        if _abrir(salida):
            print("(abierta en tu visor de imagenes)")
        else:
            print("(no pude abrirla automaticamente: abre ese archivo a mano)")
    print("\nSiguiente paso: edita tu archivo y vuelve a ejecutar el mismo comando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
