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
SCALE = 2


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
    printf("%s|%d|%d|%d|%d|%d|%d|%d|%s|%s|%s\n",
           title,
           (int)screen->id,
           (int)screen->home_mode,
           (int)screen->icon,
           (int)screen->left_action,
           (int)screen->ok_action,
           (int)screen->right_action,
           screen->show_home_nav ? 1 : 0,
           screen->header,
           screen->primary,
           screen->secondary);
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
    show(&app, "04_back_action", 103);
    long_press(&app, HABIT_BUTTON_RIGHT, 104);
    show(&app, "05_home_logs_empty", 104);
    press(&app, HABIT_BUTTON_OK, 105);
    show(&app, "06_empty_logs_exit", 105);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_OK, 101);
    show(&app, "07_count_logged", 101);
    long_press(&app, HABIT_BUTTON_OK, 102);
    show(&app, "08_count_undo", 102);

    press(&app, HABIT_BUTTON_RIGHT, 110);
    show(&app, "09_action_timer", 110);
    press(&app, HABIT_BUTTON_OK, 111);
    show(&app, "10_timer_setup", 111);
    press(&app, HABIT_BUTTON_RIGHT, 112);
    show(&app, "11_timer_plus_minute", 112);
    press(&app, HABIT_BUTTON_OK, 113);
    show(&app, "12_timer_running_start", 113);
    show(&app, "13_timer_running_seconds", 118);
    press(&app, HABIT_BUTTON_OK, 119);
    show(&app, "14_timer_paused", 119);
    press(&app, HABIT_BUTTON_OK, 124);
    show(&app, "15_timer_resumed", 124);
    press(&app, HABIT_BUTTON_LEFT, 125);
    show(&app, "16_cancel_confirmation", 125);
    press(&app, HABIT_BUTTON_OK, 126);
    show(&app, "17_cancel_back", 126);
    press(&app, HABIT_BUTTON_RIGHT, 130);
    show(&app, "18_timer_saved", 130);
    show(&app, "19_back_to_action", 135);

    press(&app, HABIT_BUTTON_RIGHT, 140);
    show(&app, "20_action_stopwatch", 140);
    press(&app, HABIT_BUTTON_OK, 141);
    show(&app, "21_stopwatch_start", 141);
    show(&app, "22_stopwatch_seconds", 146);
    press(&app, HABIT_BUTTON_OK, 147);
    show(&app, "23_stopwatch_paused", 147);
    press(&app, HABIT_BUTTON_RIGHT, 150);
    show(&app, "24_stopwatch_saved", 150);
    show(&app, "25_select_after_save", 155);

    long_press(&app, HABIT_BUTTON_RIGHT, 154);
    show(&app, "26_logs_latest", 154);
    press(&app, HABIT_BUTTON_RIGHT, 155);
    show(&app, "27_logs_previous", 155);
    press(&app, HABIT_BUTTON_OK, 156);
    show(&app, "28_log_stats", 156);
    press(&app, HABIT_BUTTON_OK, 157);
    show(&app, "29_stats_exit", 157);

    long_press(&app, HABIT_BUTTON_OK, 160);
    show(&app, "30_stats_week", 160);
    press(&app, HABIT_BUTTON_RIGHT, 161);
    show(&app, "31_stats_delta", 161);
    press(&app, HABIT_BUTTON_RIGHT, 162);
    show(&app, "32_stats_month", 162);
    press(&app, HABIT_BUTTON_RIGHT, 163);
    show(&app, "33_stats_average", 163);
    press(&app, HABIT_BUTTON_OK, 164);
    show(&app, "34_stats_exit", 164);

    habit_app_init(&app);
    press(&app, HABIT_BUTTON_RIGHT, 170);
    press(&app, HABIT_BUTTON_OK, 171);
    press(&app, HABIT_BUTTON_OK, 172);
    show(&app, "35_timer_cancel_running", 176);
    press(&app, HABIT_BUTTON_LEFT, 177);
    show(&app, "36_timer_cancel_prompt", 177);
    press(&app, HABIT_BUTTON_RIGHT, 178);
    show(&app, "37_timer_cancelled", 178);

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


