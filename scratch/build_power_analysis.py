import sqlite3
import json
import sys
import re

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Curated candidate list with target URLs or criteria
target_picks = [
    # 1. HP OMEN 17 i7-12700H 14C/20T + RTX 3060 140W @ 2200 PLN
    {
        "url_match": "%laptop-gamingowy-omen-17-CID99-ID1bFtoh%",
        "tier": "flagship-power",
        "badge_text": "Monster 14-Core CPU",
        "badge_type": "stellar",
        "highlight": "14 Cores / 20 Threads Alder Lake (6P + 8E) with full 140W RTX 3060 on a 17.3\" 144Hz chassis. Massive +280% multi-core jump over i5-9300H. Desktop-replacement class performance."
    },
    # 2. Lenovo Legion 5 Pro 16 i7-11800H + RTX 3060 130W + 16\" QHD 165Hz 500 nits HDR400 @ 2300 PLN
    {
        "url_match": "%laptop-gamingowy-lenovo-legion-5-pro-16-i7-16gb-1tb-CID99-ID1bUpxp%",
        "tier": "legion-champions",
        "badge_text": "Best Display & Chassis",
        "badge_type": "stellar",
        "highlight": "The undisputed king of the generation: 16\" 16:10 2560x1600 165Hz 500-nit HDR screen, 100% sRGB factory-calibrated, full 130W RTX 3060 with MUX switch, 8-Core i7-11800H, all-aluminum chassis, 1TB SSD."
    },
    # 3. Lenovo Legion 5 15ACH6H Ryzen 5 5600H + RTX 3060 130W + 165Hz sRGB @ 2200 PLN
    {
        "url_match": "%lenovo-legion-5-15ach6h-CID99-ID1c8xq3%",
        "tier": "legion-champions",
        "badge_text": "Best 1080p Legion Deal",
        "badge_type": "highlight",
        "highlight": "Full 130W TGP RTX 3060, true Coldfront 3.0 dual-fan cooling, and the superior 165Hz 100% sRGB panel (not the cheap 120Hz 45% NTSC). Clean condition with original charger."
    },
    # 4. Gigabyte G5 KC i5-10500H (6C/12T) + RTX 3060 105W + 240Hz screen + Honeywell PTM7950 @ 1999 PLN
    {
        "url_match": "%gigabyte-g5-kc-i5-10500h-16gb-512-rtx3060p-240hz-CID99-ID1cdGFd%",
        "tier": "sub-2000-titans",
        "badge_text": "240Hz + PTM7950 Repaste",
        "badge_type": "stellar",
        "highlight": "Lowest price in Poland for a full RTX 3060 (1,999 PLN)! Blazing 240Hz IPS screen, repasted with Honeywell PTM7950 phase-change pad (will never dry out), 3 storage slots (2x M.2 + 2.5\")."
    },
    # 5. Acer Predator Triton 300 SE i5-11300H + RTX 3060 @ 1899 PLN
    {
        "url_match": "%predator-triton-300-se-n20c8-i5-16gb-ram-512gb-ssd-iwin11-home-CID99-ID1cnM5A%",
        "tier": "sub-2000-titans",
        "badge_text": "Sub-1,900 RTX 3060",
        "badge_type": "highlight",
        "highlight": "All-metal Predator unibody chassis, vapor chamber cooling, RTX 3060 6GB. Significantly better build and thermals than entry Nitro line, priced under 1,900 PLN."
    },
    # 6. Acer Nitro 5 AN515-58 i7-12700H (14C/20T) + RTX 3060 140W @ 2300 PLN
    {
        "url_match": "%acer-nitro-5-an515-58-intelcore-i7-12700h-geforce-rtx-3060-CID99-ID1c6rxD.html%",
        "tier": "flagship-power",
        "badge_text": "14-Core 12th Gen Nitro",
        "badge_type": "stellar",
        "highlight": "Completely redesigned 2022 Nitro chassis (quad-exhaust, rear ports, MUX switch) featuring 14-core i7-12700H and 140W RTX 3060. Seller reports 80% battery health, zero defects."
    },
    # 7. Medion Erazer Specialist P10 i7-12700H + RTX 3060 + 16\" QHD 165Hz @ 2300 PLN
    {
        "url_match": "%medion-erazer-specialist-p10-CID99-ID1cEdo0%",
        "tier": "flagship-power",
        "badge_text": "QHD 165Hz + 12700H",
        "badge_type": "stellar",
        "highlight": "Equipped with 14-Core i7-12700H, RTX 3060, and a stunning 16\" 2560x1600 (QHD+) 165Hz display. Excellent desktop replacement for developer & gaming workloads."
    },
    # 8. Acer Nitro 5 AN515-57 RTX 4060 8GB (Ada Lovelace) + i7 + 165Hz QHD 1440p @ 2600 PLN
    {
        "url_match": "%acer-nitro-5-165-hz-qhd-1440p-rtx-4060-i7-CID99-ID16f0Hd%",
        "tier": "next-gen-ada",
        "badge_text": "RTX 4060 8GB + QHD",
        "badge_type": "stellar",
        "highlight": "Generation jump to Ada Lovelace RTX 4060 with 8GB VRAM (+110% over 1660 Ti), DLSS 3 Frame Gen, and a crisp 165Hz 1440p QHD screen. First used August 2025 (barely used)."
    },
    # 9. Acer Nitro V16 Ryzen 5 8645HS (Zen 4 + NPU) + RTX 4050 6GB @ 2500 PLN
    {
        "url_match": "%laptop-acer-nitro-v16-CID99-ID1aOkF3%",
        "tier": "next-gen-ada",
        "badge_text": "Zen 4 (4nm) + DLSS 3",
        "badge_type": "highlight",
        "highlight": "Brand new 4nm Zen 4 architecture with built-in Ryzen AI NPU and RTX 4050 6GB. Ultra-efficient thermals, high battery runtime, dual 512GB SSDs (1TB total storage)."
    },
    # 10. Lenovo Legion 5 15ACH6H Ryzen 7 5800H (8C/16T) + RTX 3060 130W + 165Hz @ 2599 PLN
    {
        "url_match": "%mega-okazja-laptop-gamingowy-lenovo-legion-5-15ach6h-ssd-165hz-r7-5800h-16gb-ram-512gb-dysk-ssd-rtx3060-win11-czarno-niebieski-aero-rtx5060-CID99-ID1bJfeG%",
        "tier": "legion-champions",
        "badge_text": "8-Core Zen 3 + 130W GPU",
        "badge_type": "stellar",
        "highlight": "Full 8-Core / 16-Thread Ryzen 7 5800H paired with maximum 130W RTX 3060. 165Hz display, pristine condition, ready to use with fresh Windows 11."
    },
    # 11. DELL G15 5525 Ryzen 5 6600H (6C/12T 6nm Zen 3+) + RTX 3050 4GB @ 1600 PLN
    {
        "url_match": "%dell-g15-5525-r5-6600h-16gb-rtx3050-4gb-m-2-256gb-w10-CID99-ID1cHhK2%",
        "tier": "budget-steals",
        "badge_text": "6nm Zen 3+ Modern Platform",
        "badge_type": "value",
        "highlight": "Only 1,600 PLN for a 6000-series AMD Rembrandt CPU (6nm Zen 3+, RDNA2 graphics) and RTX 3050. Premium Alienware-derived cooling geometry."
    },
    # 12. MSI Katana / GF63 i7-11800H (8C/16T Tiger Lake) + RTX 3050 + 144Hz @ 1650 PLN
    {
        "url_match": "%laptop-gamingowy-msi-CID99-ID1cbNJR%",
        "tier": "budget-steals",
        "badge_text": "8-Core i7 Under 1,700 PLN",
        "badge_type": "value",
        "highlight": "High-end 8-Core / 16-Thread i7-11800H with 24MB cache (+220% multi-core jump vs i5-9300H) and 144Hz display for a flat 1,650 PLN."
    },
    # 13. Lenovo IdeaPad Gaming 15 i5-11320H + RTX 3050 + 120Hz (Battery 4h) @ 1400 PLN
    {
        "url_match": "%lenovo-gaming-15-rtx3050-120hz-i5-11th-CID99-ID1ct6s1%",
        "tier": "budget-steals",
        "badge_text": "Best Entry Deal (1,400 PLN)",
        "badge_type": "value",
        "highlight": "10nm Tiger Lake + RTX 3050 with 16GB RAM and 120Hz screen for only 1,400 PLN. Seller confirms battery holds up to 4 hours."
    },
    # 14. ASUS ROG Zephyrus G14 Ryzen 7 5800HS (8C/16T) + RTX 3050 + 2.5K 120Hz @ 2300 PLN
    {
        "url_match": "%asus-rog-zephyrus-g14-ryzen-7-5800hs-rtx-3050-16gb-512gb-14-2-5k-120hz-CID99-ID1bJgu0%",
        "tier": "ultraportable",
        "badge_text": "Magnesium Ultraportable (1.7kg)",
        "badge_type": "highlight",
        "highlight": "Premium CNC magnesium alloy body, 1.7kg ultralight weight, 8-Core 5800HS, 14\" 2560x1440 120Hz 100% DCI-P3 display, 8+ hours battery life off charger."
    },
    # 15. HP Pavilion Gaming 15 Ryzen 5 5600H (6C/12T) + RTX 3050 + 16GB @ 1600 PLN
    {
        "url_match": "%laptop-gamingowy-hp-pavilion-15-ryzen-5-5600h-rtx-3050-16gb-ram-ssd-512gb-CID99-ID1cj2Si%",
        "tier": "budget-steals",
        "badge_text": "Zen 3 6-Core Under 1,600",
        "badge_type": "value",
        "highlight": "True Zen 3 6-core 12-thread efficiency paired with RTX 3050 for 1,600 PLN. Runs cool, low fan noise in daily tasks."
    },
    # 16. Lenovo Legion 5 15ACH6H Ryzen 5 5600H + RTX 3050 + 120Hz PTM7950 @ 1900 PLN
    {
        "url_match": "%15ach6h-ryzen-5-5600h-rtx3050-16gb-ram-512ssd-fhd-120hz-ptm7950-CID99-ID1cCzNz%",
        "tier": "legion-champions",
        "badge_text": "Legion Coldfront + PTM7950",
        "badge_type": "highlight",
        "highlight": "Legion 5 chassis with PTM7950 phase-change pad professionally applied. Exceptional thermal headroom and quiet operation."
    }
]

curated_results = []

for p in target_picks:
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
        cast(o.price_amount as integer) as price,
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
    WHERE o.url LIKE '{p["url_match"]}'
    LIMIT 1
    '''
    row = c.execute(query).fetchone()
    if row:
        item = dict(row)
        item['tier'] = p['tier']
        item['badge_text'] = p['badge_text']
        item['badge_type'] = p['badge_type']
        item['curated_highlight'] = p['highlight']
        curated_results.append(item)
    else:
        print(f"Warning: not found {p['url_match']}")

print(f"Total curated picks found: {len(curated_results)}")
with open('scratch/curated_power_laptops.json', 'w', encoding='utf-8') as f:
    json.dump(curated_results, f, ensure_ascii=False, indent=2)
print("Saved scratch/curated_power_laptops.json successfully.")
