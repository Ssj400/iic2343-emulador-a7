# Entorno de práctica A7 — emulador en Python

Estado: **2026-11-15**. Este documento es la especificación y el registro de decisiones del
entorno de práctica para la actividad A7 (Space Invaders sobre VGA en Basys3): alcance, hechos
extraídos del VHDL del proyecto base y reglas de fidelidad que el emulador respeta. Las
secciones 1 a 10 se escribieron antes del código (están en tiempo futuro); la sección 11
recoge lo que quedó implementado. Para usar el emulador, lee `README.md`.

Todo lo descrito abajo proviene de leer los fuentes VHDL del proyecto base de ACF7
(`IIC2343_ProyectoBaseACF_7.zip`, carpeta `.../Proyecto Base.srcs/sources_1/new/`). Las
referencias del tipo `archivo.vhd:línea` (y `_x/archivo.vhd`) apuntan a esos fuentes
extraídos del ZIP del curso, que **no** se incluyen en este repositorio. Nada del proyecto
base fue modificado.

---

## 1. ¿Se puede emular la parte VGA?

Sí, y sin emular la señal analógica. La señal VGA sólo aporta sincronización y color; lo que
la actividad evalúa es la cadena:

```
escritura de RAM (posición del sprite)  ->  SM compara con el puntero de barrido  ->
color del píxel  ->  prioridad  ->  RGB 4-4-4
```

Eso es exactamente lo que un emulador puede reproducir. Basta con generar el frame 640x480
como imagen (PNG/GIF) en vez de como voltajes:

- se ejecuta la CPU instrucción por instrucción sobre la RAM real;
- cada escritura a RAM actualiza los registros `x1`/`y1` de los sprite managers, igual que en la placa;
- al terminar los ciclos de un frame se recorre el raster y se calcula el color de cada píxel;
- el resultado se guarda como imagen, o como GIF/MP4 para ver movimiento.

Lo que se pierde: el comportamiento eléctrico de la señal, el debounce real de los botones y
la latencia de la placa. Lo que se conserva —y es lo que importa para la nota— es **qué se ve
en pantalla para un programa dado**, incluidos los bugs de direcciones de memoria, de
prioridad o de geometría.

### Alternativas descartadas

| Vía | Por qué no |
|---|---|
| Simulación VHDL completa (Vivado/GHDL) | No hay `vivado`, `ghdl` ni `wine` en esta máquina; además las memorias de sprite son IP de Xilinx (`blk_mem_gen`) con `.coe`, que GHDL no compila. |
| Emular el protocolo VGA (píxel a píxel, sync) | No aporta nada: la resolución y el timing no se evalúan, se evalúa la imagen. |
| Monitor VGA físico | Para practicar en casa normalmente no se dispone de uno. |

### Herramientas verificadas en esta máquina (2026-11-15)

| Herramienta | Estado |
|---|---|
| `python3` 3.14.8 + `numpy` 2.5.4, `PIL` 13.0.0, `matplotlib`, `pandas` | presentes |
| `ffmpeg`, `convert` (ImageMagick), `java`, `node` | presentes |
| `vivado`, `ghdl`, `gtkwave`, `wine`, `xvfb-run` | **ausentes** |

Conclusión: Python + numpy + Pillow es suficiente; no se necesita instalar nada.

---

## 2. Máquina a emular

| Bloque | Fuente | Comportamiento |
|---|---|---|
| CPU | `CPU.vhd`, `SuperRegisterFile.vhd`, `RegisterFile.vhd`, `ALU.vhd`, `Adder16.vhd` | 4 registros A, B, C, D de 16 bits; PC y SP de 12 bits efectivos; status C, Z, N |
| ROM | `ROM.vhd` | 4096 palabras de **62 bits** (16 literal + 46 control), lectura combinacional |
| RAM | `RAM.vhd` | 4096 palabras de 16 bits, lectura combinacional, escritura en flanco |
| Timer | `Timer.vhd` | prescaler 0–99, luego µs/ms/s hasta 999 |
| Reloj | `Clock_Divider.vhd` con `speed = "00"` | ≈**50 MHz** (no 25 MHz) |
| I/O | `Basys3.vhd` | multiplexor de lectura, registros de display y LEDs |
| Video | `Xelor.vhd`, `GraphicsProcessor.vhd`, 4 SM | 640x480, 4 capas con prioridad fija |

