#include "tickstone_network.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_crt_bundle.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "habit_web_config.h"
#include "sync_payload.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "network";
static SemaphoreHandle_t s_lock;
static habit_config_t s_habits[HABIT_APP_MAX_HABITS];
static size_t s_count;
static bool s_pending;
static tickstone_network_status_t s_status;
static httpd_handle_t s_server;
static esp_netif_t *s_ap;
static bool s_sntp_started;
static char s_sync_url[192];
static char s_ap_ssid[33];
static char s_network_options[3000];

static const char PAGE[] =
"<!doctype html><html lang='sv'><meta name='viewport' content='width=device-width,initial-scale=1'>"
"<title>TickStone</title><style>body{font:16px system-ui;margin:auto;max-width:640px;padding:24px;color:#171717}"
"h1{font-size:28px}fieldset{border:1px solid #bbb;margin:12px 0;padding:12px}label{display:block;margin:8px 0}"
"input,select,button{font:inherit;padding:10px;width:100%%;box-sizing:border-box}button{background:#111;color:white;border:0}"
"small{color:#555}</style><h1>TickStone</h1><form method='post' action='/save'>"
"<fieldset><legend>WiFi</legend><label>Nätverk<select name='ssid'><option value=''>Välj nätverk</option>%s</select></label>"
"<label>Dolt nätverk (valfritt)<input name='ssid_custom' maxlength='32'></label><label>Lösenord<input name='pass' type='password' maxlength='63'></label>"
"<label>Synk-URL<input name='url' maxlength='191' placeholder='https://...'></label></fieldset>"
"<p><small>Habit-inställningar</small></p>%s"
"<button>Spara</button></form>";

static bool append_html_escaped(char *out, size_t size, size_t *used, const char *text)
{
    while (*text) {
        const char *escaped = NULL;
        switch (*text) {
        case '&': escaped = "&amp;"; break;
        case '<': escaped = "&lt;"; break;
        case '>': escaped = "&gt;"; break;
        case '\'': escaped = "&#39;"; break;
        case '"': escaped = "&quot;"; break;
        default: break;
        }
        const char one[2] = {*text, 0};
        const char *part = escaped ? escaped : one;
        const size_t length = strlen(part);
        if (*used + length >= size) return false;
        memcpy(out + *used, part, length);
        *used += length;
        out[*used] = 0;
        ++text;
    }
    return true;
}

static void build_network_options(char *out, size_t size)
{
    wifi_scan_config_t scan = {.show_hidden = false};
    if (esp_wifi_scan_start(&scan, true) != ESP_OK) return;

    uint16_t count = 20;
    wifi_ap_record_t *records = calloc(count, sizeof(*records));
    if (!records) return;
    if (esp_wifi_scan_get_ap_records(&count, records) != ESP_OK) {
        free(records);
        return;
    }

    size_t used = 0;
    for (uint16_t i = 0; i < count; ++i) {
        const char *ssid = (const char *)records[i].ssid;
        if (!ssid[0]) continue;
        bool duplicate = false;
        for (uint16_t previous = 0; previous < i; ++previous) {
            duplicate = duplicate || strcmp(ssid, (const char *)records[previous].ssid) == 0;
        }
        if (duplicate || used + 18 >= size) continue;
        memcpy(out + used, "<option value='", 15); used += 15; out[used] = 0;
        if (!append_html_escaped(out, size, &used, ssid) || used + 2 >= size) break;
        memcpy(out + used, "'>", 2); used += 2; out[used] = 0;
        if (!append_html_escaped(out, size, &used, ssid) || used + 10 >= size) break;
        memcpy(out + used, "</option>", 9); used += 9; out[used] = 0;
    }
    free(records);
}

