"""Print the nets that have zones in a KiCad board (any format)."""
import re
import sys

t = open(sys.argv[1]).read()
names = set(re.findall(r'\(zone\s+\(net \d+\)\s+\(net_name "?([^")]*)"?\)', t))
names |= set(re.findall(r'\(zone\s+\(net "([^"]*)"\)', t))
print(" ".join(sorted(names)))