No hay interrupciones ni DMA: el programa hace polling de switches, botones y timer.

---

## 3. Formato de palabra e instrucción

Palabra ROM de 62 bits: `rom_dataout(61 downto 46)` = literal de 16 bits,
`rom_dataout(45 downto 0)` = palabra de control. La tabla de opcodes del ensamblador
(`directives/minki_opcodes.json`, 389 mnemónicos) contiene **sólo los 46 bits de control**;
el ensamblador agrega el literal cuando la instrucción lo lleva. Los 394 valores del archivo
tienen largo 46, lo que confirma esa separación.

### Campos de control (decodificados desde `ControlUnit.vhd`)

| Bits (45..0) | Señal | Valores |
|---|---|---|
| 7..0 | `SelALU` (one-hot) | `00000001` ADD, `00000010` SUB, `00000100` AND, `00001000` OR, `00010000` XOR, `00100000` NOT, `01000000` SHR, `10000000` SHL. **Cualquier otro valor cae en `111` = SHL** |
| 8 | `LReg` | 1 = escribir el registro destino con el resultado |
| 12..9 | `selectFirst` (one-hot) | `0001` A, `0010` B, `0100` C, otro = D |
| 16..13 | `selectSecond` (one-hot) | ídem |
| 20..17 | `SReg` (destino, one-hot) | `0001` A, `0010` B, `0100` C, otro = D |
| 23..21 | `SelOne` | `001` = primer operando, `010` = constante 1, otro = constante 0 |
| 27..24 | `SelTwo` | `0001` = segundo operando, `0010` = constante 0, `0100` = literal, otro = dato leído de RAM/I/O |
| 29..28 | `SelDIn` | `01` = resultado de la ALU, otro = PC+1 |
| 30 | `w` | 1 = `ram_write` |
| 33..31 | `SelAdd` | `001` = literal(57..46), `010` = B(11..0), otro = SP |
| 34 | `incSP` | 1 = SP+1 |
| 35 | `decSP` | 1 = SP-1 |
| 43..36 | condición de `loadPC` (one-hot) | `01` siempre, `02` Z, `04` no Z, `08` no Z y no N, `10` no N, `20` N, `40` Z o N, `80` C; otro = 0 |
| 45..44 | `SelPC` | `01` = literal(57..46), otro = RAM(11..0) (retorno) |

Nota: el literal de 16 bits también es la fuente de la dirección de salto, pero sólo se usan
sus 12 bits bajos (`57..46`), que coinciden con `literal(11..0)`.

### ALU (`ALU.vhd`)

| `sop` | Resultado | C | N |
|---|---|---|---|
| `000` ADD | a + b | carry de salida | 0 |
| `001` SUB | a - b (b invertido, cin=1) | carry de salida | **no carry** (= 1 si a < b sin signo) |
| `010` AND | a and b | 0 | 0 |
| `011` OR | a or b | 0 | 0 |
| `100` XOR | a xor b | 0 | 0 |
| `101` NOT | not a | 0 | 0 |
| `110` SHR | `0 & a(15..1)` | a(0) | 0 |
| `111` SHL | `a(14..0) & 0` | a(15) | 0 |

`Z` = 1 si el resultado es `0000000000000000`, para todas las operaciones.

---

## 4. Semántica de instrucciones (verificada decodificando la tabla)

Se decodificaron los 389 mnemónicos con las reglas de `ControlUnit.vhd`; estas son las formas
reales que usa el ensamblador:

| Instrucción | Palabras | Efecto real en el hardware |
|---|---|---|
| `MOV Rx, Ry` | 1 | `Rx := Ry + 0` por la ALU (LReg=1) |
| `MOV Rx, Lit` | 1 | `Rx := 0 + lit` |
| `MOV Rx, (dir)` | 1 | `Rx := MEM[dir]` (dir = literal de 12 bits) |
| `MOV Rx, (Ry)` | 1 | `Rx := MEM[Ry]` (dirección = registro) |
| `MOV (dir), Rx` | 1 | `MEM[dir] := Rx + 0`, con `w = 1` |
| `MOV (Ry), Rx` | 1 | `MEM[Ry] := Rx` |
| `MOV (Ry), Lit` | 1 | `MEM[Ry] := lit` |
| `ADD/SUB/AND/OR/XOR Rx, Ry` | 1 | operación, resultado en `Rx` |
| `ADD/SUB/... Rx, Lit` | 1 | ídem con literal |
| `ADD/SUB/... Rx, (Ry)` | 1 | ídem con dato de memoria |
| `NOT (Ry), Rx`, `SHL (Ry), Rx`, `SHR (Ry), Rx` | 1 | **memoria como destino**: `MEM[Ry] := op(Rx)` |
| `INC Rx` / `DEC Rx` | 1 | `Rx := Rx + 1` / `Rx - 1` (suma/resta con 1) |
| `INC (dir)` / `INC (Ry)` | 1 | incrementa la palabra de memoria |
| `CMP Rx, Ry` (o `Lit`, o `(Ry)`) | 1 | resta **sin** escribir registro: sólo actualiza banderas |
| `JMP Lit`, `JEQ`, `JNE`, `JGT`, `JGE`, `JLT`, `JLE`, `JCR` | 1 | salto condicional según la tabla de condición |
| `CALL Lit` | 1 | `MEM[SP] := PC+1`; `SP--`; `PC := Lit` |
| `RET` | **2** | `SP++` y luego `PC := MEM[SP](11..0)` |
| `PUSH Rx` | 1 | `MEM[SP] := Rx`; `SP--` |
| `POP Rx` | **2** | `SP++` y luego `Rx := MEM[SP]` |
| `NOP` | 1 | no escribe nada; **sí actualiza banderas** (ver §5) |

No existen `INC SP` / `DEC SP` en esta tabla de opcodes (a diferencia de ACE4). La pila se
maneja sólo con `PUSH`/`POP`/`CALL`/`RET`.

Como `RET` y `POP` ocupan **dos** palabras de ROM, cualquier etiqueta después de ellos queda
corrida: el ensamblador inserta la palabra extra y el `PC+1` de un `CALL` apunta a la
instrucción siguiente real, no a la línea fuente siguiente.

---

## 5. Banderas y rarezas verificadas

1. **El registro de estado se carga en todos los flancos** (`load = '1'` fijo en
   `RegisterFile.vhd`), con las banderas que produce la instrucción actual.
2. **Un salto destruye las banderas.** Los 8 saltos tienen bits ALU = `00000000`, que caen en
   el `when others` de `SelALU` = `111` (SHL). Con `SelOne = 0` el resultado es 0, por lo que
   después de **cualquier** salto queda `C = 0`, `Z = 1`, `N = 0`. Un segundo salto
   consecutivo, o un `JMP` seguido de un condicional sin `CMP` intermedio, ve `Z = 1`. `NOP`
   tiene exactamente el mismo efecto.
3. **`N` sólo significa algo después de `SUB`.** Para todas las demás operaciones `N = 0`,
   así que `JLT`/`JGT`/`JGE`/`JLE` sólo tienen sentido inmediatamente después de un `CMP`.
   La comparación es **sin signo**: `N = 1` significa `a < b`.
4. **Cualquier instrucción pisa las banderas**, incluidas `MOV` y las escrituras a memoria
   (la ALU calcula `valor + 0`: `Z` queda según el valor movido).
5. **`PC` se incrementa en cada ciclo** (`up = '1'`, `load = loadPC`): cada instrucción es un
   ciclo; una palabra de control = una instrucción.
6. **`SP` arranca en `0xFFFF`** (`Reg` con `load = clear`, `datain = FFFF`); sus 12 bits bajos
   valen `0xFFF`, así que el primer `PUSH` escribe en `0xFFF` y deja `SP = 0xFFE`. Esto es
   correcto en este proyecto (a diferencia de lo que ocurría en ACE4).
7. **Lecturas combinacionales**: `RAM.vhd` y `ROM.vhd` devuelven el dato en el mismo ciclo, sin
   latencia, así que el modelo de un ciclo por instrucción es fiel.
