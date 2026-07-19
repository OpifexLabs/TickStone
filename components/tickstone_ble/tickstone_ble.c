#include "tickstone_ble.h"

#include <assert.h>
#include <string.h>

#include "esp_log.h"
#include "esp_check.h"
#include "clock_service.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "os/os_mbuf.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "tickstone_ble_protocol.h"

static const char *TAG = "tickstone_ble";
static SemaphoreHandle_t s_lock;
static uint8_t s_packet[TICKSTONE_BLE_PACKET_SIZE];
static habit_config_t s_habits[HABIT_APP_MAX_HABITS];
static size_t s_habit_count;
static uint8_t s_config_page;
static bool s_ack_pending;
static uint64_t s_ack_id;
static bool s_time_pending;
static int64_t s_utc_seconds;
static uint8_t s_addr_type;
static bool s_active;
static volatile bool s_stopping;
static int64_t s_deadline_ms;
static int64_t s_empty_since_ms = -1;
static bool s_had_pending_logs;
static bool s_data_read;

#define SYNC_WINDOW_MS 60000
#define EMPTY_GRACE_MS 3000

static const ble_uuid128_t s_service_uuid = BLE_UUID128_INIT(
    0x01,0x00,0x00,0x00,0x00,0x00,0x10,0x9e,0x2d,0x4c,0x1b,0x7a,0x00,0x00,0x57,0x7e);
static const ble_uuid128_t s_data_uuid = BLE_UUID128_INIT(
    0x02,0x00,0x00,0x00,0x00,0x00,0x10,0x9e,0x2d,0x4c,0x1b,0x7a,0x00,0x00,0x57,0x7e);
static const ble_uuid128_t s_control_uuid = BLE_UUID128_INIT(
    0x03,0x00,0x00,0x00,0x00,0x00,0x10,0x9e,0x2d,0x4c,0x1b,0x7a,0x00,0x00,0x57,0x7e);
static const ble_uuid128_t s_config_uuid = BLE_UUID128_INIT(
    0x04,0x00,0x00,0x00,0x00,0x00,0x10,0x9e,0x2d,0x4c,0x1b,0x7a,0x00,0x00,0x57,0x7e);

static uint64_t get_u64(const uint8_t *data)
{
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= (uint64_t)data[i] << (i * 8);
    return value;
}

