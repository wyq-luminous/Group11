/**
 * matrix_scroll.h — Non-blocking scroll engine for 8×13 LED matrix.
 *
 * Builds a column buffer from ASCII text using the 5×7 font,
 * then slides a 13-column window across it frame by frame.
 *
 * Uses millis() for timing — no delay(), no blocking in loop().
 *
 * NOTE: Does NOT include Arduino_LED_Matrix.h. The main sketch includes it.
 * Uses forward declaration + matrix.draw(uint8_t*) which takes a 104-byte buffer.
 */

#ifndef MATRIX_SCROLL_H
#define MATRIX_SCROLL_H

#include <stdint.h>
#include <string.h>
#include "matrix_font.h"

class Arduino_LED_Matrix;

enum DisplayMode : uint8_t {
    MODE_CLEAR         = 0,
    MODE_SCROLL_TEXT   = 1,
    MODE_SHOW_PATTERN  = 2,
    MODE_SHOW_ANIMATION = 3,
};

struct ScrollEngine {
    uint8_t*      col_buffer;
    uint16_t      col_buffer_len;
    uint16_t      scroll_pos;
    unsigned long last_frame_ms;
    uint16_t      frame_delay_ms;
    DisplayMode   mode;
    uint8_t       frame[MATRIX_SIZE];
    const uint8_t* pattern_data;
    // Animation fields
    const uint8_t* anim_frames;    // PROGMEM pointer to first frame
    uint8_t       anim_frame_count;
    uint8_t       anim_current_frame;
};

inline void scroll_init(ScrollEngine& eng) {
    eng.col_buffer        = nullptr;
    eng.col_buffer_len    = 0;
    eng.scroll_pos        = 0;
    eng.last_frame_ms     = 0;
    eng.frame_delay_ms    = 80;
    eng.mode              = MODE_CLEAR;
    eng.pattern_data      = nullptr;
    eng.anim_frames       = nullptr;
    eng.anim_frame_count  = 0;
    eng.anim_current_frame = 0;
    memset(eng.frame, 0, sizeof(eng.frame));
}

inline uint16_t scroll_build_buffer(ScrollEngine& eng, const char* text) {
    if (eng.col_buffer) { free(eng.col_buffer); eng.col_buffer = nullptr; }
    size_t text_len = strlen(text);
    if (text_len == 0) { eng.col_buffer_len = 0; return 0; }
    uint16_t buf_len = MATRIX_COLS + text_len * (FONT_CHAR_WIDTH + FONT_CHAR_SPACING) + MATRIX_COLS;
    eng.col_buffer = (uint8_t*)calloc(buf_len, sizeof(uint8_t));
    if (!eng.col_buffer) return 0;
    uint16_t pos = MATRIX_COLS;
    for (size_t i = 0; i < text_len; i++) {
        char c = text[i];
        uint8_t idx = (c >= FONT_FIRST && c <= FONT_LAST) ? (c - FONT_FIRST) : 0;
        for (uint8_t col = 0; col < FONT_CHAR_WIDTH; col++) {
            if (pos < buf_len) eng.col_buffer[pos] = pgm_read_byte(&FONT[idx][col]);
            pos++;
        }
        if (pos < buf_len) eng.col_buffer[pos] = 0x00;
        pos++;
    }
    eng.col_buffer_len = buf_len;
    return buf_len;
}

inline void scroll_render_frame(ScrollEngine& eng, uint8_t* frame) {
    memset(frame, 0, MATRIX_SIZE);
    if (!eng.col_buffer || eng.col_buffer_len == 0) return;
    for (uint8_t col = 0; col < MATRIX_COLS; col++) {
        uint16_t buf_col = eng.scroll_pos + col;
        if (buf_col >= eng.col_buffer_len) continue;
        uint8_t col_byte = eng.col_buffer[buf_col];
        for (uint8_t row = 0; row < MATRIX_ROWS; row++) {
            uint8_t pixel = (col_byte & (1 << row)) ? 255 : 0;
#if defined(FLIP_X) && defined(FLIP_Y)
            uint8_t fx = FLIP_X ? (MATRIX_COLS - 1 - col) : col;
            uint8_t fy = FLIP_Y ? (MATRIX_ROWS - 1 - row) : row;
            frame[fy * MATRIX_COLS + fx] = pixel;
#elif defined(FLIP_X)
            uint8_t fx = FLIP_X ? (MATRIX_COLS - 1 - col) : col;
            frame[row * MATRIX_COLS + fx] = pixel;
#elif defined(FLIP_Y)
            uint8_t fy = FLIP_Y ? (MATRIX_ROWS - 1 - row) : row;
            frame[fy * MATRIX_COLS + col] = pixel;
#else
            frame[row * MATRIX_COLS + col] = pixel;
#endif
        }
    }
}

