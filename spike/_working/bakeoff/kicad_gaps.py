"""Split a KiCad DRC report's unconnected items into pad-to-pad gaps and ones with a via end."""
import re, sys
t = open(sys.argv[1]).read()
items = re.findall(r"\[unconnected_items\]:.*?\n((?:    @.*\n)+)", t)
pads = vias = 0
for it in items:
    ends = re.findall(r"@\([^)]*\): (\S+)", it)
    if "Via" in ends:
        vias += 1
    else:
        pads += 1
print(f"{sys.argv[1].split('/')[-1]}: pad-to-pad {pads}, with a via end {vias}")