static int access_data(uint16_t conn_handle, uint16_t attr_handle,
                       struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_READ_NOT_PERMITTED;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    int rc = os_mbuf_append(ctxt->om, s_packet, sizeof(s_packet));
    s_data_read = true;
    xSemaphoreGive(s_lock);
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int access_control(uint16_t conn_handle, uint16_t attr_handle,
                          struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
    uint8_t command[9]; uint16_t length = 0;
    if (ble_hs_mbuf_to_flat(ctxt->om, command, sizeof(command), &length) != 0) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (length == 2 && command[0] == 3 && command[1] < TICKSTONE_BLE_CONFIG_PAGE_COUNT) {
        s_config_page = command[1];
    } else if (length == 9 && command[0] == 1 &&
               get_u64(&command[1]) <= INT64_MAX &&
               clock_service_utc_is_valid((int64_t)get_u64(&command[1]))) {
        uint64_t value = get_u64(&command[1]);
        s_utc_seconds = (int64_t)value; s_time_pending = true;
    } else if (length == 9 && command[0] == 2 && get_u64(&command[1]) != 0) {
        uint64_t value = get_u64(&command[1]);
        s_ack_id = value; s_ack_pending = true;
    } else {
        xSemaphoreGive(s_lock); return BLE_ATT_ERR_UNLIKELY;
    }
    xSemaphoreGive(s_lock);
    return 0;
}

static int access_config(uint16_t conn_handle, uint16_t attr_handle,
                         struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_READ_NOT_PERMITTED;
    uint8_t packet[TICKSTONE_BLE_CONFIG_PACKET_SIZE];
    xSemaphoreTake(s_lock, portMAX_DELAY);
    bool encoded = tickstone_ble_encode_config_page(s_habits, s_habit_count, s_config_page, packet);
    int rc = encoded ? os_mbuf_append(ctxt->om, packet, sizeof(packet)) : -1;
    xSemaphoreGive(s_lock);
    return rc == 0 ? 0 : BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def s_services[] = {{
    .type = BLE_GATT_SVC_TYPE_PRIMARY,
    .uuid = &s_service_uuid.u,
    .characteristics = (struct ble_gatt_chr_def[]){{
        .uuid = &s_data_uuid.u, .access_cb = access_data, .flags = BLE_GATT_CHR_F_READ,
    }, {
        .uuid = &s_control_uuid.u, .access_cb = access_control,
        .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
    }, {
        .uuid = &s_config_uuid.u, .access_cb = access_config, .flags = BLE_GATT_CHR_F_READ,
    }, {0}},
}, {0}};

static void advertise(void);

static int gap_event(struct ble_gap_event *event, void *arg)
{
    if ((event->type == BLE_GAP_EVENT_CONNECT && event->connect.status != 0) ||
        event->type == BLE_GAP_EVENT_DISCONNECT || event->type == BLE_GAP_EVENT_ADV_COMPLETE) {
        if (!s_stopping) advertise();
    }
    return 0;
}

static void advertise(void)
{
    if (s_stopping) return;
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&s_service_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    int fields_rc = ble_gap_adv_set_fields(&fields);
    if (fields_rc != 0) {
        ESP_LOGE(TAG, "advertising fields failed: %d", fields_rc);
        return;
    }
    struct ble_hs_adv_fields response = {0};
    const char *name = ble_svc_gap_device_name();
    response.name = (uint8_t *)name;
    response.name_len = strlen(name);
    response.name_is_complete = 1;
    fields_rc = ble_gap_adv_rsp_set_fields(&response);
    if (fields_rc != 0) {
        ESP_LOGE(TAG, "scan response fields failed: %d", fields_rc);
        return;
    }
    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_UND; params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    params.itvl_min = 320; params.itvl_max = 480;
    int rc = ble_gap_adv_start(s_addr_type, NULL, BLE_HS_FOREVER, &params, gap_event, NULL);
    if (rc != 0) ESP_LOGE(TAG, "advertising failed: %d", rc);
}

static void on_sync(void)
{
    int rc = ble_hs_util_ensure_addr(0); assert(rc == 0);
    rc = ble_hs_id_infer_auto(0, &s_addr_type); assert(rc == 0);
    advertise();
}

static void host_task(void *argument)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

esp_err_t tickstone_ble_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;
    tickstone_ble_encode_log(NULL, s_packet);
    return ESP_OK;
}

static esp_err_t start_stack(void)
{
    ESP_RETURN_ON_ERROR(nimble_port_init(), TAG, "NimBLE init failed");
    ble_hs_cfg.sync_cb = on_sync;
    ble_svc_gap_init(); ble_svc_gatt_init();
    int rc = ble_svc_gap_device_name_set("TickStone");
    if (rc == 0) rc = ble_gatts_count_cfg(s_services);
    if (rc == 0) rc = ble_gatts_add_svcs(s_services);
    if (rc != 0) {
        nimble_port_deinit();
        return ESP_FAIL;
    }
    s_stopping = false;
    s_active = true;
    s_had_pending_logs = false;
    s_data_read = false;
    nimble_port_freertos_init(host_task);
    ESP_LOGI(TAG, "BLE sync window opened");
    return ESP_OK;
}

static esp_err_t stop_stack(void)
{
    if (!s_active) return ESP_OK;
    s_stopping = true;
    int rc = nimble_port_stop();
    if (rc != 0) {
        s_stopping = false;
        ESP_LOGE(TAG, "NimBLE stop failed: %d", rc);
        return ESP_FAIL;
    }
    esp_err_t err = nimble_port_deinit();
    if (err != ESP_OK) {
        s_stopping = false;
        return err;
    }
    s_active = false;
    s_stopping = false;
    s_empty_since_ms = -1;
    ESP_LOGI(TAG, "BLE radio off");
    return ESP_OK;
}

esp_err_t tickstone_ble_request_sync(int64_t now_ms)
{
    s_deadline_ms = now_ms + SYNC_WINDOW_MS;
    s_empty_since_ms = -1;
    return s_active ? ESP_OK : start_stack();
}

esp_err_t tickstone_ble_update(int64_t now_ms, bool has_pending_logs)
{
    if (!s_active) return ESP_OK;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool data_read = s_data_read;
    xSemaphoreGive(s_lock);
    if (has_pending_logs) {
        s_had_pending_logs = true;
        s_empty_since_ms = -1;
    } else if ((s_had_pending_logs || data_read) && s_empty_since_ms < 0) {
        s_empty_since_ms = now_ms;
    }
    if (now_ms >= s_deadline_ms ||
        (s_empty_since_ms >= 0 && now_ms - s_empty_since_ms >= EMPTY_GRACE_MS)) {
        return stop_stack();
    }
    return ESP_OK;
}

void tickstone_ble_publish_log(const habit_log_t *log)
{
    if (!s_lock) return;
    uint8_t packet[TICKSTONE_BLE_PACKET_SIZE];
    if (!tickstone_ble_encode_log(log, packet)) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    memcpy(s_packet, packet, sizeof(packet));
    xSemaphoreGive(s_lock);
}

void tickstone_ble_publish_habits(const habit_config_t *habits, size_t count)
{
    if (!s_lock || !habits || count > HABIT_APP_MAX_HABITS ||
        tickstone_ble_config_hash(habits, count) == 0) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    memcpy(s_habits, habits, count * sizeof(*habits));
    if (count < HABIT_APP_MAX_HABITS) {
        memset(&s_habits[count], 0, (HABIT_APP_MAX_HABITS - count) * sizeof(*habits));
    }
    s_habit_count = count;
    s_config_page = 0;
    xSemaphoreGive(s_lock);
}

bool tickstone_ble_take_ack(uint64_t *log_id)
{
    if (!s_lock || !log_id) return false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    bool pending = s_ack_pending;
    if (pending) { *log_id = s_ack_id; s_ack_pending = false; }
    xSemaphoreGive(s_lock); return pending;
}

bool tickstone_ble_take_time(int64_t *utc_seconds)
{
    if (!s_lock || !utc_seconds) return false;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    bool pending = s_time_pending;
    if (pending) { *utc_seconds = s_utc_seconds; s_time_pending = false; }
    xSemaphoreGive(s_lock); return pending;
}
