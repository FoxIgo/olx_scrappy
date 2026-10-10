import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

ids_to_check = [
    ('Gigabyte G5 240Hz 1999', '%gigabyte-g5-kc%'),
    ('Acer Predator Triton 300 SE 1899', '%predator-triton-300-se-n20c8%'),
    ('Acer Nitro 5 3060 2000', '%acer-nitro-5-i5-11400h-rtx-3060%'),
    ('HP OMEN 17 i7-12700H 2200', '%laptop-gamingowy-omen-17%'),
    ('Legion 5 3060 Kołobrzeg 2200', '%lenovo-legion-5-15ach6h%ID1c8xq3%'),
    ('Legion 5 3060 Gdańsk 2199', '%lenovo-legion-5-rtx-3060-CID99-ID1cqmGh%'),
    ('Legion 5 Pro 16 i7-11800H 2300', '%legion-5-pro-16-i7-16gb-1tb%')
]

for label, pattern in ids_to_check:
    query = f'''
    SELECT o.title, cast(o.price_amount as real) as price, o.location, o.url, o.description
    FROM offers o
    WHERE o.url LIKE '{pattern}'
    LIMIT 1
    '''
    row = c.execute(query).fetchone()
    if row:
        print(f"=== {label} ===")
        print(f"Title: {row['title']} | Price: {row['price']:.0f} PLN | Loc: {row['location']}")
        print(f"URL: {row['url']}")
        desc = (row['description'] or '')[:300].replace('\n', ' ')
        print(f"Desc: {desc}...\n")
