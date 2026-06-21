"""
Patch the SimH quickmake to build headless (no SDL2/VT11).

The quickmake unconditionally adds -DHAVE_LIBSDL and includes the VT11
vector-display renderer (display/{vt11,sim_ws,display}.c) which has a
circular dependency with pdp11_vt.c.  In a headless container we need
neither, so we remove both sides.  pdp11_sys.c guards its vt_dev
reference with #ifdef USE_DISPLAY, so removing DISPLAY_OPT is safe.
"""
import re
import sys

path = "quickmake"
with open(path) as f:
    t = f.read()

# Remove VT11 renderer source files from the PDP11 source list
t = re.sub(
    r"[ \t]*\$\(DISPLAY\)/display\.c \$\(DISPLAY\)/sim_ws\.c \$\(DISPLAY\)/vt11\.c",
    "",
    t,
)

# Remove pdp11_vt.c (provides callbacks called by the renderer)
t = re.sub(r"[ \t]*\$\{PDP11D\}/pdp11_vt\.c", "", t)

# Remove DISPLAY_OPT from PDP11_OPT
t = t.replace("$(DISPLAY_OPT)", "")

with open(path, "w") as f:
    f.write(t)

print("quickmake patched OK", file=sys.stderr)
