import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

def analyze_tier(title_name, where_clause, limit=15):
    query = f'''
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
        o.url,
        o.description
    FROM offers o
    JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
    WHERE o.status = 'active'
      AND o.price_kind = 'fixed'
      AND (json_extract(attributes, '$.condition') IN ('used', 'new') OR json_extract(attributes, '$.condition') IS NULL)
      AND (json_extract(attributes, '$.damage') IS NULL OR json_extract(attributes, '$.damage') = '[]')
      AND {where_clause}
    ORDER BY price ASC
    '''
    rows = c.execute(query).fetchall()
    prices = [r['price'] for r in rows if r['price'] > 100]
    if not prices:
        print(f"\n=== {title_name} ===: No items found")
        return []
    
    prices_sorted = sorted(prices)
    median_p = prices_sorted[len(prices_sorted)//2]
    min_p = min(prices_sorted)
    max_p = max(prices_sorted)
    
    print(f"\n=== {title_name} (Total: {len(prices)}, Min: {min_p:.0f} PLN, Median: {median_p:.0f} PLN, Max: {max_p:.0f} PLN) ===")
    print(f"Top {min(limit, len(rows))} cheapest offers:")
    for r in rows[:limit]:
        title = r['title'].replace('\n', ' ')[:45]
        loc = r['location'] or 'Unknown'
        print(f"  {r['price']:4.0f} PLN | CPU: {str(r['cpu']):15} | GPU: {str(r['gpu']):15} | {r['ram_gb']}GB | {r['refresh_hz']}Hz | {title} | {loc} | {r['url']}")
    return rows

print("="*80)
# 1. RTX 3060 offers
rtx_3060 = analyze_tier("RTX 3060 Laptops", "json_extract(attributes, '$.gpu') LIKE '%3060%' AND cast(o.price_amount as real) > 500", limit=12)

# 2. RTX 3050 / 3050 Ti offers
rtx_3050 = analyze_tier("RTX 3050 / 3050 Ti Laptops", "(json_extract(attributes, '$.gpu') LIKE '%3050%' OR json_extract(attributes, '$.gpu') LIKE '%3050 Ti%') AND cast(o.price_amount as real) > 500", limit=12)

# 3. 8-core beast CPUs (Ryzen 7 5800H, 4800H, 6800H, i7-11800H, i7-12700H)
eight_core = analyze_tier("8-Core / 14-Core High-End CPUs (5800H / 11800H / 12700H)", 
    "(json_extract(attributes, '$.cpu') LIKE '%5800H%' OR json_extract(attributes, '$.cpu') LIKE '%11800H%' OR json_extract(attributes, '$.cpu') LIKE '%4800H%' OR json_extract(attributes, '$.cpu') LIKE '%12700H%' OR json_extract(attributes, '$.cpu') LIKE '%6800H%') AND cast(o.price_amount as real) > 500", limit=12)

# 4. Premium models (Legion 5, ROG Strix, Zephyrus, Alienware, Omen)
legion = analyze_tier("Lenovo Legion 5 / Legion 5 Pro", "o.title LIKE '%Legion%' AND cast(o.price_amount as real) > 500", limit=12)

# 5. RTX 4050 / 4060
rtx_40_series = analyze_tier("RTX 4050 / 4060 Modern Gen", "(json_extract(attributes, '$.gpu') LIKE '%4050%' OR json_extract(attributes, '$.gpu') LIKE '%4060%') AND cast(o.price_amount as real) > 500", limit=10)