8. **Escribir en 0 o 2 escribe también en RAM**: el registro de LEDs (dirección 0) y el de
   display (dirección 2) se cargan con `write_ram`, pero la RAM recibe la misma escritura. Leer
   0 o 2 devuelve la última palabra escrita, no el registro.
9. **La dirección 0 está compartida con el fondo**: `backgroundSM` tiene `Ax1 = Ay1 = 0`, así
   que escribir LEDs mueve el fondo horizontalmente (`x1 := valor`; el `elsif` evita que se
   escriba `y1`). Conviene no usar LEDs en A7.
10. **Geometría con corrimiento**: cada SM dibuja en `x1 - 2 <= x < x1 + ancho - 2`
    (`hDiff = 2`), es decir, la imagen aparece 2 píxeles a la izquierda de `x1`. El índice de
    imagen es `(x + 2 - x1) + (y - y1) * ancho`.
11. **`x1 = 640` NO deja el sprite fuera de pantalla**: como la ventana parte en
    `x1 - 2`, con `x1 = 640` igual se dibujan las columnas 638 y 639 (la primera franja de la
    imagen). Para "matar" un alien de verdad hay que escribir `x1 >= 642` (p. ej. 700) o llevar
    `y1 >= 480`. Ver la rareza 1 de §11, comprobada en el render.
12. **`backgroundSM` no tiene prueba de rectángulo**: siempre dibuja, con dirección de 17 bits
    `(x + 2 - x1) + (y - y1) * 300`. Fuera de la imagen de 300x300 la dirección cae en zona no
    inicializada del BRAM (se asume negro). No se verificó en hardware.

---

## 6. Mapa de memoria e I/O

El ensamblador asigna DATA secuencialmente **desde 0**, así que el bloque DATA es a la vez el
mapa de I/O:

| Dirección | Lectura | Escritura |
|---|---|---|
| 0 | RAM (último valor) | registro de LEDs **y** RAM; además mueve el fondo |
| 1 | switches (16 bits) | RAM |
| 2 | RAM (último valor) | registro de display de 7 segmentos **y** RAM |
| 3 | botones con debounce, extendidos a 16 bits (bit 0 centro, 1 arriba, 2 izquierda, 3 derecha, 4 abajo) | RAM |
| 4 | `timer_segundos` | RAM |
| 5 | `timer_milisegundos` | RAM |
| 6 | `timer_microsegundos` | RAM |
| 7..4095 | RAM | RAM |

`switches` es el valor de los 16 interruptores; el bit 15 es el switch de la izquierda. En el
código del formativo se usa como switch de inicio.

Direcciones de los sprites (constantes del proyecto entregado):

| SM | Tamaño | `Ax1` | `Ay1` | Nota |
|---|---|---|---|---|
| `backgroundSM` | 300x300 | 0 | 0 | comparte dirección con LEDs |
| `mainShipSM` | 69x90 | **10** | **11** | |
| `enemyShipSM` | 30x30 | **12** | **13** | único enemigo instanciado |
| `ammoSM` | 10x10 | **14** | **15** | |

`base_invaders.txt` asigna `nave_x/nave_y` = 8/9, `alien1_x/y` = 10/11, `bala_x/y` = 12/13.
Para que la nave siga a `nave_x` hay que correr el mapa (por ejemplo agregando `a_x`/`a_y` en
8/9) o cambiar las constantes del VHDL. Llegar a 10 aliens exige
replicar el componente/instancia `enemyShipSM` con su propio par de direcciones y agregar su
rama a la cadena de prioridad.

Prioridad de color en `GraphicsProcessor.vhd`: nave > enemigo > munición > fondo. Un sprite
"tapa" al de menor prioridad sólo en los píxeles donde su color no es `000000000000`
(`inside_area` se fuerza a 0 en píxeles negros).

---

## 7. Tiempo: ciclos por frame y presupuesto de instrucciones

