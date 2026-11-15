"""Front-panel lamp sampler for the PiDP-11 add-on. READ-ONLY.

Reads the GPIO level register the PiDP-11 panel daemon drives and rebuilds the
time-multiplexed LED matrix: for each lamp, the percentage of usable samples in
which the lamp was lit. Works while the emulated CPU runs, which the SimH
EXAMINE-based lamp stream cannot do.

Mapping source and hardware status: docs/contracts/remote-console.md (LAMPS2
section). The mapping is taken from the upstream source; the lamps checked on a
Pi 5 are listed there, and the rest is provisional.

Safety: the device is opened ``O_RDONLY`` and mapped ``PROT_READ``. Nothing here
writes to the device, configures a pin, or calls ioctl.

CPU budget. A sample burst reads the register back to back for ``burst_ms`` and
then sleeps until the next frame. The sampling share of one core is therefore
``burst_ms * fps / 1000``, which is 4 % at the defaults (4 ms, 10 fps). Decoding
a burst adds a little on top: it runs once per burst over the distinct register
values seen, not once per sample. Measured on a development machine with a fake
register reader: 4.2 % of one core at 10 fps. Not measured on the Pi.
"""

from __future__ import annotations

import asyncio
import mmap
import os
import struct
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Mapping

DEFAULT_DEVICE = "/dev/gpiomem0"
RP1_WINDOW_LEN = 0x30000          # gpiochip_rp1.c: DECLARE_GPIO_CHIP(rp1, ..., 0x30000, 0)
FALLBACK_WINDOW_LEN = 0x11000     # smallest page-aligned length covering offset 0x10008
SYNC_IN_OFFSET = 0x10000 + 0x08   # SYS_RIO bank 0 at 0x10000, SYNC_IN at +0x8

COL_PINS = [26, 27, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]  # gpio.c:78; bit k <-> COL_PINS[k]
LEDROW_PINS = [20, 21, 22, 23, 24, 25]                 # gpio.c:76; row i <-> LEDROW_PINS[i]

MIN_FPS = 5
MAX_FPS = 20
DEFAULT_FPS = 10
DEFAULT_BURST_MS = 4.0
# A lamp change smaller than this (percentage points) is not sent on a stream.
LAMP_CHANGE_POINTS = 2

# Lamp map: (ledstatus row, bit) -> name. main.c register_controls() in upstream.
# Names are the probe's names. The "UNVERIFIED" comments mark the parts still open.
def _build_led_map() -> dict[tuple[int, int], str]:
    m: dict[tuple[int, int], str] = {}

    def add(name: str, row: int, bit: int) -> None:
        m[(row, bit)] = name

    for b in range(12):
        add(f"ADDRESS{b}", 0, b)              # main.c:612
    for b in range(12, 22):
        add(f"ADDRESS{b}", 1, b - 12)         # main.c:615
    for b in range(12):
        add(f"DATA{b}", 3, b)                 # main.c:621
    for b in range(12, 16):
        add(f"DATA{b}", 4, b - 12)            # main.c:621
    add("PARITY_LOW", 4, 4)                   # main.c:625
    add("PARITY_HIGH", 4, 5)                  # main.c:624
    add("PAR_ERR", 2, 11)                     # main.c:626
    add("ADRS_ERR", 2, 10)                    # main.c:627
    add("RUN", 2, 9)                          # main.c:628
    add("PAUSE", 2, 8)                        # main.c:629
    add("MASTER", 2, 7)                       # main.c:630
    for b in range(3):
        add(f"MMR0_MODE_BIT{b}", 2, 4 + b)    # main.c:636 (UNVERIFIED value encoding)
    add("DATA_SPACE", 2, 3)                   # main.c:638
    add("ADDRESSING_16", 2, 2)                # main.c:639
    add("ADDRESSING_18", 2, 1)                # main.c:640
    add("ADDRESSING_22", 2, 0)                # main.c:641
    for name, row, bit in (
        ("ADDR_SEL_UD", 4, 6), ("ADDR_SEL_SD", 4, 7), ("ADDR_SEL_KD", 4, 8),
        ("ADDR_SEL_CPHY", 4, 9), ("ADDR_SEL_UI", 5, 5), ("ADDR_SEL_SI", 5, 6),
        ("ADDR_SEL_KI", 5, 7), ("ADDR_SEL_PPHY", 5, 8),
    ):
        add(name, row, bit)                   # gpiopattern.c comment (UNVERIFIED order)
    add("DATA_SEL_FB_LO0", 4, 10)             # main.c:660 (UNVERIFIED order)
    add("DATA_SEL_FB_LO1", 4, 11)
    add("DATA_SEL_FB_HI0", 5, 10)
    add("DATA_SEL_FB_HI1", 5, 11)
    return m


