import json
import re

with open(r'c:\WORK\Projects\olx_scrappy\scratch\damaged_offers.json', 'r', encoding='utf-8') as f:
    offers = json.load(f)

# Let's inspect offers and write a categorizer
print(f"Total offers: {len(offers)}")

classified = []
for o in offers:
    title = (o['title'] or '').lower()
    desc = (o['description'] or '').lower()
    cpu = (o['cpu'] or '')
    gpu = (o['gpu'] or '')
    price = o['price'] or 0
    
    # Check specs
    is_gaming = bool(gpu and gpu != 'Zintegrowana' and 'intel hd' not in gpu.lower())
    is_modern_thinkpad = any(k in title for k in ['t480', 't490', 'x390', 'e14', 'e590', 't580', 'l480', 'x1 carbon'])
    is_modern_cpu = any(k in cpu.lower() for k in ['8250', '8265', '10300', '10750', '1135', '11400', '12500', '12650', '3550h', '6600h']) or any(k in title for k in ['i5-8', 'i5-10', 'i5-11', 'i5-12', 'i7-8', 'i7-9', 'i7-10', 'i7-12', 'rtx', 'gtx'])
    
    classified.append((o['id'], o['price'], o['title'], gpu, cpu, is_gaming, is_modern_thinkpad))

print("Gaming or modern offers count:")
gaming_modern = [c for c in classified if c[5] or c[6]]
for g in sorted(gaming_modern, key=lambda x: x[1]):
    print(f"{g[1]:6.1f} PLN | GPU: {g[3]:15} | CPU: {g[4]:15} | {g[2][:50]}")
