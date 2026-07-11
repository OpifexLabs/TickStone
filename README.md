# TickStone

TickStone ar en batterimedveten habit tracker for ESP32-C3 med 128x128 SSD1306 OLED och tre knappar. Upp till tio habits kan vara antingen tillfallen eller tid, med timer eller tidtagare. Loggar sparas lokalt och synkas nar WiFi finns.

## Koppling

Knapparna ar active-low och anvander intern pull-up: `GPIO -> knapp -> GND`.

| Funktion | GPIO |
| --- | ---: |
| OLED SDA | 7 |
| OLED SCL | 6 |
| Vanster knapp | 20 |
| Mittenknapp | 8 |
| Hoger knapp | 9 |

OLED drivs med 3V3 och GND. Alla pinnummer finns i `main/app_config.h`.

## Anvandning

- Hem har tre lagen: habits, action och loggar.
- Kort vanster/hoger bladdrar inom aktuell vy. Mitten valjer eller startar.
- Lang vanster/hoger byter hemlage. Lang mitten visar statistik eller sparar en session.
- Displayen dimmas efter 5 sekunder. Utan aktiv timer slacks den efter ytterligare 10 sekunder; en aktiv timer far ligga dimmad i upp till en minut.
- Forsta knapptrycket fran dimmat/slackt lage vacker bara displayen.

## WiFi och webbvy

Utan sparat natverk startar enheten installationsnatet `TickStone-XXXX` med losenordet `tickstone`. Anslut och oppna `http://192.168.4.1`. Dar kan WiFi, synk-URL och upp till tio habits konfigureras. Pa hemnatet ar samma sida tillganglig pa enhetens DHCP-adress, som skrivs i serielloggen.

Klockan synkas med SNTP och anvander tidszonen Europe/Stockholm. En TickStone-dag byter vid 05:00 lokal tid. Veckor ar mandag-sondag och manader foljer kalendern, inklusive sommartid.

## Synk-API

Varje osynkad logg skickas med `POST` som JSON till konfigurerad URL. Headern `Idempotency-Key` innehaller loggens stabila ID. Alla 2xx-svar markerar posten synkad. Fel ger exponentiell backoff fran 5 sekunder upp till 15 minuter; lokal loggning fortsatter offline. HTTPS verifieras mot ESP-IDF:s CA-bundle.

Servern ska behandla samma idempotensnyckel som samma operation. JSON innehaller `id`, `habit_id`, `type`, `started_at`, `ended_at`, `duration_seconds`, `count` och `deleted`.

## Data och energi

- Versionerat little-endian-format med CRC, explicit migrering fran tidigare NVS-format och ingen automatisk radering vid NVS-fel.
- Ringlager med 512 poster och kompakta dagssammanfattningar for 70 kalenderdagar. Osynkade poster skrivs aldrig over; UI visar `LOG FULL / SYNC NEEDED` om kon gar full.
- CPU skalar mellan 40 och 160 MHz, FreeRTOS anvander tickless idle och WiFi modem-sleep. Automatisk light sleep ar avstangd pa USB-prototypen eftersom den kopplar ned C3:ans USB-Serial/JTAG; djupsomn aktiveras forst med batteri och definierade wake-pinnar.
- NVS har en egen 128 KB-partition och appen anvander resterande flash.

## Bygg och flash

```sh
source "$HOME/esp/esp-idf/export.sh"
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash monitor
```

Projektet ar konfigurerat for `esp32c3`. Att byta target skriver om `sdkconfig` och ska inte goras for den har hardvaran.

## Tester

Vardtesterna tacker habit-floden, kalendergranser och DST, codec/CRC, legacy-migrering, rollover/power-loss, full osynkad loggko, webbvalidering, synkbackoff, framebuffer dirty pages samt displayens idle-regler. OLED-flodena renderas fran samma font-, ikon- och tillstandsdata som firmware.

```sh
tools/run_tests.sh
idf.py build
```
