# habit_tracker_esp32s3

Native ESP-IDF MVP for en liten ESP32-S3-baserad habit tracker på breadboard.

Första prototypen har 3 habits, 3 vita LED-lysdioder, 3 taktila knappar och en MAX7219 4x 8x8 dot matrix-display som visar en timer. Batteri, deep sleep, WiFi, Bluetooth, NVS och CAD är medvetet utanför denna iteration.

## Funktioner i MVP

- Bootar och loggar att habit tracker startar.
- Initierar MAX7219 och visar `20:00`.
- Tre interna habits: habit 1, 2 och 3.
- Vald habit visas med motsvarande LED.
- Vänster knapp väljer föregående habit.
- Höger knapp väljer nästa habit.
- Play-knapp startar/pausar timern.
- Långtryck vänster minskar vald habits timer med 1 minut.
- Långtryck höger ökar vald habits timer med 1 minut.
- Långtryck play resetar vald habits timer till dess duration.
- Timer räknar ner från `20:00` till `00:00`.
- När timern är klar blinkar vald habits LED.
- Knapparna använder debounce på ca 40 ms och långtryck på ca 700 ms.

Alla standardpinnar finns i `main/app_config.h` så att de är enkla att ändra.

## Kopplingar

Knapparna är active-low med intern pullup:

```text
GPIO -> knapp -> GND
```

| Funktion | ESP32-S3 GPIO | Notering |
| --- | ---: | --- |
| MAX7219 DIN/MOSI | GPIO4 | Data till display |
| MAX7219 CLK | GPIO5 | Klocka till display |
| MAX7219 CS/LOAD | GPIO6 | Chip select/load |
| LED habit 1 | GPIO15 | LED med lämpligt seriemotstånd |
| LED habit 2 | GPIO16 | LED med lämpligt seriemotstånd |
| LED habit 3 | GPIO17 | LED med lämpligt seriemotstånd |
| Button left | GPIO7 | Active-low, intern pullup |
| Button play | GPIO8 | Active-low, intern pullup |
| Button right | GPIO9 | Active-low, intern pullup |

MAX7219-moduler drivs ofta med 5V medan ESP32-S3 använder 3.3V logic. Om displayen beter sig konstigt kan en level shifter behövas mellan ESP32-S3 och MAX7219.

## Build och flash

Kör från projektets rot:

```sh
idf.py set-target esp32s3
idf.py build
idf.py -p PORT flash monitor
```

På macOS är `PORT` ofta något i stil med `/dev/cu.*`, till exempel `/dev/cu.usbmodemXXXX`.

## Verifiering i denna miljö

Build kunde inte köras här eftersom ESP-IDF inte finns i PATH.

Kommando som kördes:

```sh
idf.py build
```

Resultat:

```text
zsh:1: command not found: idf.py
```

## Projektstruktur

```text
CMakeLists.txt
main/CMakeLists.txt
main/app_main.c
main/app_config.h
components/max7219_matrix/
components/buttons/
components/habit_leds/
README.md
sdkconfig.defaults
```

## Komponenter

- `components/max7219_matrix`: liten egen MAX7219 matrix-driver med `clear()`, `set_intensity()` och `draw_time_mm_ss()`.
- `components/buttons`: återanvändbar knapphantering med events för `SHORT_PRESS` och `LONG_PRESS`.
- `components/habit_leds`: enkel GPIO-abstraktion för habit-LEDs, förberedd så att PWM/LEDC kan läggas till senare.