def load_icons():
    header = (ROOT / "components" / "habit_app" / "include" / "habit_app.h").read_text()
    names = re.findall(r"\b(HABIT_UI_ICON_[A-Z_]+)(?:\s*=\s*\d+)?,", header)
    icon_ids = {name: index for index, name in enumerate(names)}

    source = (ROOT / "main" / "app_main.c").read_text()
    pattern = re.compile(r"\[(HABIT_UI_ICON_[A-Z_]+)\]\s*=\s*\{([^}]+)\}")
    icons = {}
    for name, values in pattern.findall(source):
        icons[icon_ids[name]] = [int(value.strip(), 0) for value in values.split(",") if value.strip()]
    return icons, icon_ids


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


def draw_icon_2x(pixels, icons, x, page, icon_id):
    if icon_id == 0 or icon_id not in icons:
        return
    y0 = page * 8
    for sy, row in enumerate(icons[icon_id]):
        for sx in range(8):
            if row & (1 << (7 - sx)):
                tx = x + sx * 2
                ty = y0 + sy * 2
                set_px(pixels, tx, ty)
                set_px(pixels, tx + 1, ty)
                set_px(pixels, tx, ty + 1)
                set_px(pixels, tx + 1, ty + 1)


def draw_icon_1x(pixels, icons, x, page, icon_id):
    if icon_id == 0 or icon_id not in icons:
        return
    y0 = page * 8
    for sy, row in enumerate(icons[icon_id]):
        for sx in range(8):
            if row & (1 << (7 - sx)):
                set_px(pixels, x + sx, y0 + sy)


def center_x_2x(text):
    width = len(text) * 12
    return 0 if width >= OLED_W else (OLED_W - width) // 2


def center_x_1x(text):
    width = len(text) * 6
    return 0 if width >= OLED_W else (OLED_W - width) // 2


def render_screen(font, icons, icon_ids, view):
    image = Image.new("L", (OLED_W, OLED_H), 0)
    pixels = image.load()
    header_icon = view["icon"]
    if view["show_home_nav"]:
        header_icon = (
            icon_ids["HABIT_UI_ICON_HABITS"] if view["home_mode"] == 1
            else icon_ids["HABIT_UI_ICON_LOGS"] if view["home_mode"] == 2
            else icon_ids["HABIT_UI_ICON_ACTION"]
        )
    header_width = 12 + len(view["header"]) * 6 if header_icon else len(view["header"]) * 6
    header_x = 0 if header_width >= OLED_W else (OLED_W - header_width) // 2
    if header_icon:
        draw_icon_1x(pixels, icons, header_x, 1, header_icon)
        header_x += 12
    draw_text_1x(pixels, font, header_x, 1, view["header"])

    draw_text_2x(pixels, font, center_x_2x(view["primary"]), 5, view["primary"])
    draw_text_1x(pixels, font, center_x_1x(view["secondary"]), 8, view["secondary"])
    draw_icon_2x(pixels, icons, 12, 12, view["left_action"])
    draw_icon_2x(pixels, icons, 56, 12, view["ok_action"])
    draw_icon_2x(pixels, icons, 100, 12, view["right_action"])
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
        values = line.split("|")
        rows.append({
            "title": values[0],
            "screen_id": int(values[1]),
            "home_mode": int(values[2]),
            "icon": int(values[3]),
            "left_action": int(values[4]),
            "ok_action": int(values[5]),
            "right_action": int(values[6]),
            "show_home_nav": bool(int(values[7])),
            "header": values[8],
            "primary": values[9],
            "secondary": values[10],
        })
    return rows


def annotate(tile, view):
    tile_rgb = tile.convert("RGB").resize((OLED_W * SCALE, OLED_H * SCALE), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (OLED_W * SCALE, OLED_H * SCALE + 48), (18, 18, 18))
    canvas.paste(tile_rgb, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, OLED_H * SCALE + 5), view["title"], fill=(220, 220, 220))
    draw.text((8, OLED_H * SCALE + 24), f'{view["header"]} / {view["primary"]} / {view["secondary"]}', fill=(155, 210, 255))
    return canvas


def main():
    font = load_font()
    icons, icon_ids = load_icons()
    rows = load_flow_rows()
    tiles = []

    for view in rows:
        image = render_screen(font, icons, icon_ids, view)
        image.save(OUT_DIR / f'{view["title"]}.png')
        tiles.append(annotate(image, view))

    cols = 6
    rows_count = math.ceil(len(tiles) / cols)
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows_count * th), (30, 30, 30))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * tw, (i // cols) * th))
    sheet.save(OUT_DIR / "all_flows_contact_sheet.png")

    print(OUT_DIR / "all_flows_contact_sheet.png")
    for view in rows:
        print(OUT_DIR / f'{view["title"]}.png')


if __name__ == "__main__":
    main()
