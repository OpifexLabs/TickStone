#!/usr/bin/env python3
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "build" / "oled_flow_previews"
OLED_W = 128
OLED_H = 128
SCALE = 4


FLOW_C = r'''
#include "habit_app.h"

#include <stdio.h>

static void press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_SHORT, now);
}

static void long_press(habit_app_t *app, habit_button_t button, int64_t now)
{
    habit_app_handle_button(app, button, HABIT_PRESS_LONG, now);
}

static void show(habit_app_t *app, const char *title, int64_t now)
{
    habit_app_tick(app, now);
    const habit_screen_t *screen = habit_app_screen(app, now);
    printf("%s|%s|%s\n", title, screen->primary, screen->secondary);
}

int main(void)
{
    habit_app_t app;
    habit_app_init(&app);

    show(&app, "01_action_count", 100);
    long_press(&app, HABIT_BUTTON_LEFT, 101);
    show(&app, "02_home_habits", 101);
    press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "03_habits_cycle_type", 102);
    long_press(&app, HABIT_BUTTON_RIGHT, 103);
    show(&app, "04_home_logs_empty", 103);
    press(&app, HABIT_BUTTON_OK, 104);
    show(&app, "05_back_action", 104);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_OK, 101);
    show(&app, "06_count_logged", 101);
    long_press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "07_count_undo", 102);

    press(&app, HABIT_BUTTON_RIGHT, 110);
    show(&app, "08_action_timer", 110);
    press(&app, HABIT_BUTTON_OK, 111);
    show(&app, "09_timer_setup", 111);
    press(&app, HABIT_BUTTON_RIGHT, 112);
    show(&app, "10_timer_plus_minute", 112);
    press(&app, HABIT_BUTTON_OK, 113);
    show(&app, "11_timer_running_start", 113);
    show(&app, "12_timer_running_seconds", 118);
    press(&app, HABIT_BUTTON_OK, 119);
    show(&app, "13_timer_paused", 119);
    press(&app, HABIT_BUTTON_OK, 124);
    show(&app, "14_timer_resumed", 124);
    long_press(&app, HABIT_BUTTON_OK, 130);
    show(&app, "15_timer_saved", 130);
    show(&app, "16_back_to_action", 133);

    press(&app, HABIT_BUTTON_RIGHT, 140);
    show(&app, "17_action_stopwatch", 140);
    press(&app, HABIT_BUTTON_OK, 141);
    show(&app, "18_stopwatch_start", 141);
    show(&app, "19_stopwatch_seconds", 146);
    press(&app, HABIT_BUTTON_OK, 147);
    show(&app, "20_stopwatch_paused", 147);
    long_press(&app, HABIT_BUTTON_OK, 150);
    show(&app, "21_stopwatch_saved", 150);
    show(&app, "22_select_after_save", 153);

    long_press(&app, HABIT_BUTTON_RIGHT, 154);
    show(&app, "23_logs_latest", 154);
    press(&app, HABIT_BUTTON_RIGHT, 155);
    show(&app, "24_logs_previous", 155);
    press(&app, HABIT_BUTTON_OK, 156);
    show(&app, "25_logs_exit", 156);

    long_press(&app, HABIT_BUTTON_OK, 160);
    show(&app, "26_stats_week", 160);
    press(&app, HABIT_BUTTON_RIGHT, 161);
    show(&app, "27_stats_delta", 161);
    press(&app, HABIT_BUTTON_RIGHT, 162);
    show(&app, "28_stats_month", 162);
    press(&app, HABIT_BUTTON_RIGHT, 163);
    show(&app, "29_stats_average", 163);
    press(&app, HABIT_BUTTON_OK, 164);
    show(&app, "30_stats_exit", 164);

    press(&app, HABIT_BUTTON_LEFT, 170);
    press(&app, HABIT_BUTTON_OK, 171);
    press(&app, HABIT_BUTTON_OK, 172);
    show(&app, "31_timer_cancel_running", 176);
    long_press(&app, HABIT_BUTTON_LEFT, 177);
    show(&app, "32_timer_cancelled", 177);

    return 0;
}
'''


