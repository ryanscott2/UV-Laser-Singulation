"""Prior OptiScan III / ProScan III stage driver + interactive teach tool.

This is the motion half of the one-button dicing automation: the OptiScan III
moves the wafer (on the fixed jig) under the fixed galvo field, so stage position
i lines up with WinLase job i. This module talks to the controller over its serial
port and gives you a safe way to (1) confirm comms, and (2) jog to and record the
four station positions the dicing script will replay.

NO LASER, NO WINLASE here -- this only moves the stage and reads it back. Bring the
laser in only after the taught positions are verified.

Command set (verified against the Prior OptiScan III manual v1.3 and the ProScan III
manual, which share the command structure). 9600 baud 8-N-1, each command ends in a
carriage return; the controller answers on one line (multi-line replies end in END):
    G,x,y[,z]   absolute move (microns; Z in 100 nm steps)      -> R
    GR,x,y[,z]  relative move                                   -> R
    GX,x GY,y GZ,z  single-axis absolute                        -> R
    PS / P,x,y,z   report / set stage position (microns)
    PZ / PZ,z      report / set focus position
    $           status: 0 = idle, nonzero = an axis is moving
    I           controlled stop (empties the queue)  K  hard stop
    M           move stage + focus to 0,0,0
    SIS         set index: DRIVES TO THE HARD LIMITS, then zeroes  (install-only)
    RIS         restore index: also drives to the limits
    COMP,0      Standard mode (recommended): R returns immediately, poll $

Runs on Python 3.8, no network. Serial goes through pyserial if present, else
pywin32 (win32file); one of those must be installed on the laser PC.

    python tools/optiscan.py info                 # comms + who's connected + position
    python tools/optiscan.py jog                  # interactive jog; record P1..P4
    python tools/optiscan.py goto --x 25400 --y -25400
    python tools/optiscan.py home                 # M -> 0,0,0 (asks first)

Safety: `goto`/`home` ask before moving. Nothing homes to the limits unless you run
`index`/`restore` explicitly -- on this rig a drive-to-limits could crash the jig or
the lens, so treat those as deliberate, watched operations.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_PORT = "COM5"
BAUD = 9600
CR = b"\r"
MOVE_TIMEOUT_S = 30.0
POLL_S = 0.05
STATION_KEYS = ("P1", "P2", "P3", "P4")

# ES111 stage travel (from the controller's STAGE report: X = 126 mm, Y = 76 mm).
# Coarse software soft-limit: any target whose |x| or |y| exceeds the travel is a
# typo/runaway and is refused before it reaches the controller. The hardware limit
# switches remain the physical backstop.
TRAVEL_X_UM = 126_000
TRAVEL_Y_UM = 76_000
# After a move, PS must land within this of the target or we raise. A silently
# rejected move leaves the stage put (tens of mm off), which this catches before
# anything downstream (e.g. a laser mark) trusts the position.
POSITION_TOLERANCE_UM = 1_000
# Ceiling for the interactive jog step, well under full travel.
MAX_JOG_STEP_UM = 20_000


# --------------------------------------------------------------------------- serial
class _Serial:
    """Minimal CR-terminated serial transport: pyserial first, else pywin32."""

    def __init__(self, port: str, baud: int, read_timeout_s: float = 2.0):
        self.backend = None
        try:
            import serial  # pyserial
            self._ser = serial.Serial(port, baud, timeout=read_timeout_s,
                                      bytesize=8, parity="N", stopbits=1)
            self.backend = "pyserial"
        except ImportError:
            self._open_win32(port, baud, read_timeout_s)
            self.backend = "pywin32"

    def _open_win32(self, port: str, baud: int, read_timeout_s: float) -> None:
        try:
            import win32file
            import win32con
        except ImportError as exc:
            raise SystemExit(
                "Need pyserial or pywin32 to open the serial port, and neither is "
                "installed. On an offline PC, copy a matching wheel over and "
                "`pip install pyserial` (preferred)."
            ) from exc
        self._win32file = win32file
        name = port if port.upper().startswith("\\\\.\\") else r"\\.\%s" % port
        self._h = win32file.CreateFile(
            name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None,
            win32con.OPEN_EXISTING, 0, None)
        dcb = win32file.GetCommState(self._h)
        dcb.BaudRate, dcb.ByteSize, dcb.Parity, dcb.StopBits = (
            baud, 8, win32file.NOPARITY, win32file.ONESTOPBIT)
        win32file.SetCommState(self._h, dcb)
        ms = int(read_timeout_s * 1000)
        # (interval, read-mult, read-const, write-mult, write-const)
        win32file.SetCommTimeouts(self._h, (ms, 0, ms, 0, 1000))

    def write(self, data: bytes) -> None:
        if self.backend == "pyserial":
            self._ser.write(data)
        else:
            self._win32file.WriteFile(self._h, data)

    def reset_input(self) -> None:
        """Discard any unread bytes so the next reply is read fresh.

        Multi-resource commands (M, or G,x,y,z) send back more than one response;
        reading only one leaves the extra in the buffer and shifts every following
        read by a slot (the desync that made PS parse as a single value). Flushing
        before each command starts every exchange clean.
        """
        try:
            if self.backend == "pyserial":
                self._ser.reset_input_buffer()
            else:
                self._win32file.PurgeComm(self._h, 0x0008)  # PURGE_RXCLEAR
        except Exception:
            pass

    def read_line(self) -> str:
        """Read one CR-terminated line (LF ignored). '' on timeout."""
        out = bytearray()
        if self.backend == "pyserial":
            while True:
                b = self._ser.read(1)
                if not b:
                    break
                if b in (CR, b"\n"):
                    if out:
                        break
                    continue
                out += b
        else:
            while True:
                _, b = self._win32file.ReadFile(self._h, 1)
                if not b:
                    break
                if b in (CR, b"\n"):
                    if out:
                        break
                    continue
                out += b
        return out.decode("ascii", "replace").strip()

    def close(self) -> None:
        try:
            if self.backend == "pyserial":
                self._ser.close()
            else:
                self._win32file.CloseHandle(self._h)
        except Exception:
            pass


# ---------------------------------------------------------------------- controller
class OptiScan:
    def __init__(self, port: str = DEFAULT_PORT, baud: int = BAUD):
        self.port = port
        self.io = _Serial(port, baud)
        # Standard mode (poll $), and machine-readable errors ('E,n') so command()
        # can reliably detect a rejected command. Confirm the link is really talking.
        self.command("COMP,0")
        self.command("ERROR,0")
        who = self.command("DATE")
        if not who:
            raise SystemExit(
                "No reply from %s. Check the COM number (Device Manager > Ports), that "
                "the WinLase/Prior software isn't holding the port, and the cable." % port)
        self.identity = who

    def command(self, cmd: str, multiline: bool = False, expect: str = None) -> str:
        """Send one command and return the reply.

        Raises on a controller error reply. With ERROR,0 an error is 'E,<code>'
        (the controller uses comma/space/tab delimiters), so the leading token is
        tested, not a substring. If `expect` is given (e.g. 'R' for a move, '0'
        for a set command) the reply must equal it exactly -- so a move the
        controller silently rejects can never be read as a completed move.
        """
        self.io.reset_input()  # each command starts on a clean buffer (see reset_input)
        self.io.write(cmd.encode("ascii") + CR)
        if multiline:
            lines = []
            while True:
                line = self.io.read_line()
                if line == "" or line.upper() == "END":
                    break
                lines.append(line)
            return "\n".join(lines)
        reply = self.io.read_line()
        head = reply.split(",", 1)[0].strip().upper()
        if head == "E" or head == "ERROR" or (head[:1] == "E" and head[1:].lstrip("-").isdigit()):
            raise RuntimeError("OptiScan error for %r: %r" % (cmd, reply))
        if expect is not None and reply != expect:
            raise RuntimeError("OptiScan %r: expected %r, got %r" % (cmd, expect, reply))
        return reply

    # -- reads --------------------------------------------------------------------
    def _read_xy(self, query: str):
        """Read an 'x,y' reply as two ints, with one retry on a malformed line.
        The query (PS) only reports position, so retrying it moves nothing."""
        resp = ""
        for attempt in range(2):
            resp = self.command(query)
            parts = resp.split(",")
            if len(parts) == 2:
                try:
                    return int(round(float(parts[0]))), int(round(float(parts[1])))
                except ValueError:
                    pass
            if attempt == 0:
                time.sleep(POLL_S)
        raise RuntimeError("unexpected %s reply from stage: %r" % (query, resp))

    def stage_position(self):
        return self._read_xy("PS")

    def z_position(self) -> int:
        return int(round(float(self.command("PZ"))))

    def _motion_status(self):
        """$ motion word as an int (0 = idle), or None if the reply didn't parse."""
        resp = self.command("$")
        try:
            return int(resp.split(",")[0])
        except ValueError:
            return None

    def stage_info(self) -> str:
        return self.command("STAGE", multiline=True)

    # -- motion (all guarded by wait_idle) ----------------------------------------
    def wait_idle(self, timeout_s: float = MOVE_TIMEOUT_S) -> None:
        """Block until $ confirms idle (0). Only a confirmed 0 exits -- an
        unreadable status keeps polling, so we never assume idle by mistake and
        move on while the stage is still travelling."""
        deadline = time.time() + timeout_s
        try:
            while True:
                if self._motion_status() == 0:
                    return
                if time.time() > deadline:
                    self.command("I")  # controlled stop
                    raise TimeoutError("move did not finish within %.0fs; stopped" % timeout_s)
                time.sleep(POLL_S)
        except KeyboardInterrupt:
            self.command("I")
            raise

    def _check_target(self, x: float, y: float) -> None:
        """Refuse a stage target outside the travel envelope (a typo/runaway)."""
        if abs(x) > TRAVEL_X_UM or abs(y) > TRAVEL_Y_UM:
            raise ValueError(
                "target X=%d Y=%d um is outside the +/-%d x +/-%d um travel; refusing to move"
                % (int(x), int(y), TRAVEL_X_UM, TRAVEL_Y_UM))

    def _verify_at(self, x: float, y: float, tol_um: int = POSITION_TOLERANCE_UM) -> None:
        """Confirm PS landed on the target; catches a silently rejected move."""
        ax, ay = self.stage_position()
        if abs(ax - x) > tol_um or abs(ay - y) > tol_um:
            raise RuntimeError(
                "stage did not reach target: wanted X=%d Y=%d, at X=%d Y=%d (tol %d um)"
                % (int(x), int(y), ax, ay, tol_um))

    def goto(self, x: int, y: int, wait: bool = True, verify: bool = True) -> None:
        self._check_target(x, y)
        self.command("G,%d,%d" % (int(x), int(y)), expect="R")
        if wait:
            self.wait_idle()
            if verify:
                self._verify_at(x, y)

    def goto_z(self, z: int, wait: bool = True) -> None:
        self.command("GZ,%d" % int(z), expect="R")
        if wait:
            self.wait_idle()

    def move_rel(self, dx: int, dy: int, wait: bool = True) -> None:
        cx, cy = self.stage_position()
        self._check_target(cx + dx, cy + dy)
        self.command("GR,%d,%d" % (int(dx), int(dy)), expect="R")
        if wait:
            self.wait_idle()

    def move_rel_z(self, dz: int, wait: bool = True) -> None:
        self.command("GR,0,0,%d" % int(dz), expect="R")
        if wait:
            self.wait_idle()

    def stop(self) -> None:
        # Best-effort controlled stop; do not gate on the ack (must not throw mid-abort).
        self.command("I")

    def close(self) -> None:
        self.io.close()


