#!/usr/bin/env python3
"""
Read-only status query for the Liene PixCut S1 over its Bluetooth SPP serial port.
Sends ONE harmless `get-prop` command (printer state) and prints whatever the
device replies. It does NOT create any print/cut job — nothing is printed.

Validates that our hand-built ATT framing ("cmd json\\n" + JSON) is accepted by
real hardware, and reveals the device's response frame format.

PREREQS before running:
  - Quit the official "Liene Photo" app (it holds the Bluetooth channel).
  - Be at the machine with the printer powered on and connected.

Usage:  python3 status_query.py
"""
import os
import sys
import time
import select
import termios

PORT = "/dev/cu.JiyinPixCutS1-9CD0"

# One get-prop bundling every read-only property we care about. The reply gives
# us the printer state AND the integer enum values for media-size / media-type
# that the print-job command needs. (Verbs/props taken verbatim from the
# RawProtocolManager builders; ATT control frame = "cmd json\n" + JSON.)
JSON = (
    b'{"method":"get-prop","params":['
    b'"printer-state","printer-sub-state","printer-state-alerts",'
    b'"media-size","media-type","device-info","firmware-version"'
    b'],"id":1}'
)
FRAME = b"cmd json\n" + JSON

READ_SECONDS = 5.0


def hexdump(data: bytes) -> None:
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        if len(chunk) > 8:
            hexs = hexs[:23] + " " + hexs[23:]
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {i:04x}  {hexs:<48}  |{ascii_}|")


def main() -> int:
    if not os.path.exists(PORT):
        print(f"ERROR: {PORT} not found. Is the printer connected over Bluetooth?")
        return 1

    print(f"Opening {PORT} ...")
    try:
        # Blocking open; cu devices don't block on carrier, so this returns at
        # once and the RFCOMM link is brought up asynchronously by the BT stack.
        fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
    except OSError as e:
        print(f"ERROR: open failed: {e}")
        print("If 'Resource busy', quit the official Liene Photo app first.")
        return 1

    try:
        # Put the tty in raw mode (BT SPP ignores baud, but raw avoids cooking).
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0           # iflag
        attrs[1] = 0           # oflag
        attrs[3] = 0           # lflag (no echo/canonical/signals)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        # The printer link drops when the official app quits. Opening the port
        # re-initiates the RFCOMM connection, but that takes a couple seconds —
        # writing before it's up silently drops the bytes (the bug last time).
        SETTLE = 3.0
        print(f"Waiting {SETTLE:.0f}s for the Bluetooth RFCOMM link to come up ...")
        time.sleep(SETTLE)
        try:
            termios.tcflush(fd, termios.TCIOFLUSH)  # drop any stale bytes
        except Exception:
            pass

        os.set_blocking(fd, False)
        print(f"Sending {len(FRAME)} bytes:")
        hexdump(FRAME)
        os.write(fd, FRAME)

        TOTAL = 12.0
        print(f"\nWaiting up to {TOTAL:.0f}s for a reply (will resend once at 5s) ...")
        buf = bytearray()
        start = time.monotonic()
        deadline = start + TOTAL
        resent = False
        while time.monotonic() < deadline:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    chunk = b""
                if chunk:
                    buf += chunk
                    deadline = time.monotonic() + 2.0  # extend after each chunk
            # If nothing came back in the first 5s, the link may have only just
            # finished establishing — resend the query once.
            if not resent and not buf and time.monotonic() - start > 5.0:
                print("  (no reply yet — resending the query once)")
                try:
                    os.write(fd, FRAME)
                except OSError as e:
                    print(f"  resend failed: {e}")
                resent = True

        print()
        if buf:
            print(f"RECEIVED {len(buf)} bytes:")
            hexdump(bytes(buf))
            try:
                print("\nas text:\n" + buf.decode("utf-8", "replace"))
            except Exception:
                pass
            print("\n=> FRAMING VALIDATED: the device accepted our hand-built frame.")
        else:
            print("No reply within timeout.")
            print("Possible causes: app still holding the channel, device asleep,")
            print("or the response comes on a different RFCOMM channel than the cu port.")
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
