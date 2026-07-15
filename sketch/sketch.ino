/**
 * UNO-Q Remote Control Firmware
 * STM32U585. Matrix + LED3/LED4. RPC via Bridge.provide().
 */

#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"
#include "matrix_font.h"
#include "matrix_patterns.h"
#include "matrix_scroll.h"

#define FLIP_X 0
#define FLIP_Y 0

struct LedBlinkState { bool enabled, is_on; unsigned long last_toggle_ms; uint16_t on_ms, off_ms; };
static LedBlinkState led_blink[5];
static ScrollEngine scroll;
static ArduinoLEDMatrix matrix;

// ---- LED helpers (active-low: LOW=on, HIGH=off) ----
static void led_write_rgb(uint8_t idx, uint8_t r, uint8_t g, uint8_t b) {
    bool r_on = (r > 127), g_on = (g > 127), b_on = (b > 127);
    if (idx==3) {
        digitalWrite(LED3_R, r_on ? LOW : HIGH);
        digitalWrite(LED3_G, g_on ? LOW : HIGH);
        digitalWrite(LED3_B, b_on ? LOW : HIGH);
    } else if (idx==4) {
        digitalWrite(LED4_R, r_on ? LOW : HIGH);
        digitalWrite(LED4_G, g_on ? LOW : HIGH);
        digitalWrite(LED4_B, b_on ? LOW : HIGH);
    }
}
static void led_off(uint8_t idx) { led_write_rgb(idx, 0, 0, 0); }
static void led_on(uint8_t idx)  { led_write_rgb(idx, 255, 255, 255); }
static void led_blink_tick() {
    unsigned long now = millis();
    for (uint8_t i=3; i<=4; i++) {
        if (!led_blink[i].enabled) continue;
        uint16_t interval = led_blink[i].is_on ? led_blink[i].on_ms : led_blink[i].off_ms;
        if (now - led_blink[i].last_toggle_ms >= interval) {
            led_blink[i].last_toggle_ms = now;
            led_blink[i].is_on = !led_blink[i].is_on;
            if (led_blink[i].is_on) led_on(i); else led_off(i);
        }
    }
}

// ---- RPC callbacks ----
static void rpc_scroll_text(String text) { scroll_start_text(scroll, text.c_str(), 80); }
static void rpc_show_pattern(String name) {
    const uint8_t* pat = pattern_lookup(name.c_str());
    scroll_show_pattern(scroll, pat ? pat : pattern_lookup("cross"));
}
static void rpc_show_animation(String name) {
    const AnimEntry* entry = anim_lookup(name.c_str());
    if (entry) scroll_start_animation(scroll, entry->frames, entry->frame_count, entry->frame_delay_ms);
}
static void rpc_clear() { scroll_clear(scroll); }
static void rpc_led_set(uint8_t idx, String state) {
    if (idx<3 || idx>4) return;
    led_blink[idx].enabled = false;
    const char* s = state.c_str();
    if      (strcmp(s,"on")==0)    led_on(idx);
    else if (strcmp(s,"off")==0)   led_off(idx);
    else if (strcmp(s,"blink")==0) {
        led_blink[idx].enabled=true; led_blink[idx].on_ms=500; led_blink[idx].off_ms=500;
        led_blink[idx].is_on=false; led_blink[idx].last_toggle_ms=millis(); led_off(idx);
    }
}
static void rpc_led_rgb(uint8_t idx, uint8_t r, uint8_t g, uint8_t b) {
    if (idx<3 || idx>4) return;
    led_blink[idx].enabled = false;
    led_write_rgb(idx, r, g, b);
}

void setup() {
    Bridge.begin();
    Bridge.provide("matrix.scroll_text",    rpc_scroll_text);
    Bridge.provide("matrix.show_pattern",   rpc_show_pattern);
    Bridge.provide("matrix.show_animation", rpc_show_animation);
    Bridge.provide("matrix.clear",          rpc_clear);
    Bridge.provide("led.set",              rpc_led_set);
    Bridge.provide("led.rgb",             rpc_led_rgb);

    pinMode(LED3_R,OUTPUT); pinMode(LED3_G,OUTPUT); pinMode(LED3_B,OUTPUT);
    pinMode(LED4_R,OUTPUT); pinMode(LED4_G,OUTPUT); pinMode(LED4_B,OUTPUT);
    led_off(3); led_off(4);

    matrix.begin(); matrix.setGrayscaleBits(8);
    scroll_init(scroll); matrix.draw(scroll.frame);
}

void loop() {
    scroll_tick(scroll, matrix);
    led_blink_tick();
    if (scroll.mode == MODE_SHOW_PATTERN || scroll.mode == MODE_CLEAR) {
        scroll_draw_static(scroll, matrix);
    }
    delay(10);
}