static esp_err_t send_page(httpd_req_t *req)
{
    const size_t rows_size = 7000;
    char *rows = calloc(1, rows_size);
    if (!rows) {
        return httpd_resp_send_err(req, 500, "Minnet rackte inte");
    }
    size_t used = 0;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    for (size_t i = 0; i < HABIT_APP_MAX_HABITS; ++i) {
        const habit_config_t *h = NULL;
        for (size_t j = 0; j < s_count; ++j) {
            if (s_habits[j].id == i) { h = &s_habits[j]; break; }
        }
        int written = snprintf(rows + used, rows_size - used,
            "<fieldset><legend>Habit %u</legend><label>Kod (A-Z, 0-9, max 3)<input name='n%u' maxlength='3' pattern='[A-Za-z0-9]{0,3}' value='%s'></label>"
            "<label>Namn (max 15)<input name='f%u' maxlength='15' pattern='[A-Za-z0-9 ]{0,15}' value='%s'></label>"
            "<label>Typ<select name='t%u'><option value='c'%s>Tillfalle</option><option value='t'%s>Timer</option><option value='s'%s>Tidtagare</option></select></label>"
            "<label>Standardminuter<input name='d%u' type='number' min='1' max='1440' value='%u'></label></fieldset>",
            (unsigned)(i + 1), (unsigned)i, h ? h->label : "",
            (unsigned)i, h ? h->name : "", (unsigned)i,
            (!h || h->type == HABIT_TYPE_COUNT) ? " selected" : "",
            (h && h->type == HABIT_TYPE_TIME && h->time_mode == HABIT_TIME_TIMER) ? " selected" : "",
            (h && h->type == HABIT_TYPE_TIME && h->time_mode == HABIT_TIME_STOPWATCH) ? " selected" : "",
            (unsigned)i, h ? h->default_minutes : 5);
        if (written < 0 || (size_t)written >= rows_size - used) {
            xSemaphoreGive(s_lock);
            free(rows);
            return httpd_resp_send_err(req, 500, "Sidan blev for stor");
        }
        used += (size_t)written;
    }
    xSemaphoreGive(s_lock);
    size_t html_size = sizeof(PAGE) + strlen(s_network_options) + used;
    char *html = malloc(html_size);
    if (!html) {
        free(rows);
        return httpd_resp_send_err(req, 500, "Minnet rackte inte");
    }
    snprintf(html, html_size, PAGE, s_network_options, rows);
    free(rows);
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    esp_err_t err = httpd_resp_send(req, html, HTTPD_RESP_USE_STRLEN);
    free(html); return err;
}

