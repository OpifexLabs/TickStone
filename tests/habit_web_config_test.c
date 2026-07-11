#include "habit_web_config.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    habit_web_config_t cfg;
    assert(habit_web_config_parse("ssid=Mitt+WiFi&pass=a%26b&url=https%3A%2F%2Fx.test%2Flog&n0=str&f0=stracka+pa+mig&t0=c&d0=5&n3=med&f3=meditation&t3=t&d3=12&n9=sta&f9=stada&t9=s&d9=1", &cfg));
    assert(!strcmp(cfg.ssid, "Mitt WiFi") && !strcmp(cfg.password, "a&b"));
    assert(cfg.habit_count == 3 && cfg.habits[0].id == 0 && cfg.habits[1].id == 3 && cfg.habits[2].id == 9);
    assert(!strcmp(cfg.habits[0].label, "STR"));
    assert(!strcmp(cfg.habits[0].name, "STRACKA PA MIG"));
    assert(cfg.habits[1].type == HABIT_TYPE_TIME && cfg.habits[2].type == HABIT_TYPE_TIME);
    assert(cfg.habits[1].time_mode == HABIT_TIME_TIMER && cfg.habits[2].time_mode == HABIT_TIME_TIMER);
    assert(!habit_web_config_parse("n0=TOOLONG&t0=c&d0=5", &cfg));
    assert(!habit_web_config_parse("n0=BAD!&t0=c&d0=5", &cfg));
    assert(!habit_web_config_parse("n0=OK&f0=NAME!&t0=c&d0=5", &cfg));
    assert(!habit_web_config_parse("n0=OK&t0=t&d0=0", &cfg));
    assert(!habit_web_config_parse("n0=OK&t0=t&d0=100", &cfg));
    assert(!habit_web_config_parse("n0=OK&t0=x&d0=5", &cfg));
    assert(!habit_web_config_parse("ssid=x", &cfg));
    assert(habit_web_config_parse("ssid=Lista&ssid_custom=Dolt+Nat&n0=OK&t0=c&d0=5", &cfg));
    assert(!strcmp(cfg.ssid, "Dolt Nat"));
    puts("habit_web_config_test: OK");
    return 0;
}
