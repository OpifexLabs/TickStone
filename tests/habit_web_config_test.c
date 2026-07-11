#include "habit_web_config.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    habit_web_config_t cfg;
    assert(habit_web_config_parse("ssid=Mitt+WiFi&pass=a%26b&url=https%3A%2F%2Fx.test%2Flog&n0=str&t0=c&d0=5&n3=med&t3=t&d3=12&n9=sta&t9=s&d9=1", &cfg));
    assert(!strcmp(cfg.ssid, "Mitt WiFi") && !strcmp(cfg.password, "a&b"));
    assert(cfg.habit_count == 3 && cfg.habits[0].id == 0 && cfg.habits[1].id == 3 && cfg.habits[2].id == 9);
    assert(!strcmp(cfg.habits[0].label, "STR"));
    assert(cfg.habits[1].time_mode == HABIT_TIME_TIMER && cfg.habits[2].time_mode == HABIT_TIME_STOPWATCH);
    assert(!habit_web_config_parse("n0=TOOLONG&t0=c&d0=5", &cfg));
    assert(!habit_web_config_parse("n0=BAD!&t0=c&d0=5", &cfg));
    assert(!habit_web_config_parse("n0=OK&t0=t&d0=0", &cfg));
    assert(!habit_web_config_parse("n0=OK&t0=x&d0=5", &cfg));
    assert(!habit_web_config_parse("ssid=x", &cfg));
    puts("habit_web_config_test: OK");
    return 0;
}
