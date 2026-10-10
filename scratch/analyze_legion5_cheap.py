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
    json_extract(attributes, '$.refresh_hz') as refresh_hz,
    o.location,
    o.url
FROM offers o
JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
WHERE o.status = 'active'
  AND o.price_kind = 'fixed'
  AND (json_extract(attributes, '$.damage') IS NULL OR json_extract(attributes, '$.damage') = '[]')
  AND o.title LIKE '%Legion 5%'
  AND cast(o.price_amount as real) BETWEEN 1200 AND 2650
ORDER BY price ASC
'''

rows = c.execute(query).fetchall()
print(f"Total Legion 5 between 1200 and 2650 PLN: {len(rows)}")
for r in rows:
    title = r['title'].replace('\n', ' ')[:45]
    loc = r['location'] or 'Unknown'
    print(f"{r['price']:4.0f} PLN | {str(r['cpu']):15} | {str(r['gpu']):15} | {str(r['ram_gb'])}GB | {str(r['refresh_hz'])}Hz | {title} | {loc} | {r['url']}")
