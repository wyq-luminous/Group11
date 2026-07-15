# Show Pattern on LED Matrix

## When to use
- User says "show warning", "display smiley", "show heart", "display cross", "clear matrix"
- User says "显示警告", "显示笑脸", "显示爱心", "清屏"
- User wants to stop scrolling text and show a static icon

## Available patterns
| Name    | Description                  |
|---------|------------------------------|
| warning | Exclamation mark in triangle |
| smiley  | Happy face                   |
| heart   | Heart shape                  |
| cross   | X mark                       |
| clear   | All pixels off (blank)       |

## What to do
1. Identify which pattern the user wants from the table above.
2. Run the pattern script:
   ```
   /home/arduino/ArduinoApps/ws6/bin/matrix_pattern.sh <pattern_name>
   ```
3. Relay the script output.

## Example
- User: "Show a warning on the matrix"
- Run: `/home/arduino/ArduinoApps/ws6/bin/matrix_pattern.sh warning`
- Reply: "Matrix now showing warning pattern."

- User: "Clear the screen"
- Run: `/home/arduino/ArduinoApps/ws6/bin/matrix_pattern.sh clear`
- Reply: "Matrix cleared."

## Notes
- Showing a pattern stops any active text scroll.
- If the user asks for a pattern not in the list, suggest the closest match.
- Do NOT try to control the matrix directly — always use the script.
