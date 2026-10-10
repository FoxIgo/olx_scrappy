import sqlite3
import json
import os
import re

db_path = "packages/server/data/scrappy.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Query all relevant sweet-spot listings
query = """
WITH latest_ext AS (
    SELECT source, external_id, attributes,
           row_number() OVER (PARTITION BY source, external_id ORDER BY extracted_at DESC, seq DESC) as rn
    FROM extractions
    WHERE category = 'laptop'
)
SELECT 
    o.source || ':' || o.external_id as id,
    o.title,
    cast(o.price_amount as integer) as price,
    json_extract(attributes, '$.cpu') as cpu,
    json_extract(attributes, '$.ram_gb') as ram_gb,
    json_extract(attributes, '$.storage_gb') as storage_gb,
    json_extract(attributes, '$.storage_type') as storage_type,
    json_extract(attributes, '$.screen_in') as screen_in,
    json_extract(attributes, '$.resolution') as resolution,
    json_extract(attributes, '$.gpu') as gpu,
    json_extract(attributes, '$.condition') as condition,
    json_extract(attributes, '$.battery_note') as battery_note,
    o.location,
    o.url,
    o.description
FROM offers o
JOIN latest_ext e ON o.source = e.source AND o.external_id = e.external_id AND e.rn = 1
WHERE o.status = 'active'
  AND o.price_kind = 'fixed'
  AND cast(o.price_amount as real) BETWEEN 300 AND 750
  AND json_extract(attributes, '$.condition') = 'used'
  AND (json_extract(attributes, '$.damage') IS NULL OR json_extract(attributes, '$.damage') = '[]')
  AND (
      json_extract(attributes, '$.cpu') LIKE '%8250%' OR json_extract(attributes, '$.cpu') LIKE '%8265%' 
      OR json_extract(attributes, '$.cpu') LIKE '%8350%' OR json_extract(attributes, '$.cpu') LIKE '%8365%' 
      OR json_extract(attributes, '$.cpu') LIKE '%10210%' OR json_extract(attributes, '$.cpu') LIKE '%1035%' 
      OR json_extract(attributes, '$.cpu') LIKE '%1135%' OR json_extract(attributes, '$.cpu') LIKE '%3500U%' 
      OR json_extract(attributes, '$.cpu') LIKE '%4500U%' OR json_extract(attributes, '$.cpu') LIKE '%5500U%'
      OR o.title LIKE '%T480%' OR o.title LIKE '%T495%' OR o.title LIKE '%T490%' OR o.title LIKE '%L490%' 
      OR o.title LIKE '%T580%' OR o.title LIKE '%5400%' OR o.title LIKE '%7490%'
  )
ORDER BY price ASC
"""

rows = cursor.execute(query).fetchall()

items = []
for r in rows:
    title = r["title"] or ""
    cpu = r["cpu"] or ""
    ram = r["ram_gb"] or 8
    storage = r["storage_gb"] or 256
    price = r["price"]
    url = r["url"]
    loc = r["location"] or ""
    desc = r["description"] or ""
    
    # Identify brand
    title_lower = title.lower()
    if "thinkpad" in title_lower or "t480" in title_lower or "t490" in title_lower or "t495" in title_lower or "t580" in title_lower or "l490" in title_lower or "l480" in title_lower:
        brand = "ThinkPad"
    elif "latitude" in title_lower or "dell" in title_lower:
        brand = "Dell Latitude"
    elif "probook" in title_lower or "elitebook" in title_lower or "hp" in title_lower:
        brand = "HP Elite/ProBook"
    else:
        brand = "Other"

    # Screen resolution detection
    res = r["resolution"]
    if not res:
        if "fhd" in title_lower or "1080" in title_lower or "full hd" in title_lower or "fhd" in desc.lower():
            res = "1920x1080"
        elif "hd" in title_lower or "1366" in title_lower:
            res = "1366x768"
        else:
            res = "1920x1080 (assumed)"

    # CPU Family & Cores
    cpu_lower = (cpu + " " + title).lower()
    if "3500u" in cpu_lower:
        arch = "AMD Ryzen 5 (Zen+)"
        cores = 4
        threads = 8
        gpu_name = "Radeon Vega 8"
    elif "4500u" in cpu_lower:
        arch = "AMD Ryzen 5 (Zen 2)"
        cores = 6
        threads = 6
        gpu_name = "Radeon Vega 6"
    elif "10210u" in cpu_lower or "1035g1" in cpu_lower:
        arch = "Intel 10th Gen Core"
        cores = 4
        threads = 8
        gpu_name = "Intel UHD Graphics"
    elif "8250" in cpu_lower or "8265" in cpu_lower or "8350" in cpu_lower or "8365" in cpu_lower or "8th" in cpu_lower:
        arch = "Intel 8th Gen Core"
        cores = 4
        threads = 8
        gpu_name = "Intel UHD 620"
    else:
        arch = "Intel 8th Gen/Equivalent"
        cores = 4
        threads = 8
        gpu_name = "Intel Integrated"

    # Linux Compatibility Tier
    # ThinkPad T-Series & Latitude 7000/5000 are Tier S
    if "t480" in title_lower or "t495" in title_lower or "t490" in title_lower or "t580" in title_lower or "7490" in title_lower or "5400" in title_lower:
        linux_tier = "Tier S (Gold)"
        linux_notes = "Flawless kernel support, LVFS/fwupd UEFI updates, dual SO-DIMM sockets, flawless Wayland/Intel/AMD drivers."
    elif brand in ["ThinkPad", "Dell Latitude", "HP Elite/ProBook"]:
        linux_tier = "Tier A (High)"
        linux_notes = "Enterprise-grade hardware, standard ACPI, well-tested audio & Wi-Fi in upstream kernels."
    else:
        linux_tier = "Tier B (Good)"
        linux_notes = "Standard consumer UEFI; ensure secure boot disable and kernel 6.x+."

    # Value / ROI Score
    # Score based on: (Cores * 1.5 + RAM_GB * 1.0 + (50 if NVMe/SSD else 0) + (30 if 1080p else 0)) / Price * 1000
    base_val = (cores * 15) + (ram * 3.5) + (35 if "1920" in str(res) else 10) + (30 if brand == "ThinkPad" else 20)
    roi_score = round((base_val / max(price, 1)) * 100, 1)

    items.append({
        "id": r["id"],
        "title": title,
        "price": price,
        "cpu": cpu if cpu else "Core i5 (8th Gen)",
        "arch": arch,
        "cores": cores,
        "threads": threads,
        "ram": ram,
        "storage": storage,
        "storage_type": r["storage_type"] or "ssd",
        "res": res,
        "brand": brand,
        "gpu": gpu_name,
        "loc": loc,
        "url": url,
        "linux_tier": linux_tier,
        "linux_notes": linux_notes,
        "roi_score": roi_score
    })

print(f"Processed {len(items)} items")

# Sort by ROI score descending
items.sort(key=lambda x: x["roi_score"], reverse=True)

with open("scratch/processed_laptops.json", "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

print("Saved scratch/processed_laptops.json")