LED_MAP = _build_led_map()

# The mode aliases come from the two MMR0 mode bits that form the 2-bit code.
# ASSUMPTION, not verified on hardware: the high bit is MMR0_MODE_BIT2 (the lamp
# the operator verified as USER) and the low bit is MMR0_MODE_BIT1. Code 00 is
# KERNEL, 01 is SUPER, 11 is USER, and 10 matches no alias.
_MODE_ROW = 2
_MODE_HI_K = 4 + 2
_MODE_LO_K = 4 + 1
MODE_ALIASES = ("KERNEL", "SUPER", "USER")


class LampUnavailable(RuntimeError):
    """The panel device cannot be opened or mapped read-only. Callers fall back."""


class LampFeedFailed(RuntimeError):
    """The shared sampler stopped; the stream that waits on it should end."""


def clamp_fps(value: object, default: int = DEFAULT_FPS) -> int:
    """Clamp a frame rate to MIN_FPS..MAX_FPS. Non-numbers give ``default``."""
    try:
        fps = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default
    return max(MIN_FPS, min(MAX_FPS, fps))


def env_fps() -> int:
    """The LAMP_FPS environment setting, clamped; DEFAULT_FPS when unset or odd."""
    return clamp_fps(os.environ.get("LAMP_FPS"), DEFAULT_FPS)


def device_path() -> str:
    return os.environ.get("GPIO_DEVICE", DEFAULT_DEVICE)


def lamps_changed(prev: Mapping[str, int] | None, cur: Mapping[str, int]) -> bool:
    """True when a lamp moved by LAMP_CHANGE_POINTS or more since ``prev``."""
    if prev is None or prev.keys() != cur.keys():
        return True
    return any(abs(cur[k] - prev[k]) >= LAMP_CHANGE_POINTS for k in cur)


