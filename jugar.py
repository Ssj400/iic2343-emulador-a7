#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Juega tu programa en una ventana, en vivo, con el teclado como botones de la placa.

    python3 jugar.py mi_programa.suasm

Teclas:
  Flechas ............ botones izquierda / derecha / arriba / abajo
  Espacio o Enter .... boton central
  S .................. switch 15 (el de inicio): arriba / abajo
  0 a 9 .............. switches 0 a 9: arriba / abajo
  + / - .............. mas rapido / mas lento
  P .... pausa        R .... reiniciar        Esc .... salir

Velocidad: el emulador ejecuta del orden de 1 millon de instrucciones por segundo,
unas 50 veces menos que la placa. Para que el juego no vaya en camara lenta, por
defecto el timer avanza 50 veces mas rapido respecto de las instrucciones (un tick
de ``timer_milisegundos`` cada 2 000 instrucciones en vez de 100 000). Eso se
comporta como la placa mientras tu programa haga menos de ~2 000 instrucciones
entre ticks. Con ``--acelerar 1`` el timer es exacto, pero todo va en camara lenta.

Necesita PyQt6 (``pip install PyQt6``), numpy, Pillow y el material del curso
preparado con ``preparar_materiales.py``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EMU_DIR))

import cpu  # noqa: E402
import suasm  # noqa: E402

try:  # PyQt6 es opcional: solo hace falta para jugar
    from PyQt6 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover - depende del entorno
    QtCore = QtGui = QtWidgets = None

CICLOS_POR_US_REAL = 100          # prescaler de Timer.vhd: cuenta 0..99
VELOCIDADES = (1, 2, 5, 10, 20, 50, 100)
TICKS_MS_POR_SEGUNDO_PLACA = 500  # a 50 MHz (supuesto): un tick cada 2 ms
PRESUPUESTO_S = 0.03              # tiempo de emulacion por cuadro dibujado
LOTE = 2_000                      # instrucciones por llamada a run()


def ciclos_por_us(acelerar: int) -> int:
    """Ciclos de reloj por microsegundo del timer con el factor dado."""
    return max(1, round(CICLOS_POR_US_REAL / max(1, acelerar)))


class MaquinaAcelerada(cpu.Machine):
    """La misma maquina, pero con un timer que puede avanzar mas rapido."""

    ciclos_por_us = CICLOS_POR_US_REAL

    def _tick_timer(self) -> None:
        if self._prescaler >= self.ciclos_por_us - 1:
            self._prescaler = 0
            if self._us == 999:
                self._us = 0
                if self._ms == 999:
                    self._ms = 0
                    self._s = (self._s + 1) & cpu.WORD_MASK
                else:
                    self._ms += 1
            else:
                self._us += 1
        else:
            self._prescaler += 1


def construir_maquina(programa, switches: int = 0, acelerar: int = 50) -> MaquinaAcelerada:
    """Crea la maquina y ejecuta la inicializacion de DATA (sin avisos de E/S)."""
    maquina = MaquinaAcelerada(
        rom=programa.rom,
        keys=[row.key for row in programa.listing],
        switches=switches,
        buttons=0,
        flags_mode="hardware",
        warn_branch_without_cmp=True,
    )
    maquina.init_words = programa.code_start
    maquina.ciclos_por_us = ciclos_por_us(acelerar)
    # La inicializacion de DATA escribe en direcciones de E/S como parte del
    # template: no es un error del programa.
    maquina.run(programa.code_start)
    maquina.shadow_warnings.clear()
    return maquina


def _valor(maquina, nombre: str) -> int:
    valor = getattr(maquina, nombre)
    return valor() if callable(valor) else valor


