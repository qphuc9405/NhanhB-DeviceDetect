#include "common.h"
#include "freertos/queue.h"
#include "driver/uart.h"
#include "cJSON.h"
#include <stdatomic.h>
/* ESP-IDF 5.5.4, ESP32-C3, UART0 GPIO21/20 (CH340 boards). */
#define MAX_IE 24 /* đủ cho Probe Request điện thoại; IE thừa bị bỏ */
typedef struct {int64_t ts;uint8_t mac[6],channel;int8_t rssi;uint16_t frame_seq;bool retry;uint8_t ie_n,ie[2*MAX_IE];} item_t;
static QueueHandle_t queue;
static atomic_uint seen,dropped,invalid,serial_errors,bytes_written;
static char boot[20];static uint8_t own[6];static uint32_t seq;
static cJSON *base(const char *type,int64_t ts) {
    cJSON *j=cJSON_CreateObject();if(!j)return NULL;
    cJSON_AddNumberToObject(j,"v",1);cJSON_AddStringToObject(j,"type",type);
    cJSON_AddStringToObject(j,"node","sniffer");cJSON_AddStringToObject(j,"boot_id",boot);
    cJSON_AddNumberToObject(j,"ts_us",(double)ts);cJSON_AddNumberToObject(j,"seq",seq++);return j;
}
static void mac_json(cJSON *j,const char *key,const uint8_t *mac) {
    char s[18];snprintf(s,sizeof(s),MACSTR,MAC2STR(mac));cJSON_AddStringToObject(j,key,s);
}
static void emit(cJSON *j) {
    if(!j){atomic_fetch_add(&serial_errors,1);return;}
    char *s=cJSON_PrintUnformatted(j);cJSON_Delete(j);
    if(!s){atomic_fetch_add(&serial_errors,1);return;}
    int len=strlen(s),n=uart_write_bytes(UART_NUM_0,s,len),e=uart_write_bytes(UART_NUM_0,"\n",1);
    if(n!=len || e!=1)atomic_fetch_add(&serial_errors,1);
    if(n>0)atomic_fetch_add(&bytes_written,n);
    if(e>0)atomic_fetch_add(&bytes_written,e);
    cJSON_free(s);
}
static void receive(void *buf,wifi_promiscuous_pkt_type_t type) {
    if(!buf || type!=WIFI_PKT_MGMT)return;
    const wifi_promiscuous_pkt_t *p=buf;
    if(p->rx_ctrl.sig_len<24 || p->rx_ctrl.rx_state!=0){atomic_fetch_add(&invalid,1);return;}
    const uint8_t *b=p->payload;
    if((b[0]&0xfc)!=0x40 || !memcmp(b+10,own,6))return;
    atomic_fetch_add(&seen,1);
    item_t x={.ts=esp_timer_get_time(),.channel=p->rx_ctrl.channel,.rssi=p->rx_ctrl.rssi,
        .frame_seq=(uint16_t)((b[22]|((uint16_t)b[23]<<8))>>4),.retry=(b[1]&8)!=0};
    memcpy(x.mac,b+10,6);
    /* Danh sách (mã IE, độ dài) theo thứ tự trong khung; sig_len gồm 4 byte FCS */
    int pos=24,end=p->rx_ctrl.sig_len-4;
    while(pos+2<=end && x.ie_n<MAX_IE && pos+2+b[pos+1]<=end) {
        x.ie[2*x.ie_n]=b[pos];x.ie[2*x.ie_n+1]=b[pos+1];x.ie_n++;pos+=2+b[pos+1];
    }
    if(xQueueSend(queue,&x,0)!=pdTRUE)atomic_fetch_add(&dropped,1);
}
static void output_task(void *arg) {
    (void)arg;item_t x;int64_t last=0,next_hop=0;uint8_t ch=CONFIG_PROBE_FIXED_CHANNEL;
    for(;;) {
        int64_t now=esp_timer_get_time();
#ifdef CONFIG_PROBE_HOPPING
        if(next_hop && now>=next_hop) {
            ch=ch>=CONFIG_PROBE_LAST_CHANNEL?1:ch+1;
            ESP_ERROR_CHECK(esp_wifi_set_channel(ch,WIFI_SECOND_CHAN_NONE));
            cJSON *j=base("channel",esp_timer_get_time());
            if(j){cJSON_AddNumberToObject(j,"channel",ch);cJSON_AddNumberToObject(j,"dwell_ms",CONFIG_PROBE_DWELL_MS);}emit(j);
            next_hop=now+(int64_t)CONFIG_PROBE_DWELL_MS*1000;
        }
#endif
        if(!next_hop)next_hop=now+(int64_t)CONFIG_PROBE_DWELL_MS*1000;
        if(now-last>=1000000 || !last) {
            cJSON *j=base("status",now);
            if(j) {
                cJSON_AddBoolToObject(j,"capture_active",true);mac_json(j,"own_mac",own);
                cJSON_AddNumberToObject(j,"channel",ch);
                cJSON_AddNumberToObject(j,"probe_seen",atomic_load(&seen));cJSON_AddNumberToObject(j,"probe_dropped",atomic_load(&dropped));
                cJSON_AddNumberToObject(j,"invalid",atomic_load(&invalid));cJSON_AddNumberToObject(j,"serial_errors",atomic_load(&serial_errors));
                cJSON_AddNumberToObject(j,"bytes_written",atomic_load(&bytes_written));cJSON_AddNumberToObject(j,"serial_baud",460800);
                cJSON_AddBoolToObject(j,"sniffer_enabled",true);
#ifdef CONFIG_PROBE_HOPPING
                cJSON_AddStringToObject(j,"scan_mode","hopping");
#else
                cJSON_AddStringToObject(j,"scan_mode","fixed");
#endif
                cJSON_AddNumberToObject(j,"dwell_ms",CONFIG_PROBE_DWELL_MS);
            }emit(j);last=now;
        }
        if(xQueueReceive(queue,&x,pdMS_TO_TICKS(10))==pdTRUE) {
            cJSON *j=base("probe",x.ts);
            if(j){mac_json(j,"source_mac",x.mac);cJSON_AddNumberToObject(j,"rssi",x.rssi);
                cJSON_AddNumberToObject(j,"channel",x.channel);cJSON_AddNumberToObject(j,"frame_seq",x.frame_seq);
                cJSON_AddBoolToObject(j,"retry",x.retry);
                char ie[MAX_IE*8+1];int n=0;ie[0]=0;
                for(int i=0;i<x.ie_n;i++)n+=snprintf(ie+n,sizeof(ie)-n,"%s%u:%u",i?",":"",x.ie[2*i],x.ie[2*i+1]);
                cJSON_AddStringToObject(j,"ie",ie);}emit(j);
        }
    }
}
void app_main(void) {
    snprintf(boot,sizeof(boot),"%08" PRIx32 "%08" PRIx32,esp_random(),esp_random());
    queue=xQueueCreate(128,sizeof(item_t));configASSERT(queue);
    uart_config_t u={.baud_rate=460800,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0,&u));ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,1024,8192,0,NULL,0));
    sniffer_init();wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_NULL));
    ESP_ERROR_CHECK(esp_wifi_set_country_code(CONFIG_PROBE_COUNTRY,true));
    ESP_ERROR_CHECK(esp_wifi_start());ESP_ERROR_CHECK(esp_read_mac(own,ESP_MAC_WIFI_STA));
    wifi_country_t country;ESP_ERROR_CHECK(esp_wifi_get_country(&country));
    configASSERT(CONFIG_PROBE_LAST_CHANNEL<=country.schan+country.nchan-1);
    configASSERT(CONFIG_PROBE_FIXED_CHANNEL>=country.schan && CONFIG_PROBE_FIXED_CHANNEL<=country.schan+country.nchan-1);
    ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_PROBE_FIXED_CHANNEL,WIFI_SECOND_CHAN_NONE));
    wifi_promiscuous_filter_t f={.filter_mask=WIFI_PROMIS_FILTER_MASK_MGMT};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&f));ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(receive));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    configASSERT(xTaskCreate(output_task,"probe_output",6144,NULL,4,NULL)==pdPASS);
}