inline void scroll_render_pattern(ScrollEngine& eng) {
    if (!eng.pattern_data) { memset(eng.frame, 0, sizeof(eng.frame)); return; }
    for (uint8_t row = 0; row < MATRIX_ROWS; row++) {
        for (uint8_t col = 0; col < MATRIX_COLS; col++) {
            uint8_t pixel = pgm_read_byte(&eng.pattern_data[row * MATRIX_COLS + col]);
#if defined(FLIP_X) && defined(FLIP_Y)
            uint8_t fx = FLIP_X ? (MATRIX_COLS - 1 - col) : col;
            uint8_t fy = FLIP_Y ? (MATRIX_ROWS - 1 - row) : row;
            eng.frame[fy * MATRIX_COLS + fx] = pixel;
#elif defined(FLIP_X)
            uint8_t fx = FLIP_X ? (MATRIX_COLS - 1 - col) : col;
            eng.frame[row * MATRIX_COLS + fx] = pixel;
#elif defined(FLIP_Y)
            uint8_t fy = FLIP_Y ? (MATRIX_ROWS - 1 - row) : row;
            eng.frame[fy * MATRIX_COLS + col] = pixel;
#else
            eng.frame[row * MATRIX_COLS + col] = pixel;
#endif
        }
    }
}

inline void scroll_start_text(ScrollEngine& eng, const char* text, uint16_t delay_ms = 80) {
    eng.mode = MODE_SCROLL_TEXT;
    eng.frame_delay_ms = delay_ms;
    eng.scroll_pos = 0;
    eng.last_frame_ms = millis();
    eng.pattern_data = nullptr;
    scroll_build_buffer(eng, text);
}

inline void scroll_show_pattern(ScrollEngine& eng, const uint8_t* pattern_progmem) {
    if (eng.col_buffer) { free(eng.col_buffer); eng.col_buffer = nullptr; }
    eng.col_buffer_len = 0;
    eng.scroll_pos = 0;
    eng.mode = MODE_SHOW_PATTERN;
    eng.pattern_data = pattern_progmem;
    eng.anim_frames = nullptr;
    scroll_render_pattern(eng);
}

inline void scroll_start_animation(ScrollEngine& eng, const uint8_t* frames_progmem,
                                    uint8_t frame_count, uint16_t delay_ms) {
    if (eng.col_buffer) { free(eng.col_buffer); eng.col_buffer = nullptr; }
    eng.col_buffer_len = 0;
    eng.scroll_pos = 0;
    eng.mode = MODE_SHOW_ANIMATION;
    eng.pattern_data = nullptr;
    eng.anim_frames = frames_progmem;
    eng.anim_frame_count = frame_count;
    eng.anim_current_frame = 0;
    eng.frame_delay_ms = delay_ms;
    eng.last_frame_ms = millis();
    // Render first frame
    memcpy_P(eng.frame, frames_progmem, MATRIX_SIZE);
}

inline void scroll_clear(ScrollEngine& eng) {
    eng.mode = MODE_CLEAR;
    if (eng.col_buffer) { free(eng.col_buffer); eng.col_buffer = nullptr; }
    eng.col_buffer_len = 0;
    eng.scroll_pos = 0;
    eng.pattern_data = nullptr;
    eng.anim_frames = nullptr;
    eng.anim_frame_count = 0;
    eng.anim_current_frame = 0;
    memset(eng.frame, 0, sizeof(eng.frame));
}

// Called from loop(). Non-blocking — returns immediately if not time yet.
inline bool scroll_tick(ScrollEngine& eng, Arduino_LED_Matrix& matrix) {
    unsigned long now = millis();
    if (now - eng.last_frame_ms < eng.frame_delay_ms) return false;
    eng.last_frame_ms = now;

    if (eng.mode == MODE_SCROLL_TEXT) {
        scroll_render_frame(eng, eng.frame);
        matrix.draw(eng.frame);
        eng.scroll_pos++;
        if (eng.scroll_pos >= eng.col_buffer_len) eng.scroll_pos = 0;
        return true;
    }

    if (eng.mode == MODE_SHOW_ANIMATION && eng.anim_frames) {
        eng.anim_current_frame++;
        if (eng.anim_current_frame >= eng.anim_frame_count) {
            eng.anim_current_frame = 0;
        }
        size_t frame_offset = (size_t)eng.anim_current_frame * MATRIX_SIZE;
        memcpy_P(eng.frame, eng.anim_frames + frame_offset, MATRIX_SIZE);
        matrix.draw(eng.frame);
        return true;
    }

    return false;
}

inline void scroll_draw_static(ScrollEngine& eng, Arduino_LED_Matrix& matrix) {
    matrix.draw(eng.frame);
}

#endif
