#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
mkdir -p build

run_test() {
    name=$1
    shift
    cc -std=c11 -Wall -Wextra -Werror "$@" -o "build/$name"
    "build/$name"
}

run_test clock_service_test -Icomponents/clock_service/include tests/clock_service_test.c components/clock_service/clock_service.c
run_test clock_sync_policy_test -Icomponents/clock_sync_policy/include tests/clock_sync_policy_test.c components/clock_sync_policy/clock_sync_policy.c
run_test habit_app_test -Icomponents/habit_app/include -Icomponents/clock_service/include tests/habit_app_test.c components/habit_app/habit_app.c components/clock_service/clock_service.c
run_test habit_codec_test -Icomponents/habit_app/include -Icomponents/habit_codec/include tests/habit_codec_test.c components/habit_codec/habit_codec.c
run_test habit_legacy_test -Icomponents/habit_app/include -Icomponents/habit_legacy/include tests/habit_legacy_test.c components/habit_legacy/habit_legacy.c
run_test habit_ring_test -Icomponents/habit_app/include -Icomponents/habit_ring/include tests/habit_ring_test.c components/habit_ring/habit_ring.c
run_test habit_web_config_test -Icomponents/habit_app/include -Icomponents/habit_web_config/include tests/habit_web_config_test.c components/habit_web_config/habit_web_config.c
run_test display_idle_test -Icomponents/display_idle/include tests/display_idle_test.c components/display_idle/display_idle.c
run_test finish_alert_test -Icomponents/finish_alert/include tests/finish_alert_test.c components/finish_alert/finish_alert.c
run_test oled_frame_test -Icomponents/oled_frame/include tests/oled_frame_test.c components/oled_frame/oled_frame.c
run_test sync_policy_test -Icomponents/sync_policy/include tests/sync_policy_test.c components/sync_policy/sync_policy.c
run_test sync_payload_test -Icomponents/habit_app/include -Icomponents/sync_payload/include tests/sync_payload_test.c components/sync_payload/sync_payload.c
run_test tickstone_ble_protocol_test -Icomponents/habit_app/include -Icomponents/tickstone_ble/include tests/tickstone_ble_protocol_test.c components/tickstone_ble/tickstone_ble_protocol.c

python3 tests/tickstone_settings_test.py
python3 tests/tickstone_ble_sync_test.py
python3 tests/tickstone_store_test.py
python3 tests/tickstone_dashboard_test.py
python3 tools/render_oled_flows.py >/dev/null
echo "all host tests and OLED renders: OK"