if QtWidgets is not None:

    _K = QtCore.Qt.Key
    TECLAS_BOTON = {
        _K.Key_Left.value: 4,
        _K.Key_Right.value: 8,
        _K.Key_Up.value: 2,
        _K.Key_Down.value: 16,
        _K.Key_Space.value: 1,
        _K.Key_Return.value: 1,
        _K.Key_Enter.value: 1,
    }
    NOMBRES_BOTON = {1: "centro", 2: "arriba", 4: "izquierda", 8: "derecha", 16: "abajo"}

    class VentanaJuego(QtWidgets.QWidget):
        """Pantalla 640x480 + estado de la placa + teclado como botones."""

        def __init__(self, programa, gpu, imagenes, acelerar=50, aliens=0, escala=1, switches=0):
            super().__init__()
            self.programa = programa
            self.gpu = gpu
            self.imagenes = imagenes
            self.acelerar = acelerar
            self.aliens = aliens
            self.escala = max(1, escala)
            self.switches = switches & cpu.WORD_MASK
            self.pausa = False
            self.teclas: set[int] = set()

            self.setWindowTitle(f"A7 - {Path(programa.source_name).name}")
            self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

            self.pantalla = QtWidgets.QLabel()
            self.pantalla.setFixedSize(640 * self.escala, 480 * self.escala)
            mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
            self.estado = QtWidgets.QLabel()
            self.estado.setFont(mono)
            # Tres lineas de estado: se reserva su alto para que no se monten con la imagen.
            self.estado.setMinimumHeight(QtGui.QFontMetrics(mono).lineSpacing() * 3 + 6)
            self.ayuda = QtWidgets.QLabel(
                "Flechas = botones   Espacio = centro   S = switch de inicio (15)   "
                "0-9 = switches\n+ / - = velocidad   P = pausa   R = reiniciar   Esc = salir"
            )
            for etiqueta in (self.pantalla, self.estado, self.ayuda):
                etiqueta.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

            capas = QtWidgets.QVBoxLayout(self)
            capas.addWidget(self.pantalla)
            capas.addWidget(self.estado)
            capas.addWidget(self.ayuda)

            self.reiniciar()
            self.reloj = QtCore.QTimer(self)
            self.reloj.timeout.connect(self.paso)
            self.reloj.start(0)

        # -- simulacion ---------------------------------------------------------

        def reiniciar(self) -> None:
            self.maquina = construir_maquina(self.programa, self.switches, self.acelerar)
            self.maquina.buttons = self._botones()
            self._medida = (time.perf_counter(), self.maquina.cycles)
            self.instr_por_s = 0.0

        def paso(self) -> None:
            inicio = time.perf_counter()
            if not self.pausa:
                while time.perf_counter() - inicio < PRESUPUESTO_S:
                    self.maquina.run(LOTE)
            self._dibujar()
            self._actualizar_estado()

        def _dibujar(self) -> None:
            cuadro = self.gpu.render(self.maquina, self.imagenes, extra_enemies=self.aliens)
            alto, ancho, _ = cuadro.shape
            datos = cuadro.tobytes()
            imagen = QtGui.QImage(datos, ancho, alto, 3 * ancho, QtGui.QImage.Format.Format_RGB888)
            mapa = QtGui.QPixmap.fromImage(imagen)
            if self.escala > 1:
                mapa = mapa.scaled(ancho * self.escala, alto * self.escala)
            self.pantalla.setPixmap(mapa)

        def _actualizar_estado(self) -> None:
            ahora = time.perf_counter()
            t0, c0 = self._medida
            if ahora - t0 >= 0.5:
                self.instr_por_s = (self.maquina.cycles - c0) / (ahora - t0)
                self._medida = (ahora, self.maquina.cycles)
            ticks_por_s = self.instr_por_s / (ciclos_por_us(self.acelerar) * 1000)
            porcentaje = 100 * ticks_por_s / TICKS_MS_POR_SEGUNDO_PLACA
            m = self.maquina
            pulsados = [n for v, n in NOMBRES_BOTON.items() if m.buttons & v] or ["-"]
            avisos = len(m.flag_warnings) + len(m.shadow_warnings)
            self.estado.setText(
                f"Display: 0x{m.display:04X} ({m.display:5d})   LEDs: {m.leds:016b}\n"
                f"Switches: {m.switches:016b}   Botones: {', '.join(pulsados)}\n"
                f"Timer: {_valor(m, 'timer_seconds'):3d} s {_valor(m, 'timer_milliseconds'):3d} ms   "
                f"Velocidad: x{self.acelerar} (~{porcentaje:3.0f}% de la placa)   "
                f"{self.instr_por_s / 1e6:4.2f} M instr/s"
                f"{'   EN PAUSA' if self.pausa else ''}"
                f"{f'   avisos: {avisos} (se listan al cerrar)' if avisos else ''}"
            )

        # -- teclado ------------------------------------------------------------

        def _botones(self) -> int:
            valor = 0
            for tecla in self.teclas:
                valor |= TECLAS_BOTON.get(tecla, 0)
            return valor

        def _alternar_switch(self, numero: int) -> None:
            self.switches ^= 1 << numero
            self.maquina.switches = self.switches

        def _cambiar_velocidad(self, sentido: int) -> None:
            posicion = min(range(len(VELOCIDADES)), key=lambda i: abs(VELOCIDADES[i] - self.acelerar))
            posicion = max(0, min(len(VELOCIDADES) - 1, posicion + sentido))
            self.acelerar = VELOCIDADES[posicion]
            self.maquina.ciclos_por_us = ciclos_por_us(self.acelerar)

        def keyPressEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
            if evento.isAutoRepeat():
                return
            tecla = evento.key()
            if tecla in TECLAS_BOTON:
                self.teclas.add(tecla)
                self.maquina.buttons = self._botones()
            elif tecla == _K.Key_S.value:
                self._alternar_switch(15)
            elif _K.Key_0.value <= tecla <= _K.Key_9.value:
                self._alternar_switch(tecla - _K.Key_0.value)
            elif tecla in (_K.Key_Plus.value, _K.Key_Equal.value):
                self._cambiar_velocidad(+1)
            elif tecla == _K.Key_Minus.value:
                self._cambiar_velocidad(-1)
            elif tecla == _K.Key_P.value:
                self.pausa = not self.pausa
            elif tecla == _K.Key_R.value:
                self.reiniciar()
            elif tecla == _K.Key_Escape.value:
                self.close()
            else:
                super().keyPressEvent(evento)

        def keyReleaseEvent(self, evento) -> None:  # noqa: N802
            if evento.isAutoRepeat():
                return
            if evento.key() in self.teclas:
                self.teclas.discard(evento.key())
                self.maquina.buttons = self._botones()

        def focusOutEvent(self, evento) -> None:  # noqa: N802
            # Si la ventana pierde el foco, se sueltan todos los botones.
            self.teclas.clear()
            self.maquina.buttons = 0
            super().focusOutEvent(evento)

        def closeEvent(self, evento) -> None:  # noqa: N802
            self.reloj.stop()
            super().closeEvent(evento)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jugar.py",
        description="Juega tu programa en una ventana, con el teclado como botones de la placa.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Teclas:", 1)[1].split("Velocidad:", 1)[0].join(("Teclas:", "")),
    )
    parser.add_argument("programa", help="archivo .suasm a jugar")
    parser.add_argument("--acelerar", type=int, default=50,
                        help="cuantas veces mas rapido avanza el timer (por defecto 50; 1 = exacto "
                             "pero en camara lenta)")
    parser.add_argument("--aliens", type=int, default=0, metavar="N",
                        help="dibujar N aliens EXTRA en las direcciones 16+2k / 17+2k (practica)")
    parser.add_argument("--escala", type=int, default=1, help="ampliar la ventana N veces")
    parser.add_argument("--switches", type=lambda t: int(t, 0), default=0,
                        help="switches al inicio (por defecto todos abajo; S sube el de inicio)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ruta = Path(args.programa)
    try:
        programa = suasm.assemble_file(ruta, suasm.load_opcodes())
    except suasm.AsmError as exc:
        print(f"ERROR al ensamblar {ruta}:\n  {exc}", file=sys.stderr)
        return 1
    if QtWidgets is None:
        print("Para jugar hace falta PyQt6: pip install PyQt6", file=sys.stderr)
        return 1
    try:
        import gpu

        imagenes = gpu.load_sprite_images()
    except ImportError as exc:
        print(f"Falta una libreria ({exc}): pip install -r requirements.txt", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    ventana = VentanaJuego(programa, gpu, imagenes, acelerar=args.acelerar,
                           aliens=args.aliens, escala=args.escala, switches=args.switches)
    ventana.show()
    print(f"Jugando {ruta} (velocidad x{args.acelerar}). Cierra la ventana o pulsa Esc para salir.")
    app.exec()

    maquina = ventana.maquina
    if maquina.flag_warnings or maquina.shadow_warnings:
        print("\nAVISOS durante la partida:")
        for linea in maquina.warnings_text().splitlines():
            print(f"  - {linea}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
