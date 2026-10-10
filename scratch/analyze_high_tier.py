import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

query = '''
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
    json_extract(attributes, '$.battery_note') as battery_note,
    json_extract(attributes, '$.damage_note') as damage_note,
    o.location,
    o.url,
    o.description
FROM offers o
JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
WHERE o.status = 'active'
  AND o.price_kind = 'fixed'
  AND (json_extract(attributes, '$.damage') IS NULL OR json_extract(attributes, '$.damage') = '[]')
  AND (
      -- High end GPUs
      json_extract(attributes, '$.gpu') LIKE '%3060%'
      OR json_extract(attributes, '$.gpu') LIKE '%3070%'
      OR json_extract(attributes, '$.gpu') LIKE '%4050%'
      OR json_extract(attributes, '$.gpu') LIKE '%4060%'
      OR json_extract(attributes, '$.gpu') LIKE '%6600M%'
      OR json_extract(attributes, '$.gpu') LIKE '%2070%'
      -- Or top-tier CPUs with RTX 3050/3050Ti
      OR ((json_extract(attributes, '$.cpu') LIKE '%5800H%' 
           OR json_extract(attributes, '$.cpu') LIKE '%11800H%'
           OR json_extract(attributes, '$.cpu') LIKE '%12700H%'
           OR json_extract(attributes, '$.cpu') LIKE '%6800H%'
           OR json_extract(attributes, '$.cpu') LIKE '%12500H%') 
          AND (json_extract(attributes, '$.gpu') LIKE '%3050%' OR json_extract(attributes, '$.gpu') LIKE '%1660 Ti%'))
  )
  AND cast(o.price_amount as real) BETWEEN 1400 AND 2500
ORDER BY price ASC
'''

rows = c.execute(query).fetchall()
print(f"Top tier laptops (RTX 3060/4050/2070 or 8-core CPU + 3050) between 1400 and 2500 PLN: {len(rows)}")
for r in rows:
    title = r['title'].replace('\n', ' ')[:45]
    loc = r['location'] or 'Unknown'
    print(f"{r['price']:4.0f} PLN | {str(r['cpu']):15} | {str(r['gpu']):15} | {str(r['ram_gb'])}GB | {str(r['refresh_hz'])}Hz | {title} | {loc} | {r['url']}")
