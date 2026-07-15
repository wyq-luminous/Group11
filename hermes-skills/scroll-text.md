# Scroll Text on LED Matrix

## When to use
- User says "scroll X on the matrix", "display X", "show text X", "滚动显示 X"
- User wants to change the scrolling message
- User says "matrix show X", "LED matrix X"

## What to do
1. Run the scroll text script:
   ```
   /home/arduino/ArduinoApps/ws6/bin/matrix_scroll.sh "<text>"
   ```
2. Replace `<text>` with the user's requested text.
3. If the text is very long (>120 chars), the script will auto-truncate.
4. Relay the script output to the user (confirmation or error).

## Example
- User: "Scroll 'UNO-Q Online' on the matrix"
- Run: `/home/arduino/ArduinoApps/ws6/bin/matrix_scroll.sh "UNO-Q Online"`
- Reply: "Matrix is now scrolling 'UNO-Q Online'."

## Notes
- The scroll loops continuously until cleared or replaced.
- Only ASCII printable characters are supported.
- To stop scrolling, tell the user to use "show pattern clear" or "clear matrix".
- Do NOT try to control the matrix directly — always use the script.