# ---------------------------------------------------------------------------- CLI
def _connect(args) -> OptiScan:
    dev = OptiScan(args.port)
    print("connected on %s via %s: %s" % (dev.port, dev.io.backend, dev.identity))
    return dev


def cmd_info(args) -> int:
    dev = _connect(args)
    try:
        print("\n" + dev.stage_info())
        try:
            print("FOCUS:\n" + dev.command("FOCUS", multiline=True))
        except Exception:
            pass
        x, y = dev.stage_position()
        print("\nstage position: X=%d  Y=%d  microns" % (x, y))
        try:
            print("focus position: Z=%d" % dev.z_position())
        except Exception:
            pass
    finally:
        dev.close()
    return 0


def cmd_goto(args) -> int:
    dev = _connect(args)
    try:
        x, y = dev.stage_position()
        print("at X=%d Y=%d; moving to X=%d Y=%d" % (x, y, args.x, args.y))
        if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
            print("cancelled")
            return 1
        dev.goto(args.x, args.y)
        x, y = dev.stage_position()
        print("arrived X=%d Y=%d" % (x, y))
    finally:
        dev.close()
    return 0


def cmd_home(args) -> int:
    dev = _connect(args)
    try:
        print("Home: moves the STAGE to 0,0 (focus is manual on this unit and is left alone).")
        if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
            print("cancelled")
            return 1
        dev.goto(0, 0)  # G,0,0 -- stage only; avoids the 2-resource M command
        x, y = dev.stage_position()
        print("home X=%d Y=%d" % (x, y))
    finally:
        dev.close()
    return 0


