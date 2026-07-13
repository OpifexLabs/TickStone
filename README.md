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

Firmware exponerar ocksa en read-only, paginerad config-characteristic
`7e570000-7a1b-4c2d-9e10-000000000004`. Varje anslutning laser en versionsmarkt
snapshot av alla tio slots innan loggarna synkas. Gammal firmware utan characteristic
fortsatter i legacy-lage. Delvis eller felaktigt last config sparas aldrig.

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

Habitnamn lagras automatiskt som snapshots eftersom en stabil plats kan byta namn utan att aldre historik far byta betydelse. `record-habits` finns endast som reserv for legacy-importer utan BLE-metadata; normal drift behover ingen manuell mapping. Reservformatet ar `{"habits":[{"id":0,"code":"MED","name":"MEDITATION","mode":"time","minutes":10}]}`:

```sh
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone record-habits habits.json
```

Repo-filerna `deploy/tickstone-sync.service`, `deploy/tickstone-backup.service` och `deploy/tickstone-backup.timer` ar de installerade systemd-kontrakten pa Pi:n. Timern gor en daglig SQLite online-backup och en separat kopia av JSONL under `~/.local/share/tickstone/backups/`. Filnamn ar UTC-tidsstampade och en befintlig backup skrivs aldrig over. Manuell backup:

```sh
python3 tools/tickstone_store.py --data-dir ~/.local/share/tickstone backup
```

Databasen kan alltid byggas om fran JSONL. Backuper och ra-logg ska inte laggas i Git.

## Lokal statistikdashboard

Dashboarden ar en read-only webbvy over `tickstone.sqlite3`. Den har inga skrivande API:er, inga externa typsnitt, script eller CDN-anrop och ar avsedd enbart for hem-LAN och Tailscale. Hela produktgranssnittet, inklusive datum, ARIA-texter, diagram och klientgenererade dagsdetaljer, visas pa engelska; anvandarskapade habitnamn visas oforandrade.

Habit-raderna ar klickbara. `/habit/0?period=week`, `month`, `year` och `all` visar
kalenderbaserad aktivitet, total, aktiva dagar, genomsnitt, streak och periodjamforelse.
BLE-metadata versionslagras med giltighetsintervall, och nya event pekar pa snapshoten
som lastes fore ACK. Aldre importerade event utan snapshot visas som tydligt markerad
fallback och far inte fabricerad historisk sakerhet.

Oversikten visar explicita kalenderjamforelser, till exempel `+5% jämfört med förra veckan`,
med separata utfall for oforandrat lage och ny aktivitet nar foregaende period ar noll.
Den interaktiva linjegrafen kan vaxla mellan vecka, manad och kalenderar. Varje habit kan
valjas eller doljas; valet bevaras i webblasarsessionen. Grafen jamfor konsekvent antal
aktivitetstillfallen, medan habitdetaljer fortsatter anvanda habitens riktiga enhet
(count eller duration). Data levereras read-only fran `/api/timeline?range=week|month|year`.

