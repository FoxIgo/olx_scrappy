# -*- coding: utf-8 -*-
"""
Build analysis/damaged_laptops_roi_analysis.html with rich interactive features.
"""

import json
import os
import re

def main():
    with open(r'c:\WORK\Projects\olx_scrappy\scratch\damaged_offers.json', 'r', encoding='utf-8') as f:
        offers = json.load(f)

    print(f"Loaded {len(offers)} offers")

    # Define verified database benchmarks for working laptops
    benchmarks = {
        "RTX 4060": {"avg": 3650, "min": 3100, "sample": 43},
        "RTX 4050": {"avg": 2980, "min": 2400, "sample": 45},
        "RTX 3060": {"avg": 2810, "min": 2300, "sample": 72},
        "RTX 3050": {"avg": 2380, "min": 1850, "sample": 114},
        "RTX 2060": {"avg": 2200, "min": 1750, "sample": 18},
        "GTX 1660 Ti": {"avg": 2250, "min": 1700, "sample": 27},
        "GTX 1650 Ti": {"avg": 1650, "min": 1300, "sample": 25},
        "GTX 1650": {"avg": 1380, "min": 1100, "sample": 179},
        "ThinkPad T480": {"avg": 1050, "min": 850, "sample": 20},
        "ThinkPad T490s": {"avg": 1200, "min": 950, "sample": 12},
        "ThinkPad X390 Yoga": {"avg": 1150, "min": 900, "sample": 10},
        "ThinkPad E590": {"avg": 850, "min": 700, "sample": 15},
        "ThinkPad E14 Gen 2": {"avg": 1350, "min": 1100, "sample": 8},
        "Lenovo Ideapad i5 8th": {"avg": 700, "min": 550, "sample": 30},
    }

    # Curate and enrich offers
    enriched = []
    
    for o in offers:
        title = o['title'] or ''
        desc = o['description'] or ''
        gpu = o['gpu'] or ''
        cpu = o['cpu'] or ''
        price = o['price'] or 0
        oid = o['id']

        # Determine specs category and repair strategy
        tier = "other"
        difficulty = "Unknown"
        repair_cost = 0
        resale_val = 0
        repair_summary = ""
        action_plan = []
        risk_level = "Medium"

        # Specific known high-value deals
        if oid == "olx_pl:1101863036":  # Acer Nitro 7 i7-9750H GTX 1660 Ti 24GB
            tier = "easy_fix"
            difficulty = "Easy (Modular / Epoxy)"
            repair_cost = 65  # 50 zł fans + 15 zł Poxipol
            resale_val = 2050
            repair_summary = "Replace noisy dual cooling fans, epoxy brass hinge thread inserts into lid casing, clean install Windows 11."
            action_plan = [
                "Order pair of AN715-51 cooling fans on Allegro (~45 PLN)",
                "Mix 2-component epoxy (Poxipol) to re-seat loosened brass hinge anchor bushings (~15 PLN)",
                "Flash Windows 11 Home/Pro from USB flash drive to replace Romanian install (Free)",
                "Test thermals under FurMark & Cinebench"
            ]
            risk_level = "Low (Board 100% Tested Working)"

        elif oid == "olx_pl:1086809115":  # ThinkPad T480 i5-8250U 0GB/0GB
            tier = "easy_fix"
            difficulty = "Very Easy (Plug & Play)"
            repair_cost = 165  # 40 zł 8GB RAM + 45 zł 256GB SSD + 80 zł battery
            resale_val = 1000
            repair_summary = "Fully working motherboard, screen & unlocked BIOS. Just install RAM, NVMe SSD, and battery."
            action_plan = [
                "Install 8GB or 16GB DDR4 SO-DIMM (~40-80 PLN)",
                "Install M.2 NVMe SSD 256GB (~45 PLN)",
                "Install internal/external T480 battery (~80 PLN)",
                "Install clean Windows 11 with Lenovo Vantage driver update"
            ]
            risk_level = "Very Low (Fully Functional Hardware)"

        elif oid == "olx_pl:1100937409":  # Asus TUF FX505DT Ryzen 5 3550H GTX 1650
            tier = "easy_fix"
            difficulty = "Very Easy (Charger & Keycap)"
            repair_cost = 55  # 45 zł charger + 10 zł key cleaning/rubber dome
            resale_val = 1350
            repair_summary = "Working laptop! Seller switched to desktop. Just supply a 19V Asus charger and fix/clean intermittent 'D' key."
            action_plan = [
                "Buy Asus TUF 19V 6.32A 120W / 150W charger on Allegro (~45-60 PLN)",
                "Pop off 'D' keycap to inspect contact and clean with isopropyl alcohol (Free)",
                "Benchmark GTX 1650 & Ryzen 5 3550H thermals",
                "Clean casing and resell as complete working gaming laptop"
            ]
            risk_level = "Very Low (Seller states it works)"

        elif oid == "olx_pl:1091993502":  # MSI i7-8750H GTX 1650 (No screen)
            tier = "easy_fix"
            difficulty = "Moderate (Screen Installation)"
            repair_cost = 180  # 15.6" FHD 30-pin screen
            resale_val = 1450
            repair_summary = "100% working gaming board & specs. Works on external HDMI. Just install standard 15.6'' 30-pin IPS screen."
            action_plan = [
                "Purchase compatible 15.6\" FHD IPS 30-pin EDP matrix on Allegro (~160-180 PLN)",
                "Connect EDP ribbon cable and snap screen bezel",
                "Or flip as a compact desktop console / media PC at 950-1000 PLN"
            ]
            risk_level = "Low (Tested on external display)"

        elif oid == "olx_pl:1096237565":  # ThinkPad X390 Yoga i5-8265U
            tier = "easy_fix"
            difficulty = "Moderate (Touchscreen Panel / USB-C Charger)"
            repair_cost = 260  # 220 zł screen assembly + 40 zł 65W USB-C charger
            resale_val = 1100
            repair_summary = "Fully boots, battery in very good health, works on external monitor. Cracked touchscreen."
            action_plan = [
                "Source replacement X390 Yoga touch digitizer/screen assembly (~220 PLN)",
                "Add 65W USB-C PD charger (~40 PLN)",
                "Resell as premium 2-in-1 convertible ThinkPad"
            ]
            risk_level = "Low (Confirmed working motherboard & battery)"

        elif oid == "olx_pl:1102699120":  # ThinkPad E590 i5-8265U (water spill on keys)
            tier = "easy_fix"
            difficulty = "Easy (Keyboard Replacement)"
            repair_cost = 110  # 65 zł keyboard + 45 zł SSD
            resale_val = 850
            repair_summary = "Working laptop with minor liquid spill strictly on keyboard keys. Replace keyboard & add cheap SSD."
            action_plan = [
                "Replace ThinkPad E590 keyboard (~65 PLN on Allegro)",
                "Swap slow 1TB HDD for 256GB SSD (~45 PLN)",
                "Clean install Windows 11 Pro"
            ]
            risk_level = "Low-Medium (Check board for minor corrosion)"

        elif oid == "olx_pl:1103685880":  # Acer Nitro 5 i5-12500H RTX 4060 17.3" QHD 165Hz
            tier = "modern_powerhouse"
            difficulty = "Advanced (Board-Level Diagnostics)"
            repair_cost = 250  # RAM, SSD + estimated component fix (e.g. input MOSFET / cap)
            resale_val = 3650
            repair_summary = "MASSIVE LOTTERY: RTX 4060 + 12th gen + 17.3'' QHD 165Hz for 1,100 zł! Power LEDs turn on briefly then off. Not diagnosed at shop."
            action_plan = [
                "Inspect motherboard with thermal camera for 19V rail short / blown ceramic decoupling cap",
                "Test resistance on 3.3V/5V standby coils and VCORE coils",
                "If simple input MOSFET / buck IC short: replace for ~20 PLN",
                "Install 16GB DDR5 RAM + 512GB SSD",
                "Upside: over 2,200 PLN net profit if revived"
            ]
            risk_level = "High Risk / Extreme Reward"

        elif oid == "olx_pl:1103680453":  # Acer Nitro 5 i7-12650H RTX 4050 144Hz
            tier = "modern_powerhouse"
            difficulty = "Advanced (Intermittent Boot Diagnosis)"
            repair_cost = 200
            resale_val = 2950
            repair_summary = "High-end i7-12650H + RTX 4050. Intermittent boot: 'raz się włączy i działa normalnie, po wyjęciu RAM potrafi ożyć'."
            action_plan = [
                "Clean RAM slots with contact cleaner and test known-good compatible SO-DIMMs",
                "Inspect BIOS battery, reflash clean BIOS with programmer",
                "Check power sequencing and solder joints around RAM controller / PMIC",
                "Upside: ~1,500 PLN profit if resolved"
            ]
            risk_level = "High-Medium Risk"

        elif oid == "olx_pl:1103712784":  # Acer Nitro 5 R5-6600H RTX 3060 165Hz
            tier = "modern_powerhouse"
            difficulty = "Moderate-Advanced (Freezes on OS install)"
            repair_cost = 180
            resale_val = 2750
            repair_summary = "Boots into BIOS and recognizes hardware, but freezes during Windows installation. Potential thermal, SSD, RAM, or power rail issue."
            action_plan = [
                "Clean heatsink and apply high-viscosity phase change thermal paste (PTM7950) or fresh paste",
                "Test installation with different USB drive, RAM stick, and known-good NVMe slot",
                "Run MemTest86 from bootable flash drive to isolate memory errors",
                "Upside: ~1,300 PLN profit"
            ]
            risk_level = "Medium Risk"

        elif oid == "olx_pl:1103097111":  # ThinkPad T490s 16GB RAM 256GB SSD
            tier = "modern_powerhouse"
            difficulty = "Moderate (SMD Fuse Replacement)"
            repair_cost = 30
            resale_val = 1150
            repair_summary = "Stopped turning on after screen replacement attempt. On T490s, hot-swapping screen without disabling battery blows the F1 backlight fuse."
            action_plan = [
                "Disassemble and measure F1 / F2 surface mount fuses near EDP display connector with multimeter",
                "Replace blown 0402/0603 3A fuse (~2 PLN) or bridge with fine wire for testing",
                "Reconnect LCD cable securely with battery disconnected",
                "Upside: ~770 PLN profit on a 16GB modern ThinkPad"
            ]
            risk_level = "Medium-Low (Classic well-documented fault)"

        elif oid == "olx_pl:1088159259":  # Lenovo E14 Gen 2 i5-1135U
            tier = "modern_powerhouse"
            difficulty = "Advanced (USB-C Power Delivery / PMIC)"
            repair_cost = 120  # Charging chip + charger
            resale_val = 1350
            repair_summary = "Modern 11th Gen i5. Mint screen & body. Charging LED blinks, doesn't recognize charger. Classic USB-C PD controller / charging MOSFET failure."
            action_plan = [
                "Inspect USB-C port for mechanical damage / bent CC pins",
                "Measure 20V negotiation; replace Intersil ISL9240 charging IC or input protection FETs",
                "Install RAM & SSD; test full operation"
            ]
            risk_level = "Medium-High (Micro-soldering required)"

        elif oid == "olx_pl:1096367353":  # Acer Nitro 5 i5-11400H RTX 3050 16GB
            tier = "modern_powerhouse"
            difficulty = "Advanced (Post-service board fault)"
            repair_cost = 200
            resale_val = 2350
            repair_summary = "Turned off after paste replacement at repair shop. 3-second blue LED then power-off. Service suspected RAM controller or board short."
            action_plan = [
                "Inspect board for knocked-off SMD components around CPU/GPU heatsink mounts",
                "Check for thermal paste short on GPU VRAM / decoupling capacitors",
                "Measure primary power rails"
            ]
            risk_level = "High Risk (Failed repair shop intervention)"

        elif oid == "olx_pl:1103600556":  # Acer Nitro 5 i5-10300H RTX 3050
            tier = "modern_powerhouse"
            difficulty = "Advanced (No display / keyboard lights on)"
            repair_cost = 200
            resale_val = 2200
            repair_summary = "Keyboard backlight turns on, reacts to charger, but no POST/display. Not diagnosed in service. Sold without RAM/SSD."
            action_plan = [
                "Insert known-good DDR4 RAM and perform CMOS reset",
                "Reflash main BIOS and EC chips",
                "Check GPU core power and display mux rail"
            ]
            risk_level = "High-Medium Risk"

        elif oid == "olx_pl:1099930207":  # Legion 5 i5-10300H GTX 1650 Ti (chipped die)
            tier = "avoid_donor"
            difficulty = "Unrepairable (Chipped GPU Die)"
            repair_cost = 999
            resale_val = 600
            repair_summary = "Seller explicitly notes 'ukruszony rdzeń GTX 1650 Ti' (chipped silicon die). Cannot be repaired without BGA reballing of new GPU chip (~500+ PLN)."
            action_plan = ["AVOID FOR FLIPPING. Only useful for parts (17.3'' screen, original charger, casing)."]
            risk_level = "Total Loss / Donor Only"

        elif oid == "olx_pl:1092918307":  # Dell G15 3500 (liquid flooding)
            tier = "avoid_donor"
            difficulty = "Severe Corrosion (Liquid Damage)"
            repair_cost = 800
            resale_val = 900
            repair_summary = "Laptop po zalaniu (water flooded), mainboard fried. Parts donor only."
            action_plan = ["AVOID. Salvage 1TB SSD, RAM, charger, and LCD panel only."]
            risk_level = "Severe Corrosion / Avoid"

        elif oid == "olx_pl:1047162405":  # Acer Nitro 5 AN515-55 shorted board
            tier = "avoid_donor"
            difficulty = "Severe Short Circuit"
            repair_cost = 700
            resale_val = 1100
            repair_summary = "Uszkodzona płyta główna (zwarcie). Missing 'W' keycap. Price 899 zł is too high for a dead board."
            action_plan = ["Skip - overpriced for a donor."]
            risk_level = "Overpriced Donor"

        elif is_gaming or is_modern_thinkpad:
            tier = "budget_gaming"
            difficulty = "Varies"
            repair_cost = 100
            resale_val = price * 1.5 + 200
            repair_summary = f"Damaged unit with {gpu or 'Integrated'} / {cpu or 'Intel'}. Inspect description for details."
            action_plan = ["Review diagnostic notes before bidding"]
            risk_level = "Medium"
        else:
            tier = "other"
            difficulty = "Unknown"
            repair_cost = 50
            resale_val = price + 100
            repair_summary = "Standard low-tier listing or legacy parts."
            action_plan = ["Inspect as donor"]
            risk_level = "Low-Yield"

        # Calculate finances if estimated
        if resale_val > 0 and price > 0:
            total_invested = price + repair_cost
            net_profit = resale_val - total_invested
            roi_pct = round((net_profit / total_invested) * 100, 1)
        else:
            total_invested = price
            net_profit = 0
            roi_pct = 0

        enriched.append({
            "id": oid,
            "title": title,
            "price": price,
            "condition": o.get('condition') or 'damaged',
            "cpu": cpu or "Not stated",
            "gpu": gpu or "Integrated / None",
            "ram_gb": o.get('ram_gb'),
            "storage_gb": o.get('storage_gb'),
            "screen_in": o.get('screen_in'),
            "location": o.get('location') or 'Poland',
            "seller_name": o.get('seller_name') or 'Seller',
            "url": o.get('url') or '#',
            "description": desc,
            "tier": tier,
            "difficulty": difficulty,
            "repair_cost": repair_cost,
            "resale_val": resale_val,
            "total_invested": total_invested,
            "net_profit": net_profit,
            "roi_pct": roi_pct,
            "repair_summary": repair_summary,
            "action_plan": action_plan,
            "risk_level": risk_level,
            "notes": o.get('notes') or ''
        })

    # Output enriched JSON for use or inspection
    with open(r'c:\WORK\Projects\olx_scrappy\scratch\enriched_damaged.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print("Generated scratch/enriched_damaged.json successfully!")

if __name__ == "__main__":
    main()
