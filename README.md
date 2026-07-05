# habit_tracker_esp32s3

Native ESP-IDF MVP for en liten ESP32-S3-baserad habit tracker på breadboard.

Första prototypen har 3 habits, 3 vita LED-lysdioder, 3 taktila knappar och en MAX7219 8x8 dot matrix-display som visar en timer. Batteri, deep sleep, WiFi, Bluetooth, NVS och CAD är medvetet utanför denna iteration.

## Funktioner i MVP

- Bootar och loggar att habit tracker startar.
- Initierar MAX7219 och visar `20` som två kompakta siffror på 8x8-matrisen.
- MAX7219-komponenten kan också visa två siffror i 7-segmentsstil på matrisdisplayen.
- Tre interna habits: habit 1, 2 och 3.
- Vald habit visas med motsvarande LED.
- Vänster knapp minskar vald habits timer med 1 minut.
- Höger knapp ökar vald habits timer med 1 minut.
- Play-knapp startar/pausar timern.
- Långtryck vänster väljer föregående habit.
- Långtryck höger väljer nästa habit.
- Långtryck play resetar vald habits timer till dess duration.
- Timer räknar ner från `20` minuter till `00`.
- När mer än 60 sekunder återstår visas minuter avrundat uppåt. Under sista minuten visas sekunder.
- Displayens mittpunkter blinkar när timern kör och lyser fast när den är pausad.
- När timern är klar blinkar vald habits LED.
- Knapparna använder debounce på ca 40 ms och långtryck på ca 700 ms.

Alla standardpinnar finns i `main/app_config.h` så att de är enkla att ändra.
Displayen är konfigurerad med `MAX7219_MATRIX_ROTATION_LEFT_90` i `main/app_main.c`.

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

ESP-IDF v5.5.3 installerades lokalt i `~/esp/esp-idf`.

Kommandon som kördes:

```sh
source "$HOME/esp/esp-idf/export.sh"
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/cu.usbmodem5AF71039601 flash
```

Resultat:

```text
Project build complete.
Done
Habit tracker started. Displaying 20:00
```

Senaste ändringen med tvåsiffrig 7-segments-timer är byggd med `idf.py build`, men inte flashad till kortet ännu.

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
- `max7219_matrix_draw_7seg_2_digit(value, leading_zero)` visar `0`-`99`. På en ensam 8x8-matris används ett kompakt 3x7-läge; på bredare kedjade matriser används större 7-segmentsliknande siffror.
- `components/buttons`: återanvändbar knapphantering med events för `SHORT_PRESS` och `LONG_PRESS`.
- `components/habit_leds`: enkel GPIO-abstraktion för habit-LEDs, förberedd så att PWM/LEDC kan läggas till senare.

Exempel:

```c
ESP_ERROR_CHECK(max7219_matrix_draw_7seg_2_digit(7, false)); // visar "7"
ESP_ERROR_CHECK(max7219_matrix_draw_7seg_2_digit(7, true));  // visar "07"
ESP_ERROR_CHECK(max7219_matrix_draw_7seg_2_digit(42, true)); // visar "42"
ESP_ERROR_CHECK(max7219_matrix_draw_7seg_2_digit_clock(20, true, true)); // visar "20" med klockpunkter
```
