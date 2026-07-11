#include "tickstone_ble_protocol.h"
#include <assert.h>
#include <stdio.h>

static uint64_t get_u64(const uint8_t *p) { uint64_t v=0; for(int i=0;i<8;i++) v|=(uint64_t)p[i]<<(8*i); return v; }

int main(void)
{
    uint8_t packet[TICKSTONE_BLE_PACKET_SIZE];
    assert(tickstone_ble_encode_log(NULL, packet) && packet[0] == 1 && packet[1] == 0);
    habit_log_t log = {.id=42,.habit_id=3,.type=HABIT_TYPE_TIME,.timestamp_start=1700000000,
        .timestamp_end=1700000060,.duration_seconds=60,.deleted=true};
    assert(tickstone_ble_encode_log(&log, packet));
    assert(packet[1] == 3 && packet[2] == HABIT_TYPE_TIME && packet[3] == 3);
    assert(get_u64(&packet[4]) == 42 && get_u64(&packet[12]) == 1700000000);
    puts("tickstone_ble_protocol_test: OK");
    return 0;
}