Huvudvyn ar en periodstyrd statistikarbetsyta med `period=week|month|year|all` och
bakatriktad `offset`. Den visar aktiva dagar, antal loggar, total tid,
kalenderjamforelse, faktisk tidsaktivitet per vald time-habit, klickbara habitresultat,
12-veckors heatmap och datagrundade insikter. Habitjamforelsen visar bade vecka och manad mot
exakt samma forflutna lokala tid i foregaende period (`V: +N%`, `M: -N%`) med separata
positiva/negativa toner. Momentumkortet rankar den starkaste positiva utvecklingen mot samma
veckodag och klockslag forra veckan, i stallet for att jamfora en ofullstandig vecka med en hel.
Personliga rekord beraknas for streak, vecka, dagstillfallen, tidssession och veckotid men visas
bara som en tillfallig insikt nar en tidigare baseline faktiskt slas. Historiska baselines ar
bundna till samma versionslagrade habitidentitet och typ; en ateranvand slot blandar aldrig count
med sekunder eller en gammal vana med en ny. Inaktiva habits driver inte aktuell intelligens.
Narmaste relevanta gap till att faktiskt sla (inte bara tangera) ett tidigare veckorekord kan
visas som milstolpe; nagon permanent rekordpanel finns inte.
Tidsgrafen kan visas som staplar eller linjer;
valda habits och diagramtyp sparas i `sessionStorage`. Count-events visas inte i grafen.
Dashboarden har inga mal, malringar eller malnormaliserade framsteg; varken renderingslagret
eller statistikmodellen beraknar maluppfyllelse. Habitdetaljen binder snapshot-losa legacy-events
konservativt till den aktuella identitetens `valid_from`, raknar helg/vardag fran TickStone-dygnet
05:00 och bygger trend enbart fran avslutade veckor. Diagramdata finns aven som en skarmlasarlista
och en `noscript`-fallback. Framtida kalenderdagar ar semantiskt inaktiverade. Framtida offset avvisas
och senare-pilen ar inaktiv i aktuell period.
Habitdetaljen har ett rikt, read-only analyslager med rattvisa vecka/manad-jamforelser,
milstolpe, fyra nyckeltal, faktiska dag/vecka/manad-diagram, typmedvetna rekord,
evidenstrosklade monster, klickbar 12-veckors habitkalender och daggrupperad logghistorik.
Loggar kan granskas men inte rattas eller raderas fran dashboarden; den kanoniska ravloggen
forblir append-only.
Vid iPad-landskap (1024x768) anvander oversikten en kompakt fyrkortsrad, minst 150 px tidsdiagram
och en 12x7-heatmap med minst 12 px rader, sa att oversikt, heatmap, insikter och synkstatus
ryms pa den forsta vyn utan vertikal scrollning. Arbetsytans maxbredd ar 1800 px, sa vanliga och
breda desktopskarmar anvander nastan hela den tillgangliga bredden. Pa hogre skarmar vaxer branding, KPI-kort,
tidsdiagram och heatmaprader responsivt till begransade maxhojder. Tidsdiagrammet anvander den
storre delen av primarraden, och samma kolumnfordelning anvands for 12-veckorsmatrisen sa att
vansterkorten ar exakt lika breda. Habit-tabellen ar kompakt utan typkolumn och visar streak som
ett tal. Manadens x-axeetiketter glesas ut efter tillganglig bredd. Habitdetaljer har staplar som
standard, synlig y-axel med `Tid` eller `Tillfallen` och ratt sekunder/minuter/timmar respektive
antal, samt ett lokalt stapel-/linjeval som sparas per habit under browsersessionen.

- LAN: `http://192.168.86.29:8750`
- Tailscale: `http://100.111.154.107:8750`
- Health: `/healthz`
- Service: `tickstone-dashboard.service`
- Loggar: `journalctl -u tickstone-dashboard.service`

Installera repo-kontraktet pa Pi:n och begransa LAN-trafiken med UFW:

```sh
sudo install -o root -g root -m 0644 deploy/tickstone-dashboard.service /etc/systemd/system/tickstone-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now tickstone-dashboard.service
sudo ufw allow from 192.168.86.0/24 to any port 8750 proto tcp comment 'TickStone dashboard from home LAN'
```

Tailscale ar tillatet genom vardens befintliga `tailscale0`-regel. Oppna inte porten for `Anywhere`, skapa ingen publik tunnel och lagg inte till publik DNS. Tjansten kor som den vanliga anvandaren, oppnar databasen med SQLite `mode=ro`, accepterar endast GET/HEAD och har systemd-hardening. Kontrollera efter uppdatering:

```sh
systemctl is-active tickstone-dashboard.service
curl -fsS http://127.0.0.1:8750/healthz
systemd-analyze security tickstone-dashboard.service --no-pager
```

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
