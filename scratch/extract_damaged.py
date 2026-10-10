import sqlite3
import json

conn = sqlite3.connect(r'c:\WORK\Projects\olx_scrappy\data\scrappy.db')
c = conn.cursor()

query = '''
WITH ranked_ext AS (
  SELECT source, external_id, attributes, notes,
         row_number() OVER (PARTITION BY source, external_id ORDER BY extracted_at DESC, seq DESC) as rn
  FROM extractions
),
latest_ext AS (
  SELECT * FROM ranked_ext WHERE rn = 1
)
SELECT 
  o.source || ':' || o.external_id AS id,
  o.title,
  CAST(o.price_amount AS FLOAT) AS price,
  json_extract(e.attributes, '$.condition') AS condition,
  json_extract(e.attributes, '$.cpu') AS cpu,
  json_extract(e.attributes, '$.gpu') AS gpu,
  json_extract(e.attributes, '$.ram_gb') AS ram_gb,
  json_extract(e.attributes, '$.storage_gb') AS storage_gb,
  json_extract(e.attributes, '$.screen_in') AS screen_in,
  o.location,
  o.seller_name,
  o.url,
  o.description,
  e.notes,
  o.params
FROM offers o
JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id
WHERE o.status = 'active'
  AND (json_extract(e.attributes, '$.condition') IN ('damaged', 'for_parts')
       OR o.title LIKE '%uszkodzon%' OR o.title LIKE '%części%')
ORDER BY price ASC
'''

c.execute(query)
rows = c.fetchall()

results = []
for r in rows:
    results.append({
        "id": r[0],
        "title": r[1],
        "price": r[2],
        "condition": r[3],
        "cpu": r[4],
        "gpu": r[5],
        "ram_gb": r[6],
        "storage_gb": r[7],
        "screen_in": r[8],
        "location": r[9],
        "seller_name": r[10],
        "url": r[11],
        "description": r[12],
        "notes": r[13],
        "params": json.loads(r[14]) if r[14] else {}
    })

with open(r'c:\WORK\Projects\olx_scrappy\scratch\damaged_offers.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Extracted {len(results)} damaged offers to scratch/damaged_offers.json")
