#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interfaz de linea de comandos del emulador de ACF7.

Ejemplos:
    python3 cli.py asm   programa.suasm
    python3 cli.py run   programa.suasm --steps 500
    python3 cli.py run   programa.suasm --frames 1
    python3 cli.py trace programa.suasm --max 80
    python3 cli.py selftest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cpu as cpu_module
import suasm


def _build_machine(
    program: suasm.Program,
    *,
    switches: int = 0,
    buttons: int = 0,
    flags_mode: str = "hardware",
    warn: bool = True,
    clock_hz: int = 50_000_000,
    inputs: list[tuple[int, str, int]] | None = None,
) -> cpu_module.Machine:
    keys = [row.key for row in program.listing]
    machine = cpu_module.Machine(
        rom=program.rom,
        keys=keys,
        switches=switches,
        buttons=buttons,
        flags_mode=flags_mode,
        warn_branch_without_cmp=warn,
        clock_hz=clock_hz,
    )
    machine.init_words = program.code_start
    for cycle, field, value in inputs or []:
        machine.schedule_input(cycle, field, value)
    return machine


def _parse_inputs(specs: list[str]) -> list[tuple[int, str, int]]:
    events = []
    for spec in specs:
        parts = spec.split(":")
        if len(parts) != 3:
            raise SystemExit(f"--input espera CICLO:campo:valor, no {spec!r}")
        cycle, field, value = parts
        events.append((int(cycle, 0), field.strip(), int(value, 0)))
    return events


def _load(args: argparse.Namespace) -> tuple[suasm.Program, cpu_module.Machine]:
    table = suasm.load_opcodes(args.opcodes)
    program = suasm.assemble_file(args.program, table)
    machine = _build_machine(
        program,
        switches=args.switches,
        buttons=args.buttons,
        flags_mode=args.flags_mode,
        warn=not args.no_warn,
        clock_hz=args.clock,
        inputs=_parse_inputs(args.input),
    )
    return program, machine