def open_readonly(path: str) -> mmap.mmap:
    """Map the RP1 GPIO window read-only. Raises LampUnavailable on any failure."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        raise LampUnavailable(f"cannot open {path} read-only: {exc}") from exc
    try:
        for length in (RP1_WINDOW_LEN, FALLBACK_WINDOW_LEN):
            try:
                return mmap.mmap(fd, length, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
            except (OSError, ValueError):
                continue
        raise LampUnavailable(f"cannot map {path} read-only")
    finally:
        os.close(fd)


def _pct(part: int, whole: int) -> int:
    return round(100.0 * part / whole) if whole else 0


def decode(counter: Mapping[int, int]) -> dict[str, int]:
    """Turn {raw register value: count} into {lamp name: percent on}.

    A sample is usable only when exactly one LED row pin is high. A lamp is lit
    in that sample when its column pin is LOW (gpio.c:190-193).
    """
    row_active = [0] * len(LEDROW_PINS)
    on = [[0] * len(COL_PINS) for _ in LEDROW_PINS]
    mode = [0, 0, 0, 0]  # usable samples of row _MODE_ROW by 2-bit mode code
    for value, n in counter.items():
        rows = [r for r, pin in enumerate(LEDROW_PINS) if ((value >> pin) & 1)]
        if len(rows) != 1:
            continue
        r = rows[0]
        row_active[r] += n
        lit = [not ((value >> pin) & 1) for pin in COL_PINS]
        for k, is_lit in enumerate(lit):
            if is_lit:
                on[r][k] += n
        if r == _MODE_ROW:
            code = (int(lit[_MODE_HI_K]) << 1) | int(lit[_MODE_LO_K])
            mode[code] += n

    out: dict[str, int] = {}
    for (r, k), name in LED_MAP.items():
        out[name] = _pct(on[r][k], row_active[r])
    whole = row_active[_MODE_ROW]
    out["KERNEL"] = _pct(mode[0], whole)
    out["SUPER"] = _pct(mode[1], whole)
    out["USER"] = _pct(mode[3], whole)
    return out


def _mmap_reader(mm: mmap.mmap) -> Callable[[], int]:
    unpack = struct.Struct("<I").unpack_from
    off = SYNC_IN_OFFSET

    def read() -> int:
        return unpack(mm, off)[0]

    return read


class LampSampler:
    """Samples the panel in short bursts and decodes them into lamp percentages.

    ``reader`` and ``clock`` exist for tests: a reader returns one raw 32-bit
    SYNC_IN value per call, and a clock returns seconds. Without them the
    sampler maps the real device read-only and uses ``time.perf_counter``.
    """

    def __init__(
        self,
        device: str | None = None,
        *,
        reader: Callable[[], int] | None = None,
        clock: Callable[[], float] | None = None,
        burst_ms: float = DEFAULT_BURST_MS,
        fps: int | None = None,
    ) -> None:
        self.fps = clamp_fps(fps, env_fps()) if fps is not None else env_fps()
        self.burst_s = burst_ms / 1000.0
        self._clock = clock or time.perf_counter
        self._mm: mmap.mmap | None = None
        if reader is None:
            self._mm = open_readonly(device or device_path())
            reader = _mmap_reader(self._mm)
        self._read: Callable[[], int] | None = reader

    @property
    def closed(self) -> bool:
        return self._read is None

    def close(self) -> None:
        self._read = None
        if self._mm is not None:
            self._mm.close()
            self._mm = None

    def sample(self) -> Counter[int]:
        """Read the register back to back for one burst; count the raw values."""
        if self._read is None:
            raise LampUnavailable("sampler is closed")
        counter: Counter[int] = Counter()
        read = self._read
        clock = self._clock
        end = clock() + self.burst_s
        while clock() < end:
            counter[read()] += 1
        return counter

    def frame(self) -> dict[str, int]:
        """One burst, decoded: {lamp name: percent on, 0..100}."""
        return decode(self.sample())

    async def frames(
        self, rate: Callable[[], int] | int | None = None
    ) -> AsyncIterator[dict[str, int]]:
        """Yield frames at the configured rate. ``rate`` may be a callable.

        The rate is read before each wait, so a caller that changes it takes
        effect on the next frame.
        """
        loop = asyncio.get_running_loop()
        if callable(rate):
            get_rate: Callable[[], int] = rate
        else:
            fixed = rate if rate is not None else self.fps
            get_rate = lambda: fixed
        while True:
            started = loop.time()
            yield self.frame()
            period = 1.0 / clamp_fps(get_rate(), self.fps)
            await asyncio.sleep(max(0.0, period - (loop.time() - started)))


class SharedLampFeed:
    """One LampSampler shared by every lamp client on the stream port.

    The sampler runs only while at least one client is subscribed, at the
    highest rate any subscriber asked for. The last unsubscribe closes it.
    """

    def __init__(self, open_sampler: Callable[[], LampSampler] = LampSampler) -> None:
        self._open = open_sampler
        self._sampler: LampSampler | None = None
        self._task: asyncio.Task[None] | None = None
        self._subs: dict[object, int] = {}
        self._seq = 0
        self._frame: dict[str, int] | None = None
        self._failed: BaseException | None = None
        self._cond = asyncio.Condition()

    def current_fps(self) -> int:
        return max(self._subs.values()) if self._subs else env_fps()

    def subscriber_count(self) -> int:
        return len(self._subs)

    def running(self) -> bool:
        return self._task is not None

    async def subscribe(self, fps: int | None = None) -> object:
        """Register a client. Raises LampUnavailable when the device cannot open."""
        if self._task is None:
            sampler = self._open()  # raises LampUnavailable
            self._sampler = sampler
            self._failed = None
            self._task = asyncio.get_running_loop().create_task(self._run(sampler))
        token = object()
        self._subs[token] = clamp_fps(fps, env_fps()) if fps is not None else env_fps()
        return token

    def unsubscribe(self, token: object) -> None:
        self._subs.pop(token, None)
        if not self._subs:
            self._stop()

    def _stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
        sampler, self._sampler = self._sampler, None
        self._frame = None
        if sampler is not None:
            sampler.close()

    async def _run(self, sampler: LampSampler) -> None:
        try:
            async for frame in sampler.frames(rate=self.current_fps):
                self._seq += 1
                self._frame = frame
                async with self._cond:
                    self._cond.notify_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the device went away or a read failed
            self._failed = exc
            async with self._cond:
                self._cond.notify_all()

    def latest(self) -> tuple[int, dict[str, int]] | None:
        if self._frame is None:
            return None
        return self._seq, self._frame

    async def next_frame(self, after: int, timeout: float) -> tuple[int, dict[str, int]] | None:
        """Return (seq, frame) once seq > ``after``; None on timeout.

        Raises LampFeedFailed when the sampler stopped with nothing newer to give.
        """
        async with self._cond:
            if self._seq <= after and self._failed is None:
                try:
                    await asyncio.wait_for(
                        self._cond.wait_for(lambda: self._seq > after or self._failed is not None),
                        timeout,
                    )
                except TimeoutError:
                    pass
            if self._seq > after and self._frame is not None:
                return self._seq, self._frame
            if self._failed is not None:
                raise LampFeedFailed(str(self._failed)) from self._failed
            return None