- `Xelor`: 800 x 521 ciclos por frame → **416 800 ciclos** = 8.34 ms a 50 MHz (≈120 Hz).
- La CPU usa el **mismo** reloj reducido: **1 instrucción por ciclo** → ~416 800 instrucciones
  por frame. Para la práctica esto significa que un lazo principal "lento" debe frenarse a
  propósito (con el timer o contando iteraciones).
- Timer: `counter` llega a 99 → 100 ciclos por tick de µs; 1000 ticks de µs → 1 de ms. Por lo
  tanto **1 tick de `timer_milisegundos` = 100 000 ciclos ≈ 2 ms reales**, y `timer_segundos`
  avanza cada ~2 s. El timer va a **la mitad de la velocidad nominal** y el contador de ms
  envuelve cada ~2 s, igual que en ACF5 pero con otra causa.
- Consecuencia práctica: comparar `timer_milisegundos` por igualdad exacta es frágil; conviene
  comparar "distinto de" un valor capturado, o contar ciclos propios.

Modelo del emulador: por defecto `cpu.cycles_per_frame = 416800`, y el timer se implementa con
la misma cuenta de ciclos (100 por µs). Ambos valores deben ser configurables para comparar
comportamientos sin cambiar el código del alumno.

---

## 8. Módulos propuestos

```
Laboratorio/ACF7/emu/
  suasm.py      ensamblador .suasm -> palabras de 62 bits (usa minki_opcodes.json)
  cpu.py        máquina: RAM, ROM, registros, ALU, banderas, timer, I/O, pila
  gpu.py        sprite managers + raster -> imagen 640x480 (numpy)   [hecho, F3]
  cli.py        asm, run, trace, frame, selftest (PNG/GIF)          [hecho, F3]
  coe/          los 12 .coe del proyecto entregado (sin modificar)
  minki_opcodes.json  tabla de control copiada del paquete 2.0.2
  programas/    seis programas de ejemplo propios (suma, pila, banderas, timer, nave, sprites)
  tests/        opcodes + máquina + GPU (131 pruebas)
  README.md     arranque rápido y rarezas
  DISENO.md     este documento
```

### Reglas de fidelidad

1. Reproducir el hardware **tal como está**, incluidas las rarezas de §5; nada de
   "correcciones inteligentes". Cualquier desviación se documenta y se activa con una bandera.
2. Implementar la ALU y las banderas campo por campo, no con atajos de alto nivel.
3. Los sprites se evalúan con las mismas constantes (`Ax1`, `Ay1`, `ancho`, `alto`, `hDiff`) y
   la misma fórmula de índice, leídas de los `.coe` convertidos a matrices.