def cmd_asm(args: argparse.Namespace) -> int:
    table = suasm.load_opcodes(args.opcodes)
    program = suasm.assemble_file(args.program, table)
    print(suasm.render_listing(program, limit=args.limit))
    print()
    print("Simbolos:")
    print(suasm.render_symbols(program))
    for warning in program.warnings:
        print(f"aviso: {warning}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    program, machine = _load(args)
    print(f"Programa {program.source_name}: {program.size} palabras, "
          f"CODE empieza en {program.code_start:04X}")
    print(machine.state_text())
    if args.frames:
        machine.run_frames(args.frames)
    else:
        machine.run(args.steps)
    print("--- despues ---")
    print(machine.state_text())
    if machine.last_write:
        address, value = machine.last_write
        print(f"ultima escritura: [{address:03X}] = {value:04X}")
    if program.data:
        end = max(entry.address + entry.size for entry in program.data)
        print("--- DATA (RAM) ---")
        print(machine.ram_dump(0, end))
    if args.ram:
        start, stop = args.ram
        print(f"--- RAM {start:04X}..{stop:04X} ---")
        print(machine.ram_dump(start, stop))
    if machine.flag_warnings or machine.shadow_warnings:
        print("--- avisos ---")
        print(machine.warnings_text())
    if args.timing:
        print(cpu_module.timing_report(args.clock))
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    program, machine = _load(args)
    step = args.every
    executed = 0
    index = 0
    while executed < args.max:
        pc = machine.pc & 0xFFF
        row = program.row_at(pc)
        source = row.source if row else "?"
        literal = row.literal if row else 0
        machine.step()
        executed += 1
        if index % step == 0:
            write = ""
            if machine.last_write:
                address, value = machine.last_write
                write = f"  [{address:03X}]<={value:04X}"
            print(
                f"{executed:06d} PC={pc:04X} lit={literal:04X} "
                f"{machine.registers_text} SP={machine.sp & 0xFFF:03X} "
                f"{machine.flags_text}{write}  {source}"
            )
        index += 1
    return 0


def _save_png(frame, path: Path, scale: int = 1) -> None:
    from PIL import Image

    image = Image.fromarray(frame, "RGB")
    if scale > 1:
        image = image.resize(
            (image.width * scale, image.height * scale), Image.NEAREST
        )
    image.save(path)


def cmd_frame(args: argparse.Namespace) -> int:
    import gpu

    program, machine = _load(args)
    total = args.frames * cpu_module.CYCLES_PER_FRAME if args.frames else args.steps
    images = gpu.load_sprite_images()
    extra = getattr(args, "extra_enemies", 0)
    shots = max(2, args.shots)
    sampled = []
    per_shot = 0

    if args.gif:
        per_shot = max(1, total // shots)
        for _ in range(shots - 1):
            machine.run(per_shot)
            sampled.append(gpu.render(machine, images, extra_enemies=extra))
        machine.run(max(0, total - per_shot * (shots - 1)))
    else:
        machine.run(total)

    frame = gpu.render(machine, images, extra_enemies=extra)
    print(f"Programa {program.source_name}: {program.size} palabras, "
          f"CODE empieza en {program.code_start:04X}")
    print(machine.state_text())
    print("--- sprites ---")
    print(gpu.describe(machine, extra_enemies=extra))
    if extra:
        print(f"({extra} enemigos extra de practica: x=16+2k, y=17+2k; "
              f"suposicion del emulador, no de la base entregada)")
    print(f"cuadro 640x480: {int((frame != 0).any(axis=2).sum())} pixeles no negros")

    out = Path(args.out) if args.out else (None if args.gif else Path("frame.png"))
    if out:
        _save_png(frame, out, args.scale)
        print(f"imagen guardada en {out} ({args.scale}x)")

    if args.gif:
        from PIL import Image

        sampled.append(frame)
        duration = max(50, int(per_shot / args.clock * 1000))
        pictures = [Image.fromarray(item, "RGB") for item in sampled]
        if args.scale > 1:
            pictures = [
                item.resize(
                    (item.width * args.scale, item.height * args.scale),
                    Image.NEAREST,
                )
                for item in pictures
            ]
        pictures[0].save(
            args.gif,
            save_all=True,
            append_images=pictures[1:],
            duration=duration,
            loop=0,
        )
        print(f"gif guardado en {args.gif}: {len(pictures)} cuadros, "
              f"{duration} ms por cuadro")

    if machine.flag_warnings or machine.shadow_warnings:
        print("--- avisos ---")
        print(machine.warnings_text())
    return 0


# ----------------------------------------------------------------------------
# Autoprueba: programas propios y minimos, no soluciones de la actividad
# ----------------------------------------------------------------------------

SELFTEST_SOURCE = """
DATA:
  resultado 0
  contador 0

CODE:
inicio:
  MOV A, 5
  MOV B, 3
  ADD A, B            // A = 8
  MOV (resultado), A
  CALL doblar         // A = 16
  MOV (resultado), A
  PUSH A
  MOV A, 0
  POP B               // B = 16
  MOV A, 1
  MOV (contador), A
  CMP A, 1
  JEQ igual
  MOV A, 0
  MOV (resultado), A
igual:
  JMP fin

doblar:
  ADD A, A
  RET

fin:
  JMP fin
"""


def cmd_selftest(args: argparse.Namespace) -> int:
    table = suasm.load_opcodes(args.opcodes)
    program = suasm.assemble(SELFTEST_SOURCE, table, "<autoprueba>")
    machine = _build_machine(program, flags_mode=args.flags_mode, clock_hz=args.clock)
    machine.run(400)
    print(suasm.render_listing(program))
    print()
    print(machine.state_text())
    print("--- DATA (RAM) ---")
    print(machine.ram_dump(0, 2))
    checks = [
        ("resultado == 16", machine.ram[0] == 16),
        ("contador == 1", machine.ram[1] == 1),
        ("B == 16 (PUSH/POP)", machine.registers[1] == 16),
        ("SP intacto (0xFFF)", (machine.sp & 0xFFF) == 0xFFF),
        ("termino en 'fin'", (machine.pc & 0xFFF) == program.symbols["fin"]),
    ]
    ok = True
    for label, passed in checks:
        print(f"[{'ok' if passed else 'FALLA'}] {label}")
        ok = ok and passed
    if machine.flag_warnings or machine.shadow_warnings:
        print("--- avisos ---")
        print(machine.warnings_text())
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emulador del computador basico de ACF7 (practica, sin VGA).",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--opcodes",
        default=None,
        help="tabla de opcodes alternativa (por defecto minki_opcodes.json)",
    )
    common.add_argument("--clock", type=lambda text: int(float(text)),
                        default=50_000_000, metavar="HZ",
                        help="reloj en Hz para los informes de tiempo; acepta 25000000 "
                             "o 25e6 (por defecto 50e6)")
    common.add_argument("--flags-mode", choices=("hardware", "sticky"),
                        default="hardware",
                        help="'hardware' pisa banderas en cada ciclo; "
                             "'sticky' es una variante hipotetica")
    common.add_argument("--no-warn", action="store_true",
                        help="desactiva el aviso de salto condicional sin CMP")
    common.add_argument("--switches", type=lambda s: int(s, 0), default=0,
                        help="valor inicial de los 16 switches")
    common.add_argument("--buttons", type=lambda s: int(s, 0), default=0,
                        help="botones apretados (bit 0 centro, 1 arriba, "
                             "2 izquierda, 3 derecha, 4 abajo)")
    common.add_argument("--input", action="append", default=[],
                        metavar="CICLO:CAMPO:VALOR",
                        help="cambio de entrada guionado, por ejemplo "
                             "1000:buttons:0x8 (se puede repetir)")

    sub = parser.add_subparsers(dest="command", required=True)

    asm = sub.add_parser("asm", parents=[common],
                         help="ensamblar y mostrar el listado ROM")
    asm.add_argument("program")
    asm.add_argument("--limit", type=int, default=None,
                     help="mostrar solo las primeras N palabras")
    asm.set_defaults(func=cmd_asm)

    run = sub.add_parser("run", parents=[common], help="ensamblar y ejecutar")
    run.add_argument("program")
    run.add_argument("--steps", type=int, default=1000)
    run.add_argument("--frames", type=int, default=0,
                     help="ejecutar N frames completos (416800 ciclos cada uno)")
    run.add_argument("--ram", type=lambda s: int(s, 0), nargs=2, metavar=("INI", "FIN"))
    run.add_argument("--timing", action="store_true")
    run.set_defaults(func=cmd_run)

    frame = sub.add_parser("frame", parents=[common],
                           help="ejecutar y guardar el cuadro VGA en PNG/GIF")
    frame.add_argument("program")
    frame.add_argument("--steps", type=int, default=cpu_module.CYCLES_PER_FRAME,
                       help="ciclos a ejecutar antes de la foto (416800 = 1 frame)")
    frame.add_argument("--frames", type=int, default=0,
                       help="en vez de --steps, ejecutar N frames completos")
    frame.add_argument("--out", default=None,
                       help="PNG de salida (por defecto frame.png)")
    frame.add_argument("--scale", type=int, default=2,
                       help="ampliar la imagen N veces (vecino mas cercano)")
    frame.add_argument("--gif", default=None,
                       help="guardar una animacion GIF en esta ruta")
    frame.add_argument("--shots", type=int, default=12,
                       help="cuantos cuadros muestrear para el GIF")
    frame.add_argument("--extra-enemies", type=int, default=0, metavar="N",
                       help="anadir N enemigos de practica (30x30 en 16+2k/17+2k; "
                            "suposicion, no esta en la base entregada)")
    frame.set_defaults(func=cmd_frame)

    trace = sub.add_parser("trace", parents=[common],
                           help="traza instruccion por instruccion")
    trace.add_argument("program")
    trace.add_argument("--max", type=int, default=200, help="pasos a ejecutar")
    trace.add_argument("--every", type=int, default=1, help="imprimir 1 de cada N")
    trace.set_defaults(func=cmd_trace)

    selftest = sub.add_parser("selftest", parents=[common],
                              help="autoprueba minima del entorno")
    selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except suasm.AsmError as exc:
        print(f"error de ensamblado: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"archivo no encontrado: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