def load_font():
    source = (ROOT / "components" / "ssd1306_oled" / "ssd1306_oled.c").read_text()
    font = {" ": [0, 0, 0, 0, 0]}
    pattern = re.compile(r"\['(.?)'\]\s*=\s*\{([^}]+)\}")
    for char, values in pattern.findall(source):
        font[char] = [int(v.strip(), 0) for v in values.split(",") if v.strip()]
    return font


def glyph_for(font, char):
    glyph = font.get(char, font[" "])
    return glyph if any(glyph) else font[" "]


def set_px(pixels, x, y):
    if 0 <= x < OLED_W and 0 <= y < OLED_H:
        pixels[x, y] = 255


def draw_text_1x(pixels, font, x, page, text):
    y0 = page * 8
    for char in text:
        glyph = glyph_for(font, char)
        for sx in range(6):
            col = glyph[sx] if sx < 5 else 0
            for sy in range(7):
                if col & (1 << sy):
                    set_px(pixels, x + sx, y0 + sy)
        x += 6


def draw_text_2x(pixels, font, x, page, text):
    y0 = page * 8
    for char in text:
        glyph = glyph_for(font, char)
        for sx in range(6):
            col = glyph[sx] if sx < 5 else 0
            for sy in range(7):
                if col & (1 << sy):
                    tx = x + sx * 2
                    ty = y0 + sy * 2
                    set_px(pixels, tx, ty)
                    set_px(pixels, tx + 1, ty)
                    set_px(pixels, tx, ty + 1)
                    set_px(pixels, tx + 1, ty + 1)
        x += 12


def center_x_2x(text):
    width = len(text) * 12
    return 0 if width >= OLED_W else (OLED_W - width) // 2


def center_x_1x(text):
    width = len(text) * 6
    return 0 if width >= OLED_W else (OLED_W - width) // 2


def render_screen(font, primary, secondary):
    image = Image.new("L", (OLED_W, OLED_H), 0)
    pixels = image.load()
    draw_text_2x(pixels, font, center_x_2x(primary), 6, primary)
    if secondary:
        draw_text_1x(pixels, font, center_x_1x(secondary), 11, secondary)
    return image


def compile_flow_probe():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    c_path = OUT_DIR / "flow_probe.c"
    exe_path = OUT_DIR / "flow_probe"
    c_path.write_text(FLOW_C)
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Icomponents/habit_app/include",
            "components/habit_app/habit_app.c",
            str(c_path),
            "-o",
            str(exe_path),
        ],
        cwd=ROOT,
        check=True,
    )
    return exe_path


def load_flow_rows():
    exe = compile_flow_probe()
    output = subprocess.check_output([str(exe)], cwd=ROOT, text=True)
    rows = []
    for line in output.splitlines():
        title, primary, secondary = line.split("|")
        rows.append((title, primary, secondary))
    return rows


def annotate(tile, title, primary, secondary):
    tile_rgb = tile.convert("RGB").resize((OLED_W * SCALE, OLED_H * SCALE), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (OLED_W * SCALE, OLED_H * SCALE + 48), (18, 18, 18))
    canvas.paste(tile_rgb, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, OLED_H * SCALE + 5), title, fill=(220, 220, 220))
    draw.text((8, OLED_H * SCALE + 24), f"{primary} / {secondary}", fill=(155, 210, 255))
    return canvas


def main():
    font = load_font()
    rows = load_flow_rows()
    tiles = []

    for title, primary, secondary in rows:
        image = render_screen(font, primary, secondary)
        image.save(OUT_DIR / f"{title}.png")
        tiles.append(annotate(image, title, primary, secondary))

    cols = 5
    rows_count = math.ceil(len(tiles) / cols)
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows_count * th), (30, 30, 30))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * tw, (i // cols) * th))
    sheet.save(OUT_DIR / "all_flows_contact_sheet.png")

    print(OUT_DIR / "all_flows_contact_sheet.png")
    for title, _, _ in rows:
        print(OUT_DIR / f"{title}.png")


if __name__ == "__main__":
    main()