4. Los botones se inyectan por guion (por ejemplo "botón 3 presionado entre la instrucción
   10 000 y 40 000"); el debounce se ignora y se documenta.
5. Las escrituras a RAM actualizan simultáneamente la RAM y los registros `x1`/`y1`, como el
   flanco real.

### Interfaz mínima deseada

```
python3 emu/cli.py asm  programa.suasm              # ensambla y lista palabras
python3 emu/cli.py run  programa.suasm --frames 3   # corre 3 frames, guarda PNG
python3 emu/cli.py gif  programa.suasm --frames 60  # animación
python3 emu/cli.py trace programa.suasm --max 200   # traza PC, instrucción, A..D, SP
```

---

## 9. Validación planeada

| Qué | Cómo | Estado |
|---|---|---|
| Ensamblador | reensamblar los 389 mnemónicos y comparar bit a bit con `minki_opcodes.json` | **hecho** (389/389 formas, 394 palabras, `tests/test_suasm.py`) |
| CPU | trazas a mano de `MOV`, `CMP` + salto, `PUSH`/`POP`/`CALL`/`RET` | **hecho** (`tests/test_cpu.py`: 85 pruebas en total) |
| Timer e I/O | tick de ms a 100 000 ciclos, lectura de 1/3/4/5/6, escritura de 0 y 2 | **hecho** |
| Entradas guionadas | `--input CICLO:switches|buttons:VALOR` | **hecho** |
| Gráficos | comparar un rectángulo dibujado con la fórmula de índice del VHDL | hecho en F3 (`tests/test_gpu.py`) |
| Caso real | programas reales de estudiantes del formativo | pendiente (no se incluyen en este repositorio) |
| Contra la placa | **imposible en esta máquina**; no afirmar equivalencia total | bloqueado |

---

## 10. Riesgos y pendientes

- **Sintaxis de MinkiAssembler**: se conocen `DATA:`/`CODE:`, comentarios `//` y `;`, literales
  decimal/`0x`/`0b`/sufijos `d`,`h`,`b`, arreglos de varios valores y símbolos. Faltan por
  verificar bordes: aritmética en operandos, etiquetas locales, mayúsculas/espacios, límites de
  literal. El `.exe` es de Windows y no se puede ejecutar aquí.
- **A7 evaluada no publicada**: todo se basa en el formativo. Si el enunciado real cambia (por
  ejemplo, exige 10 aliens con formación y descenso), el emulador sigue sirviendo pero la
  preparación debe reajustarse.
- **BRAM fuera de rango**: se asume que las posiciones no inicializadas de los `.coe` valen 0
  (negro). La cuenta de dirección se trunca a 17 bits como el VHDL; si la placa mostrara basura
  en esas filas, el emulador no lo reproduce.
- **Sin referencia de oro**: no hay traza oficial ni placa. El emulador ayuda a razonar y a
  detectar errores de direcciones/geometría, no certifica que la placa se comporte igual.
- El detalle de `Timer` y de `Clock_Divider` podría estar "mal" respecto de la intención del
  curso; no se corrige, se documenta.

---

## 11. Estado de implementación (2026-11-15)

Implementado y probado en esta máquina: **F1 completo (ensamblador + CPU), F2
(timer, E/S y entradas guionadas) y F3 (raster a PNG/GIF)**. Falta F4 (avisos de
solapamiento de sprites, parcialmente cubiertos por el aviso de escritura en
direcciones de E/S).

```bash
python3 -m unittest discover -s tests -v   # 131 pruebas
python3 cli.py selftest
```

### Hallazgos nuevos de la implementación (no estaban en §1–§10)

1. **No existe `MOV (dir), Lit`** en la tabla. Las formas con literal son
   `MOV (A|B|C|D), Lit` (dirección en un registro) y `MOV A|B|C|D, Lit`. Para
   escribir un literal en una dirección directa hay que pasar por un registro:
   `MOV A, 5` + `MOV (dir), A`. Lo mismo vale para `MOV (dir), (otra_dir)`: no
   hay movimiento memoria-memoria (esto confirma el error del código del
   formativo).
2. **`ADD (dir)`, `SUB (dir)`, `AND (dir)`, `OR (dir)`, `XOR (dir)`,
   `NOT (dir), r`, `SHL/SHR (dir), r`** escriben en `MEM[dir]` y leen los
   registros; `INC (dir)`/`DEC (dir)` también escriben (leen la memoria como
   segundo operando). `CMP (dir)` no existe: el primer operando siempre es un
   registro.
3. **Las direcciones 1, 3, 4, 5 y 6 están tapadas al leer** (E/S). El prólogo de
   DATA escribe en ellas sin problema, pero ese valor nunca se puede leer de
   vuelta. Regla práctica: datos propios desde la dirección 7. El emulador
   avisa cuando el *programa* (no el prólogo) escribe ahí.
4. **`010` es diez**, no ocho: sin prefijo todo se lee decimal.
5. **Registros sensibles a mayúsculas**: `b` minúscula es símbolo, no registro;
   así una variable llamada `b` no es ambigua. Los mnemónicos sí son
   insensibles a mayúsculas.
6. `DEC A`–`DEC D` usan el **literal implícito 1** (`SelTwo = 0100`); es la
   única instrucción sin operando que necesita literal.
7. Rendimiento medido: ~870 000 instrucciones/s en esta máquina, es decir
   ~0,5 s por frame de 416 800 ciclos. Por eso F3 no puede renderizar por
   píxel-ciclo: hay que muestrear la RAM cada N instrucciones y componer la
   imagen aparte.

### F3: cómo quedó el raster (cerrado)

`gpu.py` lee las constantes de los componentes entregados y compone el cuadro
con `numpy` vectorizado (una operación por sprite, no por píxel):

| Sprite | Tamaño | `Ax1`/`Ay1` | Ventana |
|---|---|---|---|
| fondo | 300x300 | 000/000 | sin prueba de caja |
| nave | 69x90 | 00A/00B | `x1-2 .. x1+66`, `y1 .. y1+89` |
| enemigo | 30x30 | 00C/00D | `x1-2 .. x1+27`, `y1 .. y1+29` |
| bala | 10x10 | 00E/00F | `x1-2 .. x1+7`, `y1 .. y1+9` |

Los 12 `.coe` se extrajeron del ZIP a `coe/` sin modificarlos; los tamaños
leídos (90 000 / 900 / 100 / 6 210) coinciden con `ancho*alto`.

Tres rarezas que aparecieron al implementar (todas del VHDL, ninguna corregida):

1. **`x1 = 640` no es invisible.** La ventana empieza en `x1-2 = 638`, así que
   cada sprite deja una franja de 2 columnas en el borde derecho mientras el
   programa no escriba su posición. Verificado en el render: la nave pinta
   las columnas 638–639 con las primeras dos columnas de su imagen.
2. **El fondo desborda.** Sin prueba de caja, su dirección es
   `(x+2-x1) + (y-y1)*300`; a partir de `x = 298` se corre a la fila siguiente
   de la imagen, entre `y = 300` y `y = 434` la dirección sale del arreglo
   (negro), y desde `y = 435` el truncamiento a 17 bits la trae de vuelta y
   repite el tope del fondo. Comprobado en las pruebas: la fila 437 empieza en
   el índice 30.
3. **El fondo lee `Ax1 = Ay1 = 000`, la misma dirección que los LEDs**: escribir
   LEDs corre el fondo en diagonal (x1 e y1 quedan con el mismo valor).

Corrección posterior: `render()` recorría `reversed(sprites)`, es decir pintaba
el fondo al final y tapaba a los otros sprites donde no fuera negro. Ahora
recorre `sprites` de menor a mayor prioridad; regresión cubierta por
`tests/test_prioridad_render.py` (117 pruebas OK al 2026-11-15).

Y un hallazgo sobre las imágenes, que no es del emulador: las tres naves tienen
un fondo celeste dominante `(4, 15, 14)` (3 093 de 6 210 píxeles en la nave
principal) que **no** es `000000`, es decir **no es transparente**. Como la
lógica de prioridad solo descarta el negro, los archivos entregados implican que
en la placa cada nave se vería dentro de un rectángulo celeste de su tamaño.

**Estado: no verificado en la placa.** La lectura de solo lectura del proyecto
entregado no encuentra nada que haga transparente ese celeste, así que el emulador
lo dibuja tal cual. Un estudiante que corrió el formativo no recuerda con certeza si
había un fondo celeste o azul alrededor de las naves, por lo que **no hay evidencia
firme a favor ni en contra**; es algo a confirmar en el laboratorio. Lo que se revisó:

- Solo se descarta el negro: `mainShipSM.vhd:90-91` (idéntico en
  `enemyShipSM.vhd:90-91` y `ammoSM.vhd:90-91`) pone `inside_area = '0'` cuando
  `inter_pixel = "000000000000"` y `out_in_a_block` en cualquier otro caso.
- La prioridad no mira color: `GraphicsProcessor.vhd:146-158` elige capa solo por
  `mainShipSM_on` / `enemyShipSM_on` / `ammoSM_on`, y `Xelor.vhd` solo maneja
  sincronía y `valid_area` (líneas 69 y 73).
- Los IP usan exactamente los `.coe` extraídos: cada `.xci` apunta
  `PARAM_VALUE.Coe_File` a `../../../../../Archivos Base/resources/<sprite>/<sprite>_<CANAL>.coe`
  (`C_ADDRA_WIDTH` 13 para `nave_principal`, 10 para `nave_azul`), y cada `.mif`
  sintetizado es numéricamente idéntico al `.coe` correspondiente de `coe/`
  (0 diferencias en los 6 canales de color).

Una hipótesis anterior (que la nave "nunca se posicionó", con `x1` en 640 y solo las
columnas 638–639 visibles) quedó **descartada**: quien probó el formativo recuerda haber
visto tanto la nave como el alien. No corregir a ciegas: confirmar en el laboratorio si el
rectángulo celeste se ve y, si no se ve, qué parte de la cadena de vídeo lo explica.

Los tres sprites se verificaron ejecutando `programas/06_sprites.suasm`, que
deja `nave_x/nave_y` en 10/11 (con relleno en 8/9 para correr las direcciones),
el enemigo en 12/13 y la bala en 14/15, y mueve todo una vez por tick de
`timer_milisegundos`, no una vez por instrucción: sin ese freno el sprite cruza
la pantalla en microsegundos y en el monitor solo se ve un salto.

### Enemigos extra: extensión del emulador (suposición)

`render()` y `describe()` aceptan `extra_enemies=N`, y `frame` el flag
`--extra-enemies N`. Cada enemigo `k` (0..N-1) es un `SpriteDef` de 30x30 con
`nave_azul`, `Ax1 = 16+2k` y `Ay1 = 17+2k`, `hDiff = 2` y transparencia
`000000`; se inserta justo después de `enemyShip` en el orden de pintado, o sea
queda **por debajo de la nave y por encima de la bala**, igual que el enemigo
base. Se reutiliza la imagen de su `rom` (`_image_for`), no se duplica en
memoria. `N = 0` devuelve `SPRITES` sin tocar (comportamiento idéntico;
`tests/test_extra_enemies.py`, 14 pruebas nuevas).

**Suposición explícita, no hecho del proyecto:** la base entregada trae un solo
`enemyShipSM` en 12/13 y la base evaluada de A7 aún no está publicada; si trae
ya las instancias (o usa otras direcciones), hay que cambiar `EXTRA_ENEMY_AX` o
pasar `sprites=` en vez de `extra_enemies=`.

## 12. Uso pensado para estudiantes: `probar.py` y `jugar.py`

La primera versión solo tenía `cli.py`, y su uso no se entendía: `frame` guardaba un
PNG en silencio y quien lo probaba esperaba una ventana de juego. Se agregaron dos
atajos encima de `cli.py`, sin cambiar la semántica de la máquina:

- **`probar.py ARCHIVO`**: ensambla, ejecuta 1 frame (o lo que se pida), imprime cada
  variable de `DATA` por nombre (omite 0–6, que son E/S), muestra los avisos sin el
  ruido de la inicialización de `DATA` (se ejecuta el prólogo y luego se borran los
  avisos de escritura en E/S), guarda la imagen y la abre con el visor del sistema
  (`xdg-open`, `open` u `os.startfile`).
- **`jugar.py ARCHIVO`**: ventana PyQt6 en vivo. Cada ~30 ms ejecuta instrucciones en
  lotes de 2 000 y redibuja; flechas/espacio fijan `buttons`, `S` y `0`–`9` alternan
  `switches`, `+`/`-` cambian la velocidad, `P`/`R`/`Esc`. Se ignoran las repeticiones
  automáticas del teclado y se sueltan los botones al perder el foco. Se eligió PyQt6
  porque Tkinter no funcionaba (falta `libtk8.6`) y pygame no estaba instalado.

**Velocidad (decisión con costo de fidelidad).** La máquina en Python ejecuta del orden
de 1 M instrucciones/s (~50 veces menos que la placa a 50 MHz) y el render de un cuadro
cuesta ~20 ms. Para que el juego no vaya en cámara lenta, `jugar.py` usa
`MaquinaAcelerada`, que cambia solo el prescaler del timer: con `--acelerar K` cada
microsegundo dura `round(100 / K)` ciclos en vez de 100 (por defecto K = 50: un tick
de `timer_milisegundos` cada 2 000 instrucciones). La CPU, la E/S y el render no
cambian. El comportamiento coincide con la placa mientras el programa ejecute menos
instrucciones entre ticks que las que caben en uno (~2 000 con K = 50); si no, el
programa "ve" pasar el tiempo más rápido que en la placa. `--acelerar 1` es el timer
exacto. Medido en la máquina de desarrollo: ~0,55 M instr/s con render, ≈55 % de la
velocidad de la placa con K = 50.

