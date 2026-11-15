import sys
from collections import Counter

counts = Counter()
for line in open(sys.argv[1]):
    parts = line.split('"')
    if len(parts) < 3:
        continue
    status = parts[2].split()[0]
    counts[status] += 1

for status, n in sorted(counts.items()):
    print(status, n)