def cmd_index(args) -> int:
    dev = _connect(args)
    try:
        word = "RIS (restore index)" if args.restore else "SIS (set index)"
        print("!! %s DRIVES THE STAGE TO ITS HARD LIMITS." % word)
        print("!! Make sure the jig, wafer, and lens cannot collide over full travel.")
        if input('type "LIMITS" to proceed: ').strip() != "LIMITS":
            print("cancelled")
            return 1
        dev.command("RIS" if args.restore else "SIS")
        dev.wait_idle(timeout_s=120.0)
        x, y = dev.stage_position()
        print("done; position now X=%d Y=%d" % (x, y))
    finally:
        dev.close()
    return 0


def cmd_jog(args) -> int:
    try:
        import msvcrt
    except ImportError:
        raise SystemExit("jog needs Windows (msvcrt); use `goto` elsewhere.")
    dev = _connect(args)
    step = args.step
    positions = {}
    out_path = Path(args.out)
    print(
        "\nJOG  (small, watched moves -- keep a hand on the controller)\n"
        "  a/d = -X/+X   s/w = -Y/+Y   f/r = focus -/+\n"
        "  [ / ] = smaller/larger step        p = print position\n"
        "  1 2 3 4 = record current point as P1..P4\n"
        "  g = go to typed X Y                q = save + quit   Esc = quit no save\n"
    )
    try:
        while True:
            x, y = dev.stage_position()
            sys.stdout.write("\rX=%-8d Y=%-8d  step=%-6d  recorded=%s        "
                             % (x, y, step, ",".join(sorted(positions)) or "-"))
            sys.stdout.flush()
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):      # arrow prefix -> map to a/d/w/s
                ch2 = msvcrt.getch()
                ch = {b"K": b"a", b"M": b"d", b"H": b"w", b"P": b"s"}.get(ch2, b"")
            key = ch.decode("ascii", "ignore").lower()
            if key == "q":
                break
            if ch == b"\x1b":                 # Esc
                print("\nquit without saving")
                return 0
            if key == "d":
                dev.move_rel(step, 0)
            elif key == "a":
                dev.move_rel(-step, 0)
            elif key == "w":
                dev.move_rel(0, step)
            elif key == "s":
                dev.move_rel(0, -step)
            elif key == "r":
                dev.move_rel_z(step)
            elif key == "f":
                dev.move_rel_z(-step)
            elif key == "]":
                step = min(step * 2, MAX_JOG_STEP_UM)
            elif key == "[":
                step = max(step // 2, 1)
            elif key == "p":
                z = None
                try:
                    z = dev.z_position()
                except Exception:
                    pass
                print("\n  X=%d Y=%d%s" % (x, y, "" if z is None else " Z=%d" % z))
            elif key in ("1", "2", "3", "4"):
                label = "P" + key
                rec = {"x": x, "y": y}
                try:
                    rec["z"] = dev.z_position()
                except Exception:
                    pass
                positions[label] = rec
                print("\n  recorded %s = %s" % (label, rec))
            elif key == "g":
                try:
                    tx = int(input("\n  target X (um): "))
                    ty = int(input("  target Y (um): "))
                except ValueError:
                    print("  bad number")
                    continue
                if input("  go to X=%d Y=%d? [y/N] " % (tx, ty)).strip().lower() == "y":
                    dev.goto(tx, ty)
    finally:
        dev.close()

    if positions:
        data = {"port": args.port, "units": "microns", "stations": positions,
                "note": "recorded with tools/optiscan.py jog"}
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("\nwrote %d point(s) to %s" % (len(positions), out_path))
        missing = [k for k in STATION_KEYS if k not in positions]
        if missing:
            print("still to record: %s" % ", ".join(missing))
    else:
        print("\nno points recorded")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", default=DEFAULT_PORT, help="serial port (default COM5)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="connect, print controller + stage info + position")

    j = sub.add_parser("jog", help="interactive jog and record P1..P4")
    j.add_argument("--step", type=int, default=1000, help="initial jog step in microns")
    j.add_argument("--out", default=str(Path(__file__).resolve().parent / "optiscan_positions.json"),
                   help="where to save recorded points")

    g = sub.add_parser("goto", help="move to an absolute X,Y (microns)")
    g.add_argument("--x", type=int, required=True)
    g.add_argument("--y", type=int, required=True)
    g.add_argument("--yes", action="store_true", help="skip the confirm prompt")

    h = sub.add_parser("home", help="M: move stage+focus to 0,0,0")
    h.add_argument("--yes", action="store_true")

    ix = sub.add_parser("index", help="SIS/RIS: drive to limits to (re)establish origin")
    ix.add_argument("--restore", action="store_true", help="RIS instead of SIS")

    args = p.parse_args()
    handlers = {"info": cmd_info, "jog": cmd_jog, "goto": cmd_goto,
                "home": cmd_home, "index": cmd_index}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
