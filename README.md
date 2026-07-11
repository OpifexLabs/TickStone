# TickStone

TickStone ar en batterimedveten habit tracker for ESP32-C3 med 128x128 SSD1306 OLED och tre knappar. Upp till tio habits kan vara antingen tillfallen eller tid, med timer eller tidtagare. Installningar gors via USB och loggar synkas till macOS eller Raspberry Pi via Bluetooth LE.

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

- Hem har tva lagen: action och habits.
- Kort vanster/hoger bladdrar inom aktuell vy. Mitten valjer eller startar.
- En habit av typen Tid visar alltid val mellan timer och tidtagare vid start. Standardminuter anvands endast om timer valjs.
- Lang vanster/hoger byter hemlage. I habits oppnar mitten senaste loggen och kalenderstatistik for vald habit.
- Displayen dimmas efter 5 sekunder. Utan aktiv timer slacks den efter ytterligare 10 sekunder; en aktiv timer far ligga dimmad i upp till en minut.
- Forsta knapptrycket fran dimmat/slackt lage vacker bara displayen.

## USB-installningar

Anslut TickStone med USB och starta det lokala installningsgranssnittet:

```sh
tools/tickstone_settings.py
```

Webblasaren oppnar `http://127.0.0.1:8787`. Dar visas alla habits och du kan lagga till, andra eller ta bort dem innan hela konfigurationen sparas och verifieras via USB. Servern lyssnar endast pa den lokala datorn. Habit-platsernas ID ar stabila sa att befintlig logghistorik inte byter betydelse.

Terminalverktyget finns kvar som reserv pa macOS och Linux:

```sh
tools/tickstone_usb.py show
tools/tickstone_usb.py configure
tools/tickstone_usb.py sync
```

Verktyget hittar normalt porten automatiskt, laser/skriver upp till tio habits och satter enhetens klocka. `sync` oppnar BLE-fonstret manuellt om en tidigare automatisk synk missades. Varje habit har en kod pa hogst 3 tecken och ett namn pa hogst 15 tecken. Protokollet ar radbaserat och versionsmarkt med `TS1`; andra serielloggar ignoreras.

## Bluetooth-synk

Installera vardberoendet en gang pa Mac eller Raspberry Pi 5:

```sh
python3 -m pip install -r tools/requirements-ble.txt
```

Lat verktyget vanta pa nya loggar pa den dator som ska ta emot dem:

```sh
tools/tickstone_ble_sync.py --watch
```

Utan `--watch` gor kommandot ett enda synkforsok. Nar en logg skapas oppnar TickStone ett BLE-fonster i hogst 60 sekunder. Radion stangs av tre sekunder efter tom synkko eller nar fonstret tar slut. Verktyget satter klockan, hamtar varje osynkad logg och sparar den idempotent i `~/tickstone-logs.jsonl` innan stabilt logg-ID kvitteras. Ett avbrott fore kvittens ger saker omleverans. Raspberry Pi-anvandaren maste ha rattighet till Bluetooth via BlueZ; USB-verktyget kan krava medlemskap i gruppen `dialout`.

Klockan anvander tidszonen Europe/Stockholm. En TickStone-dag byter vid 05:00 lokal tid. Veckor ar mandag-sondag och manader foljer kalendern, inklusive sommartid.

## Strukturerad historik pa Raspberry Pi

Pi-installationen bevarar tva lager under `~/.local/share/tickstone/`:

- `logs.jsonl` ar den append-only ra-logg som tas emot fran enheten. Den ar aterstallningskallan och skrivs aldrig om av import eller backup.
- `tickstone.sqlite3` ar en SQLite-databas for framtida statistik. Den har validerade events, index per habit/dag/tid, TickStone-dag beraknad vid 05:00 i `Europe/Stockholm`, aktuella habit-platser och versionsbevarade konfigurationssnapshots.

Starta eller ateruppbygg databasen fran ra-loggen:

```sh
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone init
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone import-jsonl
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone integrity
```

BLE-lyssnaren skriver bada lagren innan en post kvitteras till TickStone:

```sh
tools/tickstone_ble_sync.py --watch \
  --output ~/.local/share/tickstone/logs.jsonl \
  --database ~/.local/share/tickstone/tickstone.sqlite3
```

Ett stabilt event-ID ar databasens primarnyckel. Om processen avbryts mellan ra-logg och databas reparerar en omleverans den saknade databasraden utan att duplicera JSONL. Samma ID med ett annat innehall avvisas i stallet for att skriva om historik. Raderade event bevaras med `deleted=1`; de tas inte bort fysiskt.

Habitnamn lagras som snapshots eftersom en stabil plats kan byta namn utan att aldre historik far byta betydelse. Exportera en konfiguration som JSON med formen `{"habits":[{"id":0,"code":"MED","name":"MEDITATION","mode":"time","minutes":10}]}` och registrera den med:

```sh
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone record-habits habits.json
```

Repo-filerna `deploy/tickstone-sync.service`, `deploy/tickstone-backup.service` och `deploy/tickstone-backup.timer` ar de installerade systemd-kontrakten pa Pi:n. Timern gor en daglig SQLite online-backup och en separat kopia av JSONL under `~/.local/share/tickstone/backups/`. Filnamn ar UTC-tidsstampade och en befintlig backup skrivs aldrig over. Manuell backup:

```sh
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone backup
```

Databasen kan alltid byggas om fran JSONL. Backuper och ra-logg ska inte laggas i Git.

## Data och energi

- Versionerat little-endian-format med CRC, explicit migrering fran tidigare NVS-format och ingen automatisk radering vid NVS-fel.
- Ringlager med 512 poster och kompakta dagssammanfattningar for 70 kalenderdagar. Osynkade poster skrivs aldrig over; UI visar `LOG FULL / SYNC NEEDED` om kon gar full.
- CPU skalar mellan 40 och 160 MHz och FreeRTOS anvander tickless idle. WiFi startas inte. BLE-radion ar helt av i vila och aktiveras tillfalligt av en ny osynkad logg. Automatisk light sleep ar avstangd pa USB-prototypen; djupsomn aktiveras forst med definierade wake-pinnar.
- NVS har en egen 128 KB-partition och appen anvander resterande flash.

## Bygg och flash

```sh
source "$HOME/esp/esp-idf/export.sh"
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash monitor
```

Projektet ar konfigurerat for `esp32c3`. Att byta target skriver om `sdkconfig` och ska inte goras for den har hardvaran.

## Tester

Vardtesterna tacker habit-floden, kalendergranser och DST, codec/CRC, legacy-migrering, rollover/power-loss, full osynkad loggko, USB-validering, BLE-paket, framebuffer dirty pages samt displayens idle-regler. OLED-flodena renderas fran samma font-, ikon- och tillstandsdata som firmware.

```sh
tools/run_tests.sh
idf.py build
```
