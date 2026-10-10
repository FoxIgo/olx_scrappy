import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

ids_to_check = [
    # Top RTX 3060 under 2300
    ('Gigabyte G5 240Hz 1999', '%gigabyte-g5-kc%'),
    ('Acer Predator Triton 300 SE 1899', '%predator-triton-300-se-n20c8%'),
    ('Acer Nitro 5 3060 2000', '%acer-nitro-5-i5-11400h-rtx-3060%'),
    ('HP OMEN 17 i7-12700H 2200', '%laptop-gamingowy-omen-17%'),
    ('Legion 5 3060 Kołobrzeg 2200', '%lenovo-legion-5-15ach6h%ID1c8xq3%'),
    ('Legion 5 3060 Gdańsk 2199', '%lenovo-legion-5-rtx-3060-CID99-ID1cqmGh%'),
    ('Legion 5 Pro 16 i7-11800H 2300', '%legion-5-pro-16-i7-16gb-1tb%'),
    ('Acer Nitro 5 i7-12700H 3060 2300', '%acer-nitro-5-an515-58-intelcore-i7-12700h-geforce-rtx-3060%'),
    ('Medion Erazer i7-12700H 3060 2300', '%medion-erazer-specialist-p10%'),
    ('Legion 5 Pro 3050Ti 1800', '%lenovo-legion-5-pro-ryzen-5-5600h-16gb-500gb-rtx-3050ti%'),
    ('Legion 5 5600H PTM7950 1900', '%15ach6h-ryzen-5-5600h-rtx3050%'),
    ('ROG Zephyrus G14 5800HS 1900', '%asus-rog-zephyrus-g14-ryzen-7-5800hs%'),
    ('DELL G15 6600H 3050 1600', '%dell-g15-5525-r5-6600h%'),
    ('HP Pavilion 5600H 3050 1600', '%laptop-gamingowy-hp-pavilion-15-ryzen-5-5600h%'),
    ('MSI i7-11800H 3050 1650', '%laptop-gamingowy-msi-CID99-ID1cbNJR%'),
    ('IdeaPad Gaming 3 3050 1400', '%lenovo-gaming-15-rtx3050-120hz-i5-11th%'),
    ('Legion 5 5800H 3060 2599', '%lenovo-legion-5-15ach6h-ssd-165hz-r7-5800h%'),
    ('Nitro 5 RTX 4060 QHD 2600', '%acer-nitro-5-165-hz-qhd-1440p-rtx-4060-i7%'),
    ('Nitro V16 8645HS RTX 4050 2500', '%laptop-acer-nitro-v16-CID99-ID1aOkF3%')
]

for label, pattern in ids_to_check:
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
        json_extract(attributes, '$.battery_note') as battery_note,
        json_extract(attributes, '$.damage_note') as damage_note,
        o.location,
        o.url,
        o.description
    FROM offers o
    JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
    WHERE o.url LIKE '{pattern}'
    LIMIT 1
    '''
    row = c.execute(query).fetchone()
    if row:
        print(f"\n==================== {label} ====================")
        print(f"Title: {row['title']}")
        print(f"Price: {row['price']:.0f} PLN | Loc: {row['location']}")
        print(f"CPU: {row['cpu']} | GPU: {row['gpu']} | RAM: {row['ram_gb']}GB | Screen: {row['screen_in']}\" {row['resolution']} {row['refresh_hz']}Hz")
        print(f"URL: {row['url']}")
        desc_sample = (row['description'] or '')[:300].replace('\n', ' ')
        print(f"Desc: {desc_sample}...")
    else:
        print(f"\n[NOT FOUND] {label}")
