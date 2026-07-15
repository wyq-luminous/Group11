# Show Animation on LED Matrix

## When to use
- User says "play animation", "show animation", "start animation", "播放动画", "矩阵动画"
- User wants to see a looping animation on the LED matrix (NOT LED chase — see led-chase skill)

## Available animations
| Name   | Description                    | Frames | Speed |
|--------|--------------------------------|--------|-------|
| walker | Walking stick figure (4-frame) | 4      | 200ms |

## What to do
1. Run:
   ```
   /home/arduino/ArduinoApps/ws6/bin/matrix_animation.sh <name>
   ```
2. Relay the result.

## Example
- User: "Play the walker animation" / "播放动画"
- Run: `/home/arduino/ArduinoApps/ws6/bin/matrix_animation.sh walker`
- Reply: "Walker animation started on the matrix."

## Notes
- Animations loop continuously until stopped by scroll text, pattern, or clear.
- Do NOT try to control the matrix directly — always use the script.
