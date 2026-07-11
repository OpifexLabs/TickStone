#include "tickstone_ble_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint64_t get_u64(const uint8_t *p) { uint64_t v=0; for(int i=0;i<8;i++) v|=(uint64_t)p[i]<<(8*i); return v; }
static uint16_t get_u16(const uint8_t *p) { return (uint16_t)p[0] | (uint16_t)p[1] << 8; }
static uint32_t get_u32(const uint8_t *p) { uint32_t v=0; for(int i=0;i<4;i++) v|=(uint32_t)p[i]<<(8*i); return v; }

int main(void)
{
    uint8_t packet[TICKSTONE_BLE_PACKET_SIZE];
    assert(tickstone_ble_encode_log(NULL, packet) && packet[0] == 1 && packet[1] == 0);
    habit_log_t log = {.id=42,.habit_id=3,.type=HABIT_TYPE_TIME,.timestamp_start=1700000000,
        .timestamp_end=1700000060,.duration_seconds=60,.deleted=true};
    assert(tickstone_ble_encode_log(&log, packet));
    assert(packet[1] == 3 && packet[2] == HABIT_TYPE_TIME && packet[3] == 3);
    assert(get_u64(&packet[4]) == 42 && get_u64(&packet[12]) == 1700000000);

    const habit_config_t habits[] = {
        {.id=0,.label="STR",.name="STRACKA",.type=HABIT_TYPE_COUNT,.default_minutes=1},
        {.id=7,.label="M7X",.name="FEMTON TECKEN1",.type=HABIT_TYPE_TIME,.default_minutes=99},
    };
    uint8_t config[TICKSTONE_BLE_CONFIG_PACKET_SIZE];
    assert(tickstone_ble_encode_config_page(habits, 2, 0, config));
    assert(config[0] == TICKSTONE_BLE_CONFIG_VERSION && config[1] == 0);
    assert(config[2] == 10 && config[3] == 2 && get_u32(&config[4]) != 0);
    const uint32_t hash = get_u32(&config[4]);
    assert(hash == 0x984a363au);

    assert(tickstone_ble_encode_config_page(habits, 2, 1, config));
    assert(config[1] == 1 && config[2] == 0 && config[3] == 1);
    assert(config[4] == HABIT_TYPE_COUNT && get_u16(&config[8]) == 1);
    assert(config[5] == 3 && config[6] == 7);
    assert(!memcmp(&config[10], "STR", 3) && !memcmp(&config[13], "STRACKA", 7));

    assert(tickstone_ble_encode_config_page(habits, 2, 8, config));
    assert(config[2] == 7 && config[3] == 1 && config[4] == HABIT_TYPE_TIME);
    assert(config[5] == 3 && config[6] == 14 && get_u16(&config[8]) == 99);

    assert(tickstone_ble_encode_config_page(habits, 2, 2, config));
    assert(config[2] == 1 && config[3] == 0 && config[5] == 0 && config[6] == 0);
    assert(get_u16(&config[8]) == 1);

    habit_config_t changed[2] = {habits[0], habits[1]};
    changed[1].default_minutes = 98;
    assert(tickstone_ble_config_hash(habits, 2) == hash);
    assert(tickstone_ble_config_hash(changed, 2) != hash);
    assert(!tickstone_ble_encode_config_page(habits, 2, 11, config));
    habit_config_t duplicate[2] = {habits[0], habits[0]};
    assert(!tickstone_ble_encode_config_page(duplicate, 2, 0, config));
    puts("tickstone_ble_protocol_test: OK");
    return 0;
}
