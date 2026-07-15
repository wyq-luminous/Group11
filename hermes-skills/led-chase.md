# LED Chase / Running Light Effect (流水灯)

## When to use
- User says "流水灯", "跑马灯", "LED流水", "chase effect", "running lights"
- User says "彩虹灯", "rainbow lights", "彩色灯"
- User says "呼吸灯", "breathe effect", "fade lights"
- User wants a dynamic color-changing LED effect across all LEDs

## Available modes
| Mode    | Effect                                   |
|---------|------------------------------------------|
| chase   | LEDs light up in sequence (wave/flowing) |
| rainbow | All LEDs same color, cycling through rainbow |
| breathe | All LEDs fade in/out together (warm glow) |

## Commands

### Start chase (流水灯 / running lights)
```
/home/arduino/ArduinoApps/ws6/bin/led_chase.sh
```
Or with options:
```
/home/arduino/ArduinoApps/ws6/bin/led_chase.sh --mode chase --speed 0.15
```

### Start rainbow (彩虹灯)
```
/home/arduino/ArduinoApps/ws6/bin/led_chase.sh --mode rainbow --speed 0.1
```

### Start breathe (呼吸灯)
```
/home/arduino/ArduinoApps/ws6/bin/led_chase.sh --mode breathe --speed 0.05
```

### Stop the effect
```
kill $(pgrep -f led_chase)
```
Then turn off all LEDs:
```
for i in 1 2 3 4; do /home/arduino/ArduinoApps/ws6/bin/led_control.sh set $i off; done
```

## What to do
1. Identify which mode the user wants.
2. Run the appropriate command in the BACKGROUND (add `&` at end).
3. Tell the user the effect is running and how to stop it.
4. IMPORTANT: Run it in background so Hermes can continue responding.

## Examples
- User: "开始流水灯"
  → Run: `nohup /home/arduino/ArduinoApps/ws6/bin/led_chase.sh --mode chase > /tmp/led_chase.log 2>&1 &`
  → Reply: "流水灯已启动（chase 模式）。要停止时说「停止流水灯」。"

- User: "彩虹灯"
  → Run: `nohup /home/arduino/ArduinoApps/ws6/bin/led_chase.sh --mode rainbow > /tmp/led_chase.log 2>&1 &`
  → Reply: "彩虹灯已启动。"

- User: "停止流水灯"
  → Run: `kill $(pgrep -f led_chase)` then turn off LEDs

## Notes
- This controls ALL 4 LEDs (LED1-LED4).
- LED1/LED2 have smooth PWM colors, LED3/LED4 have 8 basic colors.
- The effect runs until stopped or the board is powered off.
- Do NOT try to control LEDs directly — always use these scripts.