static esp_err_t save_page(httpd_req_t *req)
{
    if (req->content_len <= 0 || req->content_len > 4096) return httpd_resp_send_err(req, 400, "Bad request");
    char *body = calloc(1, req->content_len + 1); if (!body) return ESP_ERR_NO_MEM;
    size_t received = 0;
    while (received < req->content_len) {
        int got = httpd_req_recv(req, body + received, req->content_len - received);
        if (got <= 0) { free(body); return ESP_FAIL; }
        received += (size_t)got;
    }
    habit_web_config_t parsed;
    if (!habit_web_config_parse(body, &parsed)) { free(body); return httpd_resp_send_err(req, 400, "Ogiltiga installningar"); }
    free(body);
    if (parsed.sync_url[0]) {
        strlcpy(s_sync_url, parsed.sync_url, sizeof(s_sync_url));
        nvs_handle_t n; if (nvs_open("ticknet", NVS_READWRITE, &n) == ESP_OK) {
            nvs_set_str(n, "url", s_sync_url); nvs_commit(n); nvs_close(n);
        }
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    memcpy(s_habits, parsed.habits, sizeof(parsed.habits)); s_count = parsed.habit_count; s_pending = true;
    xSemaphoreGive(s_lock);
    if (parsed.ssid[0]) {
        wifi_config_t sta = {0}; strlcpy((char *)sta.sta.ssid, parsed.ssid, sizeof(sta.sta.ssid));
        strlcpy((char *)sta.sta.password, parsed.password, sizeof(sta.sta.password));
        esp_wifi_set_config(WIFI_IF_STA, &sta); esp_wifi_set_mode(WIFI_MODE_APSTA); esp_wifi_connect();
    }
    httpd_resp_set_status(req, "303 See Other"); httpd_resp_set_hdr(req, "Location", "/"); return httpd_resp_send(req, NULL, 0);
}

static void start_server(void)
{
    if (s_server) return;
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG(); cfg.lru_purge_enable = true;
    if (httpd_start(&s_server, &cfg) != ESP_OK) return;
    const httpd_uri_t root = {.uri="/", .method=HTTP_GET, .handler=send_page};
    const httpd_uri_t save = {.uri="/save", .method=HTTP_POST, .handler=save_page};
    httpd_register_uri_handler(s_server, &root); httpd_register_uri_handler(s_server, &save);
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_status.connected = false;
        s_status.provisioning = true;
        strlcpy(s_status.address, "192.168.4.1", sizeof(s_status.address));
        esp_wifi_set_mode(WIFI_MODE_APSTA);
        esp_wifi_connect();
        ESP_LOGW(TAG, "WiFi disconnected; provisioning available on %s", s_ap_ssid);
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = data; snprintf(s_status.address, sizeof(s_status.address), IPSTR, IP2STR(&e->ip_info.ip));
        s_status.connected = true; start_server();
        if (!s_sntp_started) { esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org"); esp_netif_sntp_init(&cfg); s_sntp_started = true; }
        if (s_status.provisioning) {
            s_status.provisioning = false;
            esp_wifi_set_mode(WIFI_MODE_STA);
        }
    }
}

esp_err_t tickstone_network_start(const habit_config_t *habits, size_t count)
{
    s_lock = xSemaphoreCreateMutex(); if (!s_lock) return ESP_ERR_NO_MEM;
    tickstone_network_update_habits(habits, count);
    nvs_handle_t n; size_t url_size = sizeof(s_sync_url);
    if (nvs_open("ticknet", NVS_READONLY, &n) == ESP_OK) { nvs_get_str(n, "url", s_sync_url, &url_size); nvs_close(n); }
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta(); s_ap = esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));
    wifi_config_t sta = {0}; esp_wifi_get_config(WIFI_IF_STA, &sta);
    const bool has_saved_network = sta.sta.ssid[0] != 0;
    uint8_t mac[6]; esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    wifi_config_t ap = {.ap={.channel=1,.max_connection=4,.authmode=WIFI_AUTH_WPA2_PSK}};
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "TickStone-%02X%02X", mac[4], mac[5]);
    strlcpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid)); ap.ap.ssid_len = strlen(s_ap_ssid);
    strlcpy((char *)ap.ap.password, "tickstone", sizeof(ap.ap.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    strcpy(s_status.address, "192.168.4.1"); s_status.provisioning = true;
    ESP_ERROR_CHECK(esp_wifi_start());
    build_network_options(s_network_options, sizeof(s_network_options));
    start_server();
    if (has_saved_network) esp_wifi_connect();
    ESP_LOGI(TAG, "Web UI: http://%s", s_status.address); return ESP_OK;
}

void tickstone_network_update_habits(const habit_config_t *habits, size_t count)
{
    if (!s_lock) return;
    if (count > HABIT_APP_MAX_HABITS) count = HABIT_APP_MAX_HABITS;
    xSemaphoreTake(s_lock, portMAX_DELAY); memcpy(s_habits, habits, count * sizeof(*habits)); s_count = count; xSemaphoreGive(s_lock);
}

bool tickstone_network_take_habits(habit_config_t *habits, size_t *count)
{
    if (!s_lock || !habits || !count) return false;
    bool result;
    xSemaphoreTake(s_lock, portMAX_DELAY); result = s_pending; if (result) { memcpy(habits, s_habits, s_count * sizeof(*habits)); *count = s_count; s_pending = false; } xSemaphoreGive(s_lock); return result;
}

tickstone_network_status_t tickstone_network_status(void)
{
    s_status.clock_synced = time(NULL) >= 1704067200; return s_status;
}

bool tickstone_network_sync_log(const habit_log_t *log)
{
    if (!log || !s_status.connected || !s_sync_url[0]) return false;
    char json[320], id[24];
    if (!sync_payload_build(log, json, sizeof(json), id, sizeof(id))) return false;
    esp_http_client_config_t cfg = {
        .url=s_sync_url,
        .method=HTTP_METHOD_POST,
        .timeout_ms=5000,
        .crt_bundle_attach=esp_crt_bundle_attach,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg); if (!client) return false;
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_header(client, "Idempotency-Key", id);
    esp_http_client_set_post_field(client, json, strlen(json));
    esp_err_t err = esp_http_client_perform(client);
    int status = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    return status >= 200 && status < 300;
}
