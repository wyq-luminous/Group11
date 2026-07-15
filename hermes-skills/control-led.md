# Control Board LEDs

## When to use
- User says "turn on LED X", "turn off LED X", "blink LED X"
- User says "set LED X to red/blue/green/white", "LED X color"
- User says "LED亮度", "开关灯", "闪烁"
- User asks "what LEDs are available", "list LEDs"

## LED Inventory
| LED  | Side   | Type | Notes                        |
|------|--------|------|------------------------------|
| LED1 | Linux  | RGB  | User LED, full control       |
| LED2 | Linux  | RGB  | Shared with system indicators |
| LED3 | STM32  | RGB  | Via RPC, full control        |
| LED4 | STM32  | RGB  | Via RPC, full control        |

All LEDs are active-low (0 = full brightness, 255 = off), but the scripts handle this automatically.

## Commands

### Set LED state (on/off/blink)
```
/home/arduino/ArduinoApps/ws6/bin/led_control.sh set <index> <on|off|blink>
```

### Set LED RGB color
```
/home/arduino/ArduinoApps/ws6/bin/led_control.sh rgb <index> <r> <g> <b>
```
r, g, b are 0-255 each. Example: `rgb 3 255 0 0` = red.

### List all LEDs
```
/home/arduino/ArduinoApps/ws6/bin/led_control.sh list
```

## What to do
1. Determine what the user wants: on/off/blink or specific color.
2. If they say a color name, map to RGB:
   - red → (255, 0, 0)
   - green → (0, 255, 0)
   - blue → (0, 0, 255)
   - white → (255, 255, 255)
   - yellow → (255, 255, 0)
   - cyan → (0, 255, 255)
   - magenta → (255, 0, 255)
   - orange → (255, 128, 0)
3. Run the appropriate command.
4. Relay the result.

## Examples
- User: "Turn on LED 3"
  → Run: `/home/arduino/ArduinoApps/ws6/bin/led_control.sh set 3 on`
  → Reply: "LED3 is now on."

- User: "Make LED 1 blink"
  → Run: `/home/arduino/ArduinoApps/ws6/bin/led_control.sh set 1 blink`
  → Reply: "LED1 is now blinking."

- User: "Set LED 4 to blue"
  → Run: `/home/arduino/ArduinoApps/ws6/bin/led_control.sh rgb 4 0 0 255`
  → Reply: "LED4 set to blue (RGB 0,0,255)."

## Notes
- LED2 shares pins with system status indicators — colors may be overridden by the system.
- Blink on LED1/LED2 uses sysfs timer trigger (may conflict with other triggers).
- Do NOT try to write to /sys/class/leds/ directly — always use the script.
