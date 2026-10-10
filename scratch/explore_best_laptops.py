import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Check price ranges and models for high-performance GPUs
query_gpu = '''
WITH latest_ext AS (
    SELECT source, external_id, attributes,
           row_number() OVER (PARTITION BY source, external_id ORDER BY extracted_at DESC, seq DESC) as rn
    FROM extractions
    WHERE category = 'laptop'
)
SELECT 
    o.source || ':' || o.external_id as id,
    o.title,
    cast(o.price_amount as real) as price,
    json_extract(attributes, '$.cpu') as cpu,
    json_extract(attributes, '$.gpu') as gpu,
    json_extract(attributes, '$.vram_gb') as vram_gb,
    json_extract(attributes, '$.ram_gb') as ram_gb,
    json_extract(attributes, '$.storage_gb') as storage_gb,
    json_extract(attributes, '$.screen_in') as screen_in,
    json_extract(attributes, '$.refresh_hz') as refresh_hz,
    json_extract(attributes, '$.resolution') as resolution,
    json_extract(attributes, '$.condition') as condition,
    json_extract(attributes, '$.damage') as damage,
    json_extract(attributes, '$.damage_note') as damage_note,
    json_extract(attributes, '$.battery_note') as battery_note,
    o.location,
    o.url
FROM offers o
JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
WHERE o.status = 'active'
  AND o.price_kind = 'fixed'
  AND (json_extract(attributes, '$.condition') IN ('used', 'new') OR json_extract(attributes, '$.condition') IS NULL)
  AND (json_extract(attributes, '$.damage') IS NULL OR json_extract(attributes, '$.damage') = '[]')
ORDER BY price ASC
'''

rows = c.execute(query_gpu).fetchall()
print(f"Total active fixed-price undamaged offers: {len(rows)}")

# Let's inspect offers by GPU and CPU tiers
gpus = {}
cpus = {}
for r in rows:
    g = str(r['gpu'])
    cp = str(r['cpu'])
    gpus[g] = gpus.get(g, 0) + 1
    cpus[cp] = cpus.get(cp, 0) + 1

# Print top GPUs
print("\n--- TOP GPUs ---")
for g, cnt in sorted(gpus.items(), key=lambda x: x[1], reverse=True)[:30]:
    print(f"{g}: {cnt}")

print("\n--- TOP CPUs ---")
for cp, cnt in sorted(cpus.items(), key=lambda x: x[1], reverse=True)[:30]:
    print(f"{cp}: {cnt}")
