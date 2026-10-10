import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 20 hand-curated top power offers representing the best across all tiers
laptops = [
    # 1. HP OMEN 17 - 14 Cores / 20 Threads + RTX 3060 140W
    {
        "url_pattern": "%laptop-gamingowy-omen-17-CID99-ID1bFtoh%",
        "title": "HP OMEN 17-ck1440nw (i7-12700H 14C/20T + RTX 3060 140W)",
        "price": 2200,
        "negotiable": True,
        "category": "flagship-power",
        "roiScore": 99,
        "cpu": "Intel Core i7-12700H",
        "cpuCores": "14C / 20T (6P + 8E, Intel 7, up to 4.7 GHz)",
        "cpuVsBaseline": 380,
        "cpuPercentText": "+280% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (140W Max TGP)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "17.3\" IPS FHD 144 Hz (300 nits, 100% sRGB)",
        "ram": "16 GB DDR5 4800MHz (Dual-Channel)",
        "storage": "512 GB NVMe PCIe 4.0 SSD",
        "batteryHealth": "Good / Functional",
        "chassisGrade": "HP Omen Tempest Cooling & Aluminum Keyboard Deck",
        "location": "Skwierzyna, Lubuskie",
        "badge": { "type": "stellar", "text": "Ultimate Compute King" },
        "highlights": "Absolute computing monster for 2,200 PLN. 14 physical cores and 20 threads demolish compilation, video encoding, virtualization, and gaming. Massive 17.3\" chassis with 140W full GPU TGP keeps temperatures strictly under control. DDR5 memory standard.",
        "colorBar": "linear-gradient(90deg, #10b981, #06b6d4)"
    },

    # 2. Lenovo Legion 5 Pro 16 - i7-11800H + RTX 3060 130W + 16\" QHD 165Hz 500-nit HDR400
    {
        "url_pattern": "%laptop-gamingowy-lenovo-legion-5-pro-16-i7-16gb-1tb-CID99-ID1bUpxp%",
        "title": "Lenovo Legion 5 Pro 16ITH6H (16\" 16:10 QHD+ 165Hz 500-nit HDR)",
        "price": 2300,
        "negotiable": True,
        "category": "legion-champions",
        "roiScore": 98,
        "cpu": "Intel Core i7-11800H",
        "cpuCores": "8C / 16T (10nm SuperFin Tiger Lake, 24MB Cache)",
        "cpuVsBaseline": 320,
        "cpuPercentText": "+220% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (130W TGP + MUX Switch)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "16.0\" 16:10 2560x1600 (QHD+) 165Hz 500 nits HDR400 100% sRGB",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "1000 GB (1 TB) NVMe SSD",
        "batteryHealth": "Holds Well (Original 300W Adapter)",
        "chassisGrade": "All-Aluminum Storm Grey Unibody / Coldfront 3.0",
        "location": "Warszawa, Mazowieckie",
        "badge": { "type": "stellar", "text": "Best Display & Chassis" },
        "highlights": "Widely rated as the pinnacle laptop of this generation. The 16:10 2560x1600 500-nit HDR400 panel is leagues ahead of entry-level 250-nit 45% NTSC screens. Full 130W TGP, hardware MUX switch, 1TB NVMe SSD, and rigid all-aluminum build.",
        "colorBar": "linear-gradient(90deg, #a855f7, #38bdf8)"
    },

    # 3. Gigabyte G5 KC - i5-10500H 6C/12T + RTX 3060P + 240Hz Display + Honeywell PTM7950 Repaste
    {
        "url_pattern": "%gigabyte-g5-kc-i5-10500h-16gb-512-rtx3060p-240hz-CID99-ID1cdGFd%",
        "title": "Gigabyte G5 KC (RTX 3060 105W + 240Hz Screen + PTM7950)",
        "price": 1999,
        "negotiable": True,
        "category": "sub-2000-titans",
        "roiScore": 97,
        "cpu": "Intel Core i5-10500H",
        "cpuCores": "6C / 12T (up to 4.50 GHz, 12MB Cache)",
        "cpuVsBaseline": 165,
        "cpuPercentText": "+65% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (105W Max-P)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 240 Hz FHD (Ultra-Smooth Esports)",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe (3 Bays: 2x M.2 + 2.5\" SATA)",
        "batteryHealth": "Good Condition",
        "chassisGrade": "Windforce Dual-Fan (Repasted with Honeywell PTM7950)",
        "location": "Lublin, Lubelskie",
        "badge": { "type": "stellar", "text": "Sub-2,000 PLN Titan" },
        "highlights": "First true RTX 3060 under 2,000 PLN! Incredible 240Hz refresh panel. Repasted by owner with industrial Honeywell PTM7950 phase-change pad (will never pump out or dry). Has 3 separate internal drive bays for mass storage expansion.",
        "colorBar": "linear-gradient(90deg, #10b981, #f59e0b)"
    },

    # 4. Lenovo Legion 5 15ACH6H - Ryzen 5 5600H + RTX 3060 130W + 165Hz 100% sRGB
    {
        "url_pattern": "%lenovo-legion-5-15ach6h-CID99-ID1c8xq3%",
        "title": "Lenovo Legion 5 15ACH6H (Ryzen 5 5600H + RTX 3060 130W + 165Hz)",
        "price": 2200,
        "negotiable": True,
        "category": "legion-champions",
        "roiScore": 96,
        "cpu": "AMD Ryzen 5 5600H",
        "cpuCores": "6C / 12T (7nm Zen 3, up to 4.2 GHz)",
        "cpuVsBaseline": 235,
        "cpuPercentText": "+135% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (Full 130W TGP + MUX Switch)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 165 Hz FHD (300 nits, 100% sRGB, Dolby Vision, G-Sync)",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe PCIe SSD (Dual M.2 Bays)",
        "batteryHealth": "Healthy (Original Charger Included)",
        "chassisGrade": "Legion Coldfront 3.0 / TrueStrike Keyboard",
        "location": "Kołobrzeg, Zachodniopomorskie",
        "badge": { "type": "highlight", "text": "130W Full TGP Benchmark" },
        "highlights": "The benchmark by which all gaming laptops are judged. 130W full power RTX 3060 with hardware MUX switch beats lower-wattage RTX 4050s. Features the upgraded 165Hz 100% sRGB panel with zero ghosting and TrueStrike tactile keyboard.",
        "colorBar": "linear-gradient(90deg, #38bdf8, #a855f7)"
    },

    # 5. Acer Nitro 5 (2022 Overhaul) - i7-12700H (14C/20T) + RTX 3060 140W
    {
        "url_pattern": "%acer-nitro-5-an515-58-intelcore-i7-12700h-geforce-rtx-3060-CID99-ID1c6rxD.html%",
        "title": "Acer Nitro 5 AN515-58 (12th Gen 14C/20T + 140W RTX 3060 + MUX)",
        "price": 2300,
        "negotiable": True,
        "category": "flagship-power",
        "roiScore": 95,
        "cpu": "Intel Core i7-12700H",
        "cpuCores": "14C / 20T (6P + 8E, Intel 7, up to 4.7 GHz)",
        "cpuVsBaseline": 380,
        "cpuPercentText": "+280% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (140W Max TGP + MUX Switch)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 144 Hz FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD (Dual M.2 + SATA)",
        "batteryHealth": "80% Health Remaining ('Bateria 80%')",
        "chassisGrade": "2022 Full Redesign (Rear I/O, Quad Exhauster, Dual Fans)",
        "location": "Warszawa, Mazowieckie",
        "badge": { "type": "stellar", "text": "14-Core 12th Gen Overhaul" },
        "highlights": "Do not confuse this with older Nitro chassis. The AN515-58 is an entirely new 2022 platform with rear charging ports, quad exhausts, full 140W GPU TGP, and built-in MUX switch. Seller explicitly confirms 80% battery health and flawless condition.",
        "colorBar": "linear-gradient(90deg, #f59e0b, #10b981)"
    },

    # 6. Medion Erazer Specialist P10 - i7-12700H + RTX 3060 + 16\" QHD+ 165Hz
    {
        "url_pattern": "%medion-erazer-specialist-p10-CID99-ID1cEdo0%",
        "title": "Medion Erazer Specialist P10 (i7-12700H 14C/20T + 16\" QHD+ 165Hz)",
        "price": 2300,
        "negotiable": False,
        "category": "flagship-power",
        "roiScore": 94,
        "cpu": "Intel Core i7-12700H",
        "cpuCores": "14C / 20T (6P + 8E, up to 4.7 GHz)",
        "cpuVsBaseline": 380,
        "cpuPercentText": "+280% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "16.0\" 16:10 2560x1600 (QHD+) 165 Hz IPS",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Very Good Condition ('mało używany')",
        "chassisGrade": "Tongfang Magnesium-Alloy Gaming Chassis",
        "location": "Kłodzko, Dolnośląskie",
        "badge": { "type": "highlight", "text": "16\" QHD 165Hz + 14C" },
        "highlights": "OEM Tongfang chassis branded by Lenovo/Medion. Combines Intel's 14-core flagship with a crisp 2560x1600 165Hz panel. Barely used, pristine technical state.",
        "colorBar": "linear-gradient(90deg, #a855f7, #ec4899)"
    },

    # 7. Acer Predator Triton 300 SE - i5-11300H + RTX 3060 6GB (Slim Aluminum)
    {
        "url_pattern": "%predator-triton-300-se-n20c8-i5-16gb-ram-512gb-ssd-iwin11-home-CID99-ID1cnM5A%",
        "title": "Acer Predator Triton 300 SE (All-Metal Chassis + RTX 3060 6GB)",
        "price": 1899,
        "negotiable": False,
        "category": "sub-2000-titans",
        "roiScore": 95,
        "cpu": "Intel Core i5-11300H",
        "cpuCores": "4C / 8T (10nm Tiger Lake, up to 4.4 GHz)",
        "cpuVsBaseline": 125,
        "cpuPercentText": "+25% Single-Core Boost",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (Ampere DLSS 2/3.5)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "14.0\" IPS FHD 144 Hz (100% sRGB, 300 nits)",
        "ram": "16 GB LPDDR4X 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Functional Used",
        "chassisGrade": "All-Metal Predator Triton Unibody & 5th Gen AeroBlade Fans",
        "location": "Piła, Wielkopolskie",
        "badge": { "type": "highlight", "text": "Sub-1,900 PLN RTX 3060" },
        "highlights": "Premium slim Predator build for under 1,900 PLN! All-metal silver chassis, 1.7kg portable profile, vapor chamber with custom 5th gen metal fans. Far superior rigidity compared to plastic Nitros.",
        "colorBar": "linear-gradient(90deg, #0284c7, #38bdf8)"
    },

    # 8. Acer Nitro 5 - RTX 4060 8GB (Ada Lovelace) + 165Hz QHD 1440p
    {
        "url_pattern": "%acer-nitro-5-165-hz-qhd-1440p-rtx-4060-i7-CID99-ID16f0Hd%",
        "title": "Acer Nitro 5 (RTX 4060 8GB Ada Lovelace + 165Hz QHD 1440p)",
        "price": 2600,
        "negotiable": True,
        "category": "next-gen-ada",
        "roiScore": 94,
        "cpu": "Intel Core i7-12650H",
        "cpuCores": "10C / 16T (6P + 4E, up to 4.7 GHz, 24MB Cache)",
        "cpuVsBaseline": 325,
        "cpuPercentText": "+225% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 4060 8GB (Ada Lovelace, DLSS 3 Frame Gen)",
        "gpuVsBaseline": 210,
        "gpuPercentText": "+110% vs 1660 Ti (+238% vs 1650)",
        "display": "15.6\" IPS 165 Hz QHD (2560x1440, 100% DCI-P3)",
        "ram": "16 GB DDR5 4800MHz",
        "storage": "512 GB NVMe PCIe 4.0 SSD",
        "batteryHealth": "Like New (First used Aug 2025)",
        "chassisGrade": "2023 Nitro Gaming Redesign / MUX Switch",
        "location": "Trębaczew, Łódzkie",
        "badge": { "type": "stellar", "text": "RTX 4060 8GB + 2K QHD" },
        "highlights": "Full generational leap to NVIDIA Ada Lovelace architecture: 8GB high-speed VRAM, DLSS 3 AI Frame Generation, paired with a razor-sharp 1440p QHD 165Hz display. Unused gift first turned on in late 2025.",
        "colorBar": "linear-gradient(90deg, #10b981, #a855f7)"
    },

    # 9. Acer Nitro V16 - Ryzen 5 8645HS (4nm Zen 4 + NPU) + RTX 4050 6GB
    {
        "url_pattern": "%laptop-acer-nitro-v16-CID99-ID1aOkF3%",
        "title": "Acer Nitro V 16 (Ryzen 5 8645HS Zen 4 + RTX 4050 6GB + 1TB SSD)",
        "price": 2500,
        "negotiable": True,
        "category": "next-gen-ada",
        "roiScore": 93,
        "cpu": "AMD Ryzen 5 8645HS",
        "cpuCores": "6C / 12T (4nm Zen 4, up to 5.0 GHz + Ryzen AI NPU)",
        "cpuVsBaseline": 340,
        "cpuPercentText": "+240% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 4050 6GB (Ada Lovelace, DLSS 3)",
        "gpuVsBaseline": 175,
        "gpuPercentText": "+75% vs 1660 Ti (+182% vs 1650)",
        "display": "16.0\" 16:10 IPS 165 Hz FHD+ (1920x1200)",
        "ram": "16 GB DDR5 5600MHz",
        "storage": "1024 GB (512GB factory + 512GB Lexar SSD)",
        "batteryHealth": "Excellent (Like New)",
        "chassisGrade": "2024 Nitro V Series 16-inch",
        "location": "Katowice, Śląskie",
        "badge": { "type": "highlight", "text": "4nm Zen 4 + DDR5-5600" },
        "highlights": "State-of-the-art 2024 architecture! Built on TSMC's 4nm node with ultra-high battery efficiency and built-in AI NPU. Includes dual SSDs (1TB total) and DDR5-5600 high-speed memory.",
        "colorBar": "linear-gradient(90deg, #06b6d4, #10b981)"
    },

    # 10. Lenovo Legion 5 15ACH6H - Ryzen 7 5800H (8C/16T) + RTX 3060 130W + 165Hz
    {
        "url_pattern": "%mega-okazja-laptop-gamingowy-lenovo-legion-5-15ach6h-ssd-165hz-r7-5800h-16gb-ram-512gb-dysk-ssd-rtx3060-win11-czarno-niebieski-aero-rtx5060-CID99-ID1bJfeG%",
        "title": "Lenovo Legion 5 15ACH6H (Ryzen 7 5800H 8C/16T + RTX 3060 130W)",
        "price": 2599,
        "negotiable": True,
        "category": "legion-champions",
        "roiScore": 94,
        "cpu": "AMD Ryzen 7 5800H",
        "cpuCores": "8C / 16T (7nm Zen 3, up to 4.4 GHz, 16MB Cache)",
        "cpuVsBaseline": 310,
        "cpuPercentText": "+210% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB (Full 130W TGP + MUX Switch)",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 165 Hz FHD (300 nits, 100% sRGB, Dolby Vision)",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Very Good ('Stan Bardzo Dobry')",
        "chassisGrade": "Legion Coldfront 3.0 / Phantom Black-Aero Blue",
        "location": "Bielsko-Biała, Śląskie",
        "badge": { "type": "stellar", "text": "8-Core Zen 3 Legion" },
        "highlights": "The dream configuration for developers and gamers: 8 physical Zen 3 cores, full 130W TGP GPU without throttling, and the 165Hz 100% sRGB color-accurate display. Seller confirms immaculate condition.",
        "colorBar": "linear-gradient(90deg, #a855f7, #38bdf8)"
    },

    # 11. DELL G15 5525 - Ryzen 5 6600H (6nm Zen 3+ RDNA2) + RTX 3050 4GB
    {
        "url_pattern": "%dell-g15-5525-r5-6600h-16gb-rtx3050-4gb-m-2-256gb-w10-CID99-ID1cHhK2%",
        "title": "DELL G15 5525 (Ryzen 5 6600H 6nm Zen 3+ / RTX 3050 / DDR5)",
        "price": 1600,
        "negotiable": True,
        "category": "budget-steals",
        "roiScore": 97,
        "cpu": "AMD Ryzen 5 6600H",
        "cpuCores": "6C / 12T (6nm Zen 3+, up to 4.5 GHz, RDNA2 iGPU)",
        "cpuVsBaseline": 250,
        "cpuPercentText": "+150% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3050 4GB (GDDR6)",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650 (DLSS 2/3.5)",
        "display": "15.6\" IPS 120 Hz FHD",
        "ram": "16 GB DDR5 4800MHz",
        "storage": "256 GB NVMe SSD (M.2 Expansion Slot)",
        "batteryHealth": "Good Condition",
        "chassisGrade": "Alienware Cryo-Tech Inspired Thermal Geometry",
        "location": "Rzeszów, Podkarpackie",
        "badge": { "type": "value", "text": "1,600 PLN Steal" },
        "highlights": "Huge technological jump for only 1,600 PLN! Features AMD's modern 6nm Rembrandt Zen 3+ platform with DDR5 RAM and Alienware-derived heavy copper cooling geometry. Excellent battery life.",
        "colorBar": "linear-gradient(90deg, #10b981, #06b6d4)"
    },

    # 12. MSI Gaming - Core i7-11800H (8C/16T Tiger Lake) + RTX 3050 + 144Hz
    {
        "url_pattern": "%laptop-gamingowy-msi-CID99-ID1cbNJR%",
        "title": "MSI Gaming Katana / GF63 (Core i7-11800H 8C/16T + RTX 3050 + 144Hz)",
        "price": 1650,
        "negotiable": True,
        "category": "budget-steals",
        "roiScore": 96,
        "cpu": "Intel Core i7-11800H",
        "cpuCores": "8C / 16T (10nm Tiger Lake, 24MB L3 Cache, up to 4.6 GHz)",
        "cpuVsBaseline": 320,
        "cpuPercentText": "+220% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3050 4GB GDDR6",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650",
        "display": "15.6\" IPS 144 Hz FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Functional Used",
        "chassisGrade": "Cooler Boost 5 Dual Fan System",
        "location": "Jabłonna, Mazowieckie",
        "badge": { "type": "value", "text": "8-Core i7 Under 1,700" },
        "highlights": "If your primary goal is heavy multi-threaded compute (Docker, compilation, data processing, rendering) under 1,700 PLN, this 8-core 16-thread i7 with 24MB cache crushes 4-core i5s by +220%.",
        "colorBar": "linear-gradient(90deg, #f59e0b, #10b981)"
    },

    # 13. Lenovo IdeaPad Gaming 15 - i5-11320H + RTX 3050 + 120Hz (Holds 4h)
    {
        "url_pattern": "%lenovo-gaming-15-rtx3050-120hz-i5-11th-CID99-ID1ct6s1%",
        "title": "Lenovo IdeaPad Gaming 15 (i5-11320H + RTX 3050 + 120Hz / Holds 4h)",
        "price": 1400,
        "negotiable": True,
        "category": "budget-steals",
        "roiScore": 98,
        "cpu": "Intel Core i5-11320H",
        "cpuCores": "4C / 8T (10nm Tiger Lake, up to 4.5 GHz)",
        "cpuVsBaseline": 130,
        "cpuPercentText": "+30% Single-Core Boost",
        "gpu": "NVIDIA GeForce RTX 3050 4GB GDDR6",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650",
        "display": "15.6\" IPS 120 Hz FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Holds up to 4h ('bateria trzyma do 4 godzin')",
        "chassisGrade": "Lenovo Dual-Fan Stealth Chassis",
        "location": "Warszawa, Mazowieckie",
        "badge": { "type": "value", "text": "Lowest Entry Price (1,400 PLN)" },
        "highlights": "Unbeatable entry price: for only 1,400 PLN you get full Ampere RTX 3050 with hardware ray tracing and DLSS, 16GB RAM, 120Hz display, and a battery verified by seller to hold up to 4 hours.",
        "colorBar": "linear-gradient(90deg, #10b981, #f59e0b)"
    },

    # 14. ASUS ROG Zephyrus G14 - Ryzen 7 5800HS (8C/16T) + RTX 3050 + 2.5K 120Hz (1.7kg)
    {
        "url_pattern": "%asus-rog-zephyrus-g14-ryzen-7-5800hs-rtx-3050-16gb-512gb-14-2-5k-120hz-CID99-ID1bJgu0%",
        "title": "ASUS ROG Zephyrus G14 (8C/16T Zen 3 + 14\" 2.5K 120Hz / 1.7kg)",
        "price": 2300,
        "negotiable": True,
        "category": "ultraportable",
        "roiScore": 95,
        "cpu": "AMD Ryzen 7 5800HS",
        "cpuCores": "8C / 16T (7nm Zen 3 35W, up to 4.4 GHz)",
        "cpuVsBaseline": 300,
        "cpuPercentText": "+200% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3050 4GB (Dynamic Boost)",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650",
        "display": "14.0\" 16:9 2560x1440 (2.5K WQHD) 120 Hz IPS (100% DCI-P3, Pantone Validated)",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe PCIe SSD",
        "batteryHealth": "Excellent (76Wh battery, 8-9h office runtime)",
        "chassisGrade": "CNC Magnesium-Aluminum Honeycomb Alloy (1.7 kg)",
        "location": "Ostrowiec Świętokrzyski, Świętokrzyskie",
        "badge": { "type": "highlight", "text": "1.7kg Premium Ultrabook" },
        "highlights": "If portability, battery life, and build quality matter, nothing matches the Zephyrus G14. Weighs only 1.7kg, features a razor-sharp 2560x1440 100% DCI-P3 Pantone display, and yields 8+ hours off-charger thanks to 76Wh battery and 35W Zen 3 tuning.",
        "colorBar": "linear-gradient(90deg, #ec4899, #a855f7)"
    },

    # 15. HP Pavilion Gaming 15 - Ryzen 5 5600H (6C/12T) + RTX 3050 + 16GB
    {
        "url_pattern": "%laptop-gamingowy-hp-pavilion-15-ryzen-5-5600h-rtx-3050-16gb-ram-ssd-512gb-CID99-ID1cj2Si%",
        "title": "HP Pavilion Gaming 15 (Ryzen 5 5600H 6C/12T + RTX 3050 + 16GB)",
        "price": 1600,
        "negotiable": True,
        "category": "budget-steals",
        "roiScore": 95,
        "cpu": "AMD Ryzen 5 5600H",
        "cpuCores": "6C / 12T (7nm Zen 3, up to 4.2 GHz, 16MB Cache)",
        "cpuVsBaseline": 235,
        "cpuPercentText": "+135% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3050 4GB GDDR6",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650",
        "display": "15.6\" IPS FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Functional Used",
        "chassisGrade": "HP Dual-Fan Rear Exhaust",
        "location": "Żywiec, Śląskie",
        "badge": { "type": "value", "text": "Zen 3 6-Core @ 1,600" },
        "highlights": "High efficiency Zen 3 compute paired with RTX 3050. Operates virtually silently during regular browsing and coding workflows. Solid keyboard with full numpad.",
        "colorBar": "linear-gradient(90deg, #10b981, #38bdf8)"
    },

    # 16. Lenovo Legion 5 15ACH6H - Ryzen 5 5600H + RTX 3050 + 120Hz (PTM7950 Repaste)
    {
        "url_pattern": "%15ach6h-ryzen-5-5600h-rtx3050-16gb-ram-512ssd-fhd-120hz-ptm7950-CID99-ID1cCzNz%",
        "title": "Lenovo Legion 5 15ACH6H (Ryzen 5 5600H + RTX 3050 + PTM7950)",
        "price": 1900,
        "negotiable": True,
        "category": "legion-champions",
        "roiScore": 93,
        "cpu": "AMD Ryzen 5 5600H",
        "cpuCores": "6C / 12T (7nm Zen 3, up to 4.2 GHz)",
        "cpuVsBaseline": 235,
        "cpuPercentText": "+135% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3050 4GB (95W TGP + MUX Switch)",
        "gpuVsBaseline": 85,
        "gpuPercentText": "+37% vs GTX 1650",
        "display": "15.6\" IPS 120 Hz FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "512 GB NVMe SSD",
        "batteryHealth": "Good Condition",
        "chassisGrade": "Legion Coldfront 3.0 (Fresh PTM7950 Pad)",
        "location": "Tomaszów Mazowiecki, Łódzkie",
        "badge": { "type": "highlight", "text": "Legion Build + PTM7950" },
        "highlights": "Features Legion 5's top-tier chassis and keyboard, professionally serviced with industrial Honeywell PTM7950 phase-change pad. Offers supreme reliability and lower temps than entry Nitro 5.",
        "colorBar": "linear-gradient(90deg, #38bdf8, #10b981)"
    },

    # 17. Acer Nitro 5 - i5-11400H 6C/12T + RTX 3060 6GB + 144Hz + 750GB SSD
    {
        "url_pattern": "%acer-nitro-5-i5-11400h-rtx-3060-16gb-ram-ssd-750gb-144hz-rgb-nowa-pasta-CID99-ID1c69s1%",
        "title": "Acer Nitro 5 AN515-57 (i5-11400H 6C/12T + RTX 3060 6GB + 144Hz)",
        "price": 2000,
        "negotiable": True,
        "category": "sub-2000-titans",
        "roiScore": 95,
        "cpu": "Intel Core i5-11400H",
        "cpuCores": "6C / 12T (10nm Tiger Lake, up to 4.5 GHz)",
        "cpuVsBaseline": 230,
        "cpuPercentText": "+130% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB GDDR6",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 144 Hz FHD",
        "ram": "16 GB DDR4 3200MHz",
        "storage": "750 GB NVMe SSD (Dual M.2 + SATA)",
        "batteryHealth": "Good (Fresh Thermal Paste)",
        "chassisGrade": "Dual-Fan Quad Exhaust (Fresh Paste)",
        "location": "Ropczyce, Podkarpackie",
        "badge": { "type": "highlight", "text": "2,000 PLN Flat RTX 3060" },
        "highlights": "If staying within the Nitro ecosystem is desired, this AN515-57 generation is vastly superior to the older Nitro 7: 6-core 11th Gen CPU, RTX 3060 6GB, freshly repasted, 750GB storage, and 144Hz screen for 2,000 PLN flat.",
        "colorBar": "linear-gradient(90deg, #38bdf8, #06b6d4)"
    },

    # 18. MSI GL65 Leopard - i7-10750H (6C/12T) + RTX 3060 6GB + 24GB RAM
    {
        "url_pattern": "%laptop-msi-gl65-leopard-15-6-intel-core-i7-10750h-24gb-250gb-rtx3060-6gb-CID99-ID1bWWRM%",
        "title": "MSI GL65 Leopard (i7-10750H 6C/12T + RTX 3060 6GB + 24GB RAM)",
        "price": 2100,
        "negotiable": True,
        "category": "sub-2000-titans",
        "roiScore": 93,
        "cpu": "Intel Core i7-10750H",
        "cpuCores": "6C / 12T (up to 5.0 GHz, 12MB Cache)",
        "cpuVsBaseline": 175,
        "cpuPercentText": "+75% Multi-Core",
        "gpu": "NVIDIA GeForce RTX 3060 6GB GDDR6",
        "gpuVsBaseline": 165,
        "gpuPercentText": "+65% vs 1660 Ti (+166% vs 1650)",
        "display": "15.6\" IPS 144 Hz FHD",
        "ram": "24 GB DDR4 3200MHz (Upgraded)",
        "storage": "256 GB NVMe SSD",
        "batteryHealth": "Functional Used",
        "chassisGrade": "MSI Cooler Boost 5 (7 Heat Pipes)",
        "location": "Lublin, Lubelskie",
        "badge": { "type": "upgrade", "text": "24GB RAM + Cooler Boost" },
        "highlights": "Heavy-duty MSI Leopard with 7 copper heat pipes and 24GB installed RAM. Perfect for demanding memory loads, virtualization, and 1080p high-refresh gaming.",
        "colorBar": "linear-gradient(90deg, #f59e0b, #ef4444)"
    }
]

# Verify and extract OLX live URL and ID for each
matched_laptops = []
for lap in laptops:
    query = f'''
    SELECT source || ':' || external_id as id, location, url, description
    FROM offers
    WHERE url LIKE '{lap["url_pattern"]}'
    LIMIT 1
    '''
    row = c.execute(query).fetchone()
    if row:
        lap['id'] = row['id']
        lap['url'] = row['url']
        lap['raw_location'] = row['location']
        matched_laptops.append(lap)
    else:
        print(f"Warning: pattern {lap['url_pattern']} not matched.")

print(f"Successfully matched {len(matched_laptops)} / {len(laptops)} laptops.")

with open('scratch/master_power_laptops.json', 'w', encoding='utf-8') as f:
    json.dump(matched_laptops, f, ensure_ascii=False, indent=2)

print("Saved to scratch/master_power_laptops.json")
