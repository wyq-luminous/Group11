/**
 * matrix_patterns.h — Named icon patterns for 8×13 LED matrix.
 *
 * Each pattern is 8 rows × 13 columns = 104 uint8_t values.
 * Value 255 = pixel on, 0 = pixel off (compatible with setGrayscaleBits(8)).
 *
 * Patterns: warning, smiley, heart, cross, clear (all-off).
 * Stored in PROGMEM to save RAM.
 */

#ifndef MATRIX_PATTERNS_H
#define MATRIX_PATTERNS_H

#include <stdint.h>
#include <string.h>  // for memcpy_P

#define MATRIX_ROWS 8
#define MATRIX_COLS 13
#define MATRIX_SIZE (MATRIX_ROWS * MATRIX_COLS)  // 104

// -----------------------------------------------------------------------
// Pattern: WARNING — exclamation triangle
// -----------------------------------------------------------------------
static const uint8_t PATTERN_WARNING[MATRIX_SIZE] PROGMEM = {
    0,0,0,0,0,255,0,0,0,0,0,0,0,
    0,0,0,0,255,255,255,0,0,0,0,0,0,
    0,0,0,255,0,255,0,255,0,0,0,0,0,
    0,0,255,0,0,255,0,0,255,0,0,0,0,
    0,255,0,0,0,255,0,0,0,255,0,0,0,
    0,255,255,255,255,255,255,255,255,255,0,0,0,
    0,0,0,0,0,255,0,0,0,0,0,0,0,
    0,0,0,0,0,255,0,0,0,0,0,0,0,
};

// -----------------------------------------------------------------------
// Pattern: SMILEY — happy face
// -----------------------------------------------------------------------
static const uint8_t PATTERN_SMILEY[MATRIX_SIZE] PROGMEM = {
    0,0,0,255,255,255,255,255,255,0,0,0,0,
    0,0,255,0,0,0,0,0,0,255,0,0,0,
    0,255,0,0,0,0,0,0,0,0,255,0,0,
    0,255,0,255,0,0,0,255,0,0,255,0,0,
    0,255,0,0,0,0,0,0,0,0,255,0,0,
    0,255,0,255,255,255,255,255,0,0,255,0,0,
    0,0,255,0,0,0,0,0,0,255,0,0,0,
    0,0,0,255,255,255,255,255,255,0,0,0,0,
};

// -----------------------------------------------------------------------
// Pattern: HEART
// -----------------------------------------------------------------------
static const uint8_t PATTERN_HEART[MATRIX_SIZE] PROGMEM = {
    0,0,255,0,0,0,0,0,255,0,0,0,0,
    0,255,255,255,0,0,0,255,255,255,0,0,0,
    0,255,255,255,255,255,255,255,255,255,0,0,0,
    0,255,255,255,255,255,255,255,255,255,0,0,0,
    0,0,255,255,255,255,255,255,255,0,0,0,0,
    0,0,0,255,255,255,255,255,0,0,0,0,0,
    0,0,0,0,255,255,255,0,0,0,0,0,0,
    0,0,0,0,0,255,0,0,0,0,0,0,0,
};

// -----------------------------------------------------------------------
// Pattern: CROSS — X mark (two diagonals crossing at center)
// -----------------------------------------------------------------------
// Diagonal 1: top-left (0,0) → bottom-right (7,7)
// Diagonal 2: top-right (0,12) → bottom-left (7,5)
// They cross at row 6, col 6.
static const uint8_t PATTERN_CROSS[MATRIX_SIZE] PROGMEM = {
    255,0,0,0,0,0,0,0,0,0,0,0,255,
    0,255,0,0,0,0,0,0,0,0,0,255,0,
    0,0,255,0,0,0,0,0,0,0,255,0,0,
    0,0,0,255,0,0,0,0,0,255,0,0,0,
    0,0,0,0,255,0,0,0,255,0,0,0,0,
    0,0,0,0,0,255,0,255,0,0,0,0,0,
    0,0,0,0,0,0,255,0,0,0,0,0,0,
    0,0,0,0,0,255,0,255,0,0,0,0,0,
};

// -----------------------------------------------------------------------
// Pattern: CLEAR — all pixels off
// -----------------------------------------------------------------------
static const uint8_t PATTERN_CLEAR[MATRIX_SIZE] PROGMEM = { 0 };

// -----------------------------------------------------------------------
// Animation: WALKER — 4-frame walking stick figure
// -----------------------------------------------------------------------
// A simple walk cycle: right stride → stand → left stride → stand
// Figure position: head at (0,6), shoulders (1,5-7), body (2-5,6),
// legs at rows 6-7.
// -----------------------------------------------------------------------
static const uint8_t ANIM_WALKER[4][MATRIX_SIZE] PROGMEM = {
    // Frame 0: right leg forward, arms swinging
    {
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,255,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,255,0,0,0,0,0,255,0,0,0,
        0,0,255,0,0,0,0,0,0,0,255,0,0,
    },
    // Frame 1: standing
    {
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,255,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
    },
    // Frame 2: left leg forward, arms swinging (mirror of frame 0)
    {
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,255,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,0,0,0,0,0,255,0,
        0,0,0,0,255,0,0,0,0,0,255,0,0,
    },
    // Frame 3: standing (same as frame 1)
    {
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,255,255,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,0,255,0,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
        0,0,0,0,0,255,0,255,0,0,0,0,0,
    },
};

// Named animation registry
struct AnimEntry {
    const char* name;
    const uint8_t* frames;  // PROGMEM pointer to first frame
    uint8_t frame_count;
    uint16_t frame_delay_ms;
};

static const AnimEntry ANIMATIONS[] PROGMEM = {
    {"walker", (const uint8_t*)ANIM_WALKER, 4, 200},
};

#define ANIM_COUNT (sizeof(ANIMATIONS) / sizeof(ANIMATIONS[0]))

// Look up an animation by name; returns AnimEntry pointer or nullptr if not found.
inline const AnimEntry* anim_lookup(const char* name) {
    for (size_t i = 0; i < ANIM_COUNT; i++) {
        if (strcmp(ANIMATIONS[i].name, name) == 0) {
            return &ANIMATIONS[i];
        }
    }
    return nullptr;
}

// -----------------------------------------------------------------------
// Named pattern registry
// -----------------------------------------------------------------------
struct PatternEntry {
    const char* name;
    const uint8_t* data;  // PROGMEM pointer
};

static const PatternEntry PATTERNS[] PROGMEM = {
    {"warning", (const uint8_t*)PATTERN_WARNING},
    {"smiley",  (const uint8_t*)PATTERN_SMILEY},
    {"heart",   (const uint8_t*)PATTERN_HEART},
    {"cross",   (const uint8_t*)PATTERN_CROSS},
    {"clear",   (const uint8_t*)PATTERN_CLEAR},
};

#define PATTERN_COUNT (sizeof(PATTERNS) / sizeof(PATTERNS[0]))

// Look up a pattern by name; returns PROGMEM data pointer or nullptr if not found.
inline const uint8_t* pattern_lookup(const char* name) {
    for (size_t i = 0; i < PATTERN_COUNT; i++) {
        // NOTE: PatternEntry.name is in RAM (string literal), safe for strcmp
        if (strcmp(PATTERNS[i].name, name) == 0) {
            return PATTERNS[i].data;
        }
    }
    return nullptr;
}

#endif // MATRIX_PATTERNS_H
