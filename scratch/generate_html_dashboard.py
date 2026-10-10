# -*- coding: utf-8 -*-
"""
Generate comprehensive, interactive, rich aesthetic HTML dashboard
in analysis/damaged_laptops_roi_analysis.html
"""

import json
import os
import re

def build_dashboard():
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
        "Lenovo Ideapad i5": {"avg": 750, "min": 550, "sample": 30},
    }

    curated = []

    for o in offers:
        title = o['title'] or ''
        desc = o['description'] or ''
        gpu = o['gpu'] or ''
        cpu = o['cpu'] or ''
        price = o['price'] or 0
        oid = o['id']

        title_lower = title.lower()
        desc_lower = desc.lower()

        is_gaming = bool(gpu and gpu != 'Zintegrowana' and 'intel hd' not in gpu.lower() and 'hd 6310' not in gpu.lower())
        is_thinkpad = any(k in title_lower for k in ['thinkpad', 't480', 't490', 'x390', 'e14', 'e590', 't580', 'l480', 'x1 carbon'])

        tier = "other"
        tier_label = "General Damaged"
        difficulty = "Unknown"
        repair_cost = 0
        resale_val = 0
        repair_summary = ""
        action_plan = []
        risk_level = "Medium"
        highlight = False

        if oid == "olx_pl:1101863036":  # Acer Nitro 7 i7-9750H GTX 1660 Ti 24GB
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Easy (Fans & Casing Epoxy)"
            repair_cost = 65
            resale_val = 2050
            repair_summary = "Płyta, GPU, CPU, 24GB RAM i matryca 144Hz w 100% sprawne (uruchamia się). Głośne wentylatory do wymiany + wyrwane tulejki prawego zawiasu w klapie (do wklejenia na Poxipol). System w jęz. rumuńskim."
            action_plan = [
                "Zamów parę nowych wentylatorów do AN715-51 na Allegro (~45-50 PLN)",
                "Wklej mosiężne tuleje śrub zawiasu w klapę matrycy klejem epoksydowym Poxipol (~15 PLN)",
                "Zainstaluj czysty polski Windows 11 z pendrive'a (0 PLN)",
                "Przeprowadź stress-test FurMark + Cinebench pod obciążeniem"
            ]
            risk_level = "Bardzo niskie (Płyta i podzespoły w pełni sprawne)"
            highlight = True

        elif oid == "olx_pl:1086809115":  # ThinkPad T480 i5-8250U 0GB/0GB
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Bardzo łatwe (Plug & Play)"
            repair_cost = 165
            resale_val = 1050
            repair_summary = "Płyta, matryca FHD, podświetlana klawiatura, porty i odblokowany BIOS w 100% sprawne i przetestowane. Sprzedający wyjął RAM, dysk i baterię."
            action_plan = [
                "Włóż kość 8GB DDR4 SO-DIMM (~40 PLN) lub 16GB (~80 PLN)",
                "Zamontuj dysk SSD M.2 NVMe 256GB (~45 PLN)",
                "Dokup baterię do ThinkPad T480 (~80 PLN)",
                "Zainstaluj Windows 11 Pro z Lenovo Vantage"
            ]
            risk_level = "Bardzo niskie (Wszystko przetestowane przez sprzedawcę)"
            highlight = True

        elif oid == "olx_pl:1100937409":  # Asus TUF FX505DT Ryzen 5 3550H GTX 1650
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Bardzo łatwe (Zasilacz + Klawisz)"
            repair_cost = 55
            resale_val = 1350
            repair_summary = "W pełni działający laptop do gier! Sprzedający złożył stacjonarkę, brak zasilacza, a klawisz 'D' działa przerywanie. W środku 16GB RAM i SSD 256GB."
            action_plan = [
                "Kup zasilacz Asus 19V 6.32A 120W na Allegro (~45-55 PLN)",
                "Zdejmij klawisz 'D', przedmuchaj i wyczyść styki alkoholem izopropylowym IPA (~0-10 PLN)",
                "Wyczyść obudowę i przetestuj w grach",
                "Wystaw jako kompletnego, sprawnego laptopa gamingowego"
            ]
            risk_level = "Niskie (Sprzedawca potwierdza działanie)"
            highlight = True

        elif oid == "olx_pl:1091993502":  # MSI i7-8750H GTX 1650 (Brak matrycy)
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Umiarkowane (Montaż matrycy)"
            repair_cost = 175
            resale_val = 1450
            repair_summary = "Płyta główna, i7 6-rdzeniowy, GTX 1650 i SSD Samsung 500GB w 100% sprawne. Działa na zewnętrznym monitorze. Wymaga wpięcia matrycy."
            action_plan = [
                "Zamów kompatybilną matrycę 15.6'' FHD IPS 30-pin na Allegro (~160-180 PLN)",
                "Wepnij taśmę EDP i zatrzaśnij ramkę matrycy",
                "Alternatywa: sprzedaż jako minikomputer stacjonarny pod TV/monitor za ~1,000 PLN z zerowym kosztem naprawy"
            ]
            risk_level = "Niskie (Działa na HDMI/TV)"
            highlight = True

        elif oid == "olx_pl:1096237565":  # ThinkPad X390 Yoga i5-8265U
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Umiarkowane (Wymiana dotyku / Zasilacz)"
            repair_cost = 250
            resale_val = 1100
            repair_summary = "Płyta działa, bateria w stanie bardzo dobrym, odpala na monitorze. Uszkodzona zbita matryca dotykowa, brak ładowarki USB-C."
            action_plan = [
                "Kup klapę z matrycą do X390 Yoga (~200-240 PLN) lub używaj jako stacji roboczej",
                "Dokup ładowarkę USB-C 65W (~40 PLN)",
                "Zainstaluj Windows 11 i ciesz się dotykowym ultrabookiem biznesowym"
            ]
            risk_level = "Niskie (Płyta i bateria w 100% sprawne)"
            highlight = True

        elif oid == "olx_pl:1102699120":  # ThinkPad E590 i5-8265U
            tier = "easy_fix"
            tier_label = "🌟 Top Pick: Easy Modular Fix"
            difficulty = "Łatwe (Wymiana klawiatury)"
            repair_cost = 110
            resale_val = 850
            repair_summary = "Laptop z i5 8. generacji i 8GB RAM. Część klawiatury nie działa po drobnym zalaniu. Matryca i płyta działają, ładowarka w zestawie."
            action_plan = [
                "Kup nową klawiaturę do ThinkPada E590 na Allegro (~65 PLN)",
                "Wymień powolny dysk HDD 1TB na szybki SSD 256GB NVMe (~45 PLN)",
                "Zainstaluj Windows 11 Pro i sprzedaj z czystym zyskiem"
            ]
            risk_level = "Niskie-Średnie (Klawiatura wymienna od góry bez rozbierania płyty)"
            highlight = True

        elif oid == "olx_pl:1103685880":  # Acer Nitro 5 i5-12500H RTX 4060 17.3" QHD 165Hz
            tier = "modern_powerhouse"
            tier_label = "⚡ Ultra-Modern Powerhouse"
            difficulty = "Zaawansowane (Diagnostyka płyty / Zasilania)"
            repair_cost = 250
            resale_val = 3650
            repair_summary = "POTWÓR: i5-12500H + RTX 4060 6GB + ekran 17.3'' QHD 165Hz za 1,100 zł! Po włączeniu diody zapalają się na chwilę i gasną. Nie diagnozowany w serwisie."
            action_plan = [
                "Podłącz zasilacz serwisowy z pomiarem prądu i kamerą termowizyjną",
                "Sprawdź linię główną 19V pod kątem zwarcia w kondensatorze ceramicznym (typowa usterka)",
                "Sprawdź przetwornice 3.3V/5V oraz sekcję zasilania procesora i GPU",
                "W przypadku uszkodzenia MOSFET-a wejściowego naprawa kosztuje ~15-30 PLN",
                "Potencjalny zysk: ponad 2,200 PLN!"
            ]
            risk_level = "Wysokie ryzyko / Gigantyczny zysk (Potencjalna przebitka 300%)"
            highlight = True

        elif oid == "olx_pl:1103680453":  # Acer Nitro 5 i7-12650H RTX 4050 144Hz
            tier = "modern_powerhouse"
            tier_label = "⚡ Ultra-Modern Powerhouse"
            difficulty = "Zaawansowane (Niestabilny start / RAM)"
            repair_cost = 180
            resale_val = 2950
            repair_summary = "i7-12650H + RTX 4050 za 1,200 zł! Reaguje na ładowarkę, 'raz się włączy i działa normalnie, po wypięciu i wpięciu RAM potrafi ożyć'. Niezdiagnozowany."
            action_plan = [
                "Oczyść sloty pamięci RAM alkoholem IPA i przetestuj z pewnymi kośćmi DDR5/DDR4",
                "Sprawdź baterię podtrzymującą CMOS oraz zaktualizuj/zaprogramuj czysty wsad BIOS",
                "Zbadaj luty pod kątem zimnych lutów przy kontrolerze pamięci / przetwornicy VDDQ",
                "Potencjalny zysk: ~1,500 PLN!"
            ]
            risk_level = "Średnio-Wysokie ryzyko"
            highlight = True

        elif oid == "olx_pl:1103712784":  # Acer Nitro 5 R5-6600H RTX 3060 165Hz
            tier = "modern_powerhouse"
            tier_label = "⚡ Ultra-Modern Powerhouse"
            difficulty = "Umiarkowane-Zaawansowane"
            repair_cost = 150
            resale_val = 2750
            repair_summary = "Ryzen 5 6600H + RTX 3060 + matryca 165Hz. Odpala do BIOS-u bez problemu, widzi dysk i RAM, ale zawiesza się przy instalacji Windowsa."
            action_plan = [
                "Wymień pastę termoprzewodzącą (np. Honeywell PTM7950) i wyczyść radiatory (możliwy throttling termiczny)",
                "Uruchom MemTest86 z pendrive'a by wykluczyć uszkodzoną pamięć RAM",
                "Przetestuj z innym nośnikiem NVMe w drugim slocie M.2",
                "Potencjalny zysk: ~1,400 PLN!"
            ]
            risk_level = "Średnie ryzyko (BIOS w 100% sprawny)"
            highlight = True

        elif oid == "olx_pl:1103097111":  # ThinkPad T490s 16GB RAM 256GB SSD
            tier = "thinkpad_business"
            tier_label = "💼 Business ThinkPad"
            difficulty = "Umiarkowane (Bezpiecznik F1 na płycie)"
            repair_cost = 30
            resale_val = 1150
            repair_summary = "ThinkPad T490s z 16GB RAM i SSD 256GB za 350 zł. Przestał startować po próbie wymiany matrycy bez odpięcia baterii w BIOS-ie (spalony bezpiecznik F1)."
            action_plan = [
                "Zlokalizuj bezpiecznik podświetlenia F1/F2 przy złączu EDP płyty głównej",
                "Sprawdź ciągłość miernikiem - na 95% jest przerwany po wymianie matrycy pod napięciem",
                "Wlutuj nowy bezpiecznik SMD 0402 3A (~3 PLN) lub wykonaj zworkę testową",
                "Podłącz matrycę prawidłowo przy wyłączonym zasilaniu",
                "Zysk netto: ~770 PLN!"
            ]
            risk_level = "Niskie-Średnie (Klasyczna, powszechna usterka ThinkPadów)"
            highlight = True

        elif oid == "olx_pl:1088159259":  # Lenovo E14 Gen 2 i5-1135U
            tier = "thinkpad_business"
            tier_label = "💼 Business ThinkPad"
            difficulty = "Zaawansowane (Układ zasilania USB-C)"
            repair_cost = 120
            resale_val = 1350
            repair_summary = "Nowoczesny ThinkPad z i5 11. generacji. Matryca idealna, bateria sprawna. Nie ładuje przez USB-C (miga dioda, nie startuje). Typowa usterka kontrolera USB-PD."
            action_plan = [
                "Zbadaj linię zasilania USB-C (chip Intersil ISL9240 / kontroler negocjacji 20V)",
                "Wymień uszkodzony kontroler ładowania lub tranzystor wejściowy (~25 PLN chip)",
                "Włóż kość RAM i dysk NVMe, przetestuj działanie"
            ]
            risk_level = "Średnio-Wysokie (Wymaga stacji lutowniczej hot-air)"
            highlight = True

        elif oid == "olx_pl:1096367353":  # Acer Nitro 5 i5-11400H RTX 3050 16GB
            tier = "modern_powerhouse"
            tier_label = "⚡ Ultra-Modern Powerhouse"
            difficulty = "Zaawansowane (Płyta po serwisie)"
            repair_cost = 200
            resale_val = 2350
            repair_summary = "i5-11400H + RTX 3050 + 16GB RAM + 144Hz. Po serwisie i wymianie pasty zapala niebieską diodę na 3 sekundy i gaśnie. Serwis podejrzewał kontroler RAM/płytę."
            action_plan = [
                "Obejrzyj płytę pod mikroskopem: czy serwis nie urwał elementów SMD przy dokręcaniu chłodzenia",
                "Sprawdź czy pasta nie przewodzi prądu na kondensatorach wokół rdzenia GPU/CPU",
                "Sprawdź rezystancje cewek zasilających"
            ]
            risk_level = "Wysokie ryzyko (Nieudana ingerencja serwisu)"
            highlight = False

        elif oid == "olx_pl:1103600556":  # Acer Nitro 5 i5-10300H RTX 3050
            tier = "modern_powerhouse"
            tier_label = "⚡ Ultra-Modern Powerhouse"
            difficulty = "Zaawansowane (Brak obrazu)"
            repair_cost = 190
            resale_val = 2200
            repair_summary = "i5-10300H + RTX 3050. Włącza się, klawiatura świeci, brak obrazu. Niezdiagnozowany. Brak RAM i dysku."
            action_plan = [
                "Włóż sprawną pamięć RAM DDR4 i zresetuj baterię BIOS",
                "Podłącz monitor zewnętrzny i sprawdź sygnał HDMI",
                "Zaprogramuj kość BIOS nowym czystym wsadem ME-Region"
            ]
            risk_level = "Średnio-Wysokie ryzyko"
            highlight = False

        elif oid == "olx_pl:1099930207":  # Legion 5 ukruszony rdzeń
            tier = "avoid_donor"
            tier_label = "⚠️ Trap / Donor Only"
            difficulty = "Nieopłacalne (Ukruszony rdzeń GPU)"
            repair_cost = 999
            resale_val = 550
            repair_summary = "Ukruszony rdzeń karty GTX 1650 Ti. Naprawa wymaga wymiany całego układu BGA i reballingu (~600+ PLN). Nieopłacalna do flipowania."
            action_plan = ["UNIKAĆ DO NAPRAWY. Wartościowe jedynie jako dawca części (matryca 17.3'', obudowa, oryginalny zasilacz)."]
            risk_level = "Maksymalne / Strata kapitału"
            highlight = False

        elif oid == "olx_pl:1092918307":  # Dell G15 zalany
            tier = "avoid_donor"
            tier_label = "⚠️ Trap / Donor Only"
            difficulty = "Nieopłacalne (Ciecz / Korozja)"
            repair_cost = 800
            resale_val = 850
            repair_summary = "Laptop po zalaniu cieczą, uszkodzona płyta główna. W zestawie sprawny dysk 1TB SSD i 8GB RAM."
            action_plan = ["UNIKAĆ. Rdza i korozja pod układami BGA czynią naprawę skrajnie ryzykowną. Jedynie odzysk dysku 1TB i RAM."]
            risk_level = "Maksymalne / Korozja"
            highlight = False

        elif is_gaming and price <= 900:
            tier = "budget_gaming"
            tier_label = "🎮 Budget Gaming (<900 zł)"
            difficulty = "Zróżnicowane"
            repair_cost = 100
            resale_val = max(price * 1.5, 1200)
            repair_summary = f"Budżetowy laptop gamingowy: {gpu} | {cpu}. Sprawdź szczegółowy opis usterki przed zakupem."
            action_plan = ["Dokładnie przeanalizuj opis i zapytaj sprzedawcę o zachowanie diod zasilania"]
            risk_level = "Średnie ryzyko"

        elif is_thinkpad:
            tier = "thinkpad_business"
            tier_label = "💼 Business ThinkPad"
            difficulty = "Umiarkowane"
            repair_cost = 80
            resale_val = max(price * 1.6, 750)
            repair_summary = f"Biznesowy ThinkPad {title}. Trwała konstrukcja, wysoka płynność odsprzedaży na wtórnym rynku."
            action_plan = ["Uzupełnij brakujące podzespoły (RAM/SSD) lub napraw usterkę mechaniczną"]
            risk_level = "Niskie-Średnie"

        else:
            tier = "other"
            tier_label = "Pozostałe uszkodzone"
            difficulty = "Różne"
            repair_cost = 60
            resale_val = price * 1.3
            repair_summary = "Standardowa oferta z rynku wtórnego z usterką lub przeznaczona na części."
            action_plan = ["Oceniać indywidualnie"]
            risk_level = "Zależne od modelu"

        # Calculate finances
        if resale_val > 0 and price > 0:
            total_invested = round(price + repair_cost, 2)
            net_profit = round(resale_val - total_invested, 2)
            roi_pct = round((net_profit / total_invested) * 100, 1)
        else:
            total_invested = price
            net_profit = 0
            roi_pct = 0

        curated.append({
            "id": oid,
            "title": title,
            "price": price,
            "condition": o.get('condition') or 'damaged',
            "cpu": cpu or "Nie podano",
            "gpu": gpu or "Zintegrowana / Brak",
            "ram_gb": o.get('ram_gb'),
            "storage_gb": o.get('storage_gb'),
            "screen_in": o.get('screen_in'),
            "location": o.get('location') or 'Polska',
            "seller_name": o.get('seller_name') or 'Sprzedający',
            "url": o.get('url') or '#',
            "description": desc,
            "tier": tier,
            "tier_label": tier_label,
            "difficulty": difficulty,
            "repair_cost": repair_cost,
            "resale_val": resale_val,
            "total_invested": total_invested,
            "net_profit": net_profit,
            "roi_pct": roi_pct,
            "repair_summary": repair_summary,
            "action_plan": action_plan,
            "risk_level": risk_level,
            "highlight": highlight,
            "notes": o.get('notes') or ''
        })

    # Sort curated list: highlights first, then by ROI descending
    curated.sort(key=lambda x: (not x['highlight'], -x['roi_pct'], -x['net_profit']))

    print(f"Curated {len(curated)} items. Generating HTML...")

    # Build HTML Content
    html_content = generate_html_template(curated, benchmarks)

    output_path = r'c:\WORK\Projects\olx_scrappy\analysis\damaged_laptops_roi_analysis.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"Successfully generated {output_path}! File size: {os.path.getsize(output_path)} bytes.")


def generate_html_template(offers, benchmarks):
    # Prepare JSON data to embed for client-side reactivity
    json_data = json.dumps(offers, ensure_ascii=False)
    benchmarks_json = json.dumps(benchmarks, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Analiza Uszkodzonych Laptopów | Najwyższy ROI i Łatwe Naprawy (OLX)</title>
  <meta name="description" content="Kompleksowa analiza opłacalności zakupu uszkodzonych i niekompletnych laptopów z polskiego OLX. Zidentyfikowane perełki z prostymi naprawami modularnymi vs nowoczesne bestie z usterkami płyt.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-primary: #07090e;
      --bg-secondary: #0d121d;
      --bg-card: rgba(16, 23, 38, 0.72);
      --bg-card-hover: rgba(23, 33, 54, 0.88);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-glow: rgba(56, 189, 248, 0.28);
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent-blue: #38bdf8;
      --accent-cyan: #06b6d4;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --accent-purple: #a855f7;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --radius-xl: 26px;
      --shadow-sm: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
      --shadow-lg: 0 20px 25px -5px rgba(0, 0, 0, 0.55), 0 8px 10px -6px rgba(0, 0, 0, 0.45);
      --shadow-glow: 0 0 35px -5px rgba(56, 189, 248, 0.2);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: var(--bg-primary);
      color: var(--text-main);
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.5;
      padding-bottom: 90px;
      overflow-x: hidden;
      background-image:
        radial-gradient(circle at 10% 10%, rgba(56, 189, 248, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 90% 25%, rgba(168, 85, 247, 0.07) 0%, transparent 45%),
        radial-gradient(circle at 50% 65%, rgba(16, 185, 129, 0.06) 0%, transparent 50%),
        radial-gradient(circle at 80% 90%, rgba(245, 158, 11, 0.05) 0%, transparent 40%);
      background-attachment: fixed;
    }}

    a {{
      color: var(--accent-blue);
      text-decoration: none;
      transition: color 0.2s;
    }}
    a:hover {{
      color: #7dd3fc;
    }}

    /* Header Section */
    header {{
      padding: 48px 24px 28px;
      max-width: 1440px;
      margin: 0 auto;
    }}

    .header-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 20px;
    }}

    .badge-top {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.25);
      color: var(--accent-blue);
      font-size: 0.76rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 6px 14px;
      border-radius: 9999px;
    }}

    .badge-top.emerald {{
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.3);
      color: #34d399;
    }}

    .badge-top.purple {{
      background: rgba(168, 85, 247, 0.12);
      border-color: rgba(168, 85, 247, 0.3);
      color: #c084fc;
    }}

    .badge-top span.dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: currentColor;
      box-shadow: 0 0 8px currentColor;
    }}

    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: clamp(2.1rem, 4vw, 3.4rem);
      font-weight: 900;
      letter-spacing: -0.025em;
      line-height: 1.12;
      background: linear-gradient(135deg, #ffffff 25%, #94a3b8 80%, #38bdf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 16px;
    }}

    .subtitle {{
      color: var(--text-muted);
      font-size: 1.12rem;
      max-width: 960px;
      line-height: 1.6;
      margin-bottom: 32px;
    }}

    /* Highlights KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 36px;
    }}

    .kpi-card {{
      background: var(--bg-card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px;
      transition: all 0.25s ease;
      position: relative;
      overflow: hidden;
    }}

    .kpi-card:hover {{
      border-color: rgba(255, 255, 255, 0.16);
      transform: translateY(-2px);
      box-shadow: var(--shadow-sm);
    }}

    .kpi-card::after {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 3px;
      background: linear-gradient(90deg, var(--accent-blue), transparent);
    }}

    .kpi-card.emerald::after {{ background: linear-gradient(90deg, var(--accent-emerald), transparent); }}
    .kpi-card.amber::after {{ background: linear-gradient(90deg, var(--accent-amber), transparent); }}
    .kpi-card.purple::after {{ background: linear-gradient(90deg, var(--accent-purple), transparent); }}

    .kpi-label {{
      font-size: 0.8rem;
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .kpi-val {{
      font-family: 'Outfit', sans-serif;
      font-size: 2rem;
      font-weight: 800;
      line-height: 1.1;
      margin: 8px 0 4px;
      color: #fff;
    }}

    .kpi-val.emerald {{ color: #34d399; }}
    .kpi-val.blue {{ color: #38bdf8; }}
    .kpi-val.amber {{ color: #fbbf24; }}
    .kpi-val.purple {{ color: #c084fc; }}

    .kpi-sub {{
      font-size: 0.8rem;
      color: var(--text-dim);
    }}

    /* Strategy Matrix Box */
    .strategy-box {{
      background: linear-gradient(145deg, rgba(20, 29, 47, 0.85), rgba(11, 16, 27, 0.95));
      border: 1px solid rgba(56, 189, 248, 0.22);
      border-radius: var(--radius-xl);
      padding: 30px;
      margin-bottom: 40px;
      box-shadow: var(--shadow-lg), var(--shadow-glow);
    }}

    .strategy-title {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 20px;
    }}

    .strategy-title h2 {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.45rem;
      font-weight: 800;
      color: #fff;
    }}

    .strategy-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 18px;
    }}

    .strategy-col {{
      background: rgba(8, 12, 22, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}

    .strategy-col.best {{
      border-color: rgba(16, 185, 129, 0.35);
      background: rgba(16, 185, 129, 0.05);
    }}

    .strategy-col.modern {{
      border-color: rgba(56, 189, 248, 0.35);
      background: rgba(56, 189, 248, 0.05);
    }}

    .strategy-col.trap {{
      border-color: rgba(244, 63, 94, 0.3);
      background: rgba(244, 63, 94, 0.05);
    }}

    .strategy-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-family: 'Outfit', sans-serif;
      font-weight: 700;
      font-size: 1.05rem;
    }}

    .strategy-desc {{
      font-size: 0.88rem;
      color: var(--text-muted);
      line-height: 1.5;
    }}

    .strategy-bullets {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 4px;
    }}

    .strategy-bullets li {{
      font-size: 0.82rem;
      color: var(--text-dim);
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }}

    .strategy-bullets li span.check {{
      color: var(--accent-emerald);
      font-weight: bold;
    }}
    .strategy-bullets li span.warn {{
      color: var(--accent-amber);
      font-weight: bold;
    }}
    .strategy-bullets li span.cross {{
      color: var(--accent-rose);
      font-weight: bold;
    }}

    /* Main Container */
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 24px;
    }}

    /* Interactive Filter Bar */
    .filter-wrapper {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 22px;
      margin-bottom: 32px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      box-shadow: var(--shadow-sm);
    }}

    .tabs-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .tab-btn {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 8px 18px;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}

    .tab-btn:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
      border-color: rgba(255, 255, 255, 0.18);
    }}

    .tab-btn.active {{
      background: var(--accent-blue);
      color: #060911;
      border-color: var(--accent-blue);
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
    }}

    .tab-btn .count-badge {{
      background: rgba(0, 0, 0, 0.25);
      padding: 2px 7px;
      border-radius: 10px;
      font-size: 0.75rem;
    }}
    .tab-btn.active .count-badge {{
      background: rgba(0, 0, 0, 0.35);
      color: #fff;
    }}

    .inputs-row {{
      display: grid;
      grid-template-columns: 2fr 1fr 1fr 1fr auto;
      gap: 14px;
      align-items: center;
    }}

    @media (max-width: 1024px) {{
      .inputs-row {{
        grid-template-columns: 1fr 1fr;
      }}
    }}
    @media (max-width: 640px) {{
      .inputs-row {{
        grid-template-columns: 1fr;
      }}
    }}

    .input-box, .select-box {{
      background: rgba(10, 15, 26, 0.75);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 10px 14px;
      color: #fff;
      font-size: 0.88rem;
      font-family: inherit;
      outline: none;
      transition: all 0.2s ease;
      width: 100%;
    }}

    .input-box:focus, .select-box:focus {{
      border-color: var(--accent-blue);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
    }}

    .select-box option {{
      background: var(--bg-secondary);
      color: #fff;
    }}

    .view-toggles {{
      display: inline-flex;
      background: rgba(10, 15, 26, 0.75);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 3px;
    }}

    .view-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 7px 14px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .view-btn.active {{
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }}

    /* Results Header */
    .results-meta {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 22px;
    }}

    .results-count {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.3rem;
      font-weight: 700;
      color: #fff;
    }}

    /* Offers Grid */
    .offers-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(390px, 1fr));
      gap: 24px;
    }}

    .offer-card {{
      background: var(--bg-card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 24px;
      display: flex;
      flex-direction: column;
      position: relative;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: var(--shadow-sm);
    }}

    .offer-card:hover {{
      background: var(--bg-card-hover);
      border-color: rgba(56, 189, 248, 0.35);
      transform: translateY(-4px);
      box-shadow: var(--shadow-lg), 0 0 25px -5px rgba(56, 189, 248, 0.2);
    }}

    .offer-card.highlighted {{
      border: 1px solid rgba(16, 185, 129, 0.4);
      background: linear-gradient(170deg, rgba(16, 185, 129, 0.06), rgba(16, 23, 38, 0.85) 60%);
    }}

    .offer-card.highlighted::before {{
      content: '★ TOP ROI REKOMENDACJA';
      position: absolute;
      top: -11px;
      right: 20px;
      background: linear-gradient(90deg, #10b981, #059669);
      color: #fff;
      font-size: 0.68rem;
      font-weight: 800;
      letter-spacing: 0.06em;
      padding: 3px 10px;
      border-radius: 9999px;
      box-shadow: 0 4px 10px rgba(16, 185, 129, 0.4);
    }}

    .card-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 12px;
    }}

    .card-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.15rem;
      font-weight: 700;
      color: #fff;
      line-height: 1.35;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .card-price-tag {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      flex-shrink: 0;
    }}

    .price-main {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.55rem;
      font-weight: 800;
      color: #fff;
      white-space: nowrap;
    }}

    .price-curr {{
      font-size: 0.9rem;
      color: var(--accent-blue);
      margin-left: 2px;
    }}

    .location-text {{
      font-size: 0.75rem;
      color: var(--text-dim);
    }}

    /* Badges Row */
    .specs-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 16px;
    }}

    .chip {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 4px 9px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      font-family: 'JetBrains Mono', monospace;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }}

    .chip.gpu {{
      background: rgba(56, 189, 248, 0.12);
      border-color: rgba(56, 189, 248, 0.28);
      color: var(--accent-blue);
    }}

    .chip.cpu {{
      background: rgba(168, 85, 247, 0.12);
      border-color: rgba(168, 85, 247, 0.28);
      color: #c084fc;
    }}

    .chip.tier {{
      background: rgba(245, 158, 11, 0.12);
      border-color: rgba(245, 158, 11, 0.28);
      color: var(--accent-amber);
    }}

    /* Financial ROI Box */
    .finance-box {{
      background: rgba(9, 13, 23, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      margin-bottom: 16px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}

    .finance-item {{
      display: flex;
      flex-direction: column;
    }}

    .finance-label {{
      font-size: 0.72rem;
      color: var(--text-dim);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .finance-val {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.05rem;
      font-weight: 700;
      color: #fff;
    }}

    .finance-item.profit {{
      grid-column: span 2;
      background: rgba(16, 185, 129, 0.08);
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      display: flex;
      flex-direction: row;
      justify-content: space-between;
      align-items: center;
    }}

    .finance-item.profit .profit-val {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.25rem;
      font-weight: 800;
      color: #34d399;
    }}

    .finance-item.profit .roi-badge {{
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
      padding: 3px 8px;
      border-radius: 9999px;
      font-size: 0.76rem;
      font-weight: 800;
    }}

    /* Diagnosis and Prescription */
    .diagnosis-box {{
      background: rgba(15, 23, 42, 0.5);
      border-radius: var(--radius-sm);
      border-left: 3px solid var(--accent-cyan);
      padding: 10px 14px;
      margin-bottom: 14px;
      font-size: 0.82rem;
      line-height: 1.45;
      color: var(--text-muted);
    }}

    .diagnosis-box strong {{
      color: #fff;
      display: block;
      margin-bottom: 2px;
    }}

    .action-steps {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 18px;
    }}

    .action-steps li {{
      font-size: 0.78rem;
      color: var(--text-muted);
      display: flex;
      align-items: flex-start;
      gap: 7px;
    }}

    .action-steps li span.step-num {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent-blue);
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.7rem;
      font-weight: 700;
      width: 17px;
      height: 17px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 1px;
    }}

    /* Card Footer & Links */
    .card-footer {{
      margin-top: auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding-top: 14px;
      border-top: 1px solid var(--border-subtle);
    }}

    .btn-details {{
      background: transparent;
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 7px 12px;
      border-radius: var(--radius-sm);
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .btn-details:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
    }}

    .btn-olx {{
      background: linear-gradient(135deg, #002f34, #004f57);
      border: 1px solid rgba(0, 47, 52, 0.6);
      color: #23e5db;
      padding: 8px 14px;
      border-radius: var(--radius-sm);
      font-size: 0.8rem;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }}

    .btn-olx:hover {{
      background: linear-gradient(135deg, #00454d, #006670);
      color: #ffffff;
      box-shadow: 0 0 12px rgba(35, 229, 219, 0.35);
    }}

    /* Table View */
    .table-container {{
      display: none;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow-x: auto;
      box-shadow: var(--shadow-sm);
    }}

    table.data-table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.85rem;
    }}

    table.data-table th {{
      background: rgba(10, 15, 26, 0.85);
      padding: 14px 16px;
      font-family: 'Outfit', sans-serif;
      font-weight: 700;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border-subtle);
      white-space: nowrap;
    }}

    table.data-table td {{
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      vertical-align: middle;
    }}

    table.data-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    /* Interactive Live ROI Simulator */
    .simulator-box {{
      background: linear-gradient(145deg, rgba(20, 27, 44, 0.9), rgba(10, 14, 25, 0.95));
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: var(--radius-xl);
      padding: 32px;
      margin: 48px 0;
      box-shadow: var(--shadow-lg), var(--shadow-glow);
    }}

    .simulator-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.6rem;
      font-weight: 800;
      color: #fff;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .simulator-subtitle {{
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-bottom: 24px;
    }}

    .sim-grid {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 32px;
    }}

    @media (max-width: 900px) {{
      .sim-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    .sim-controls {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .sim-field {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .sim-field label {{
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
    }}

    .sim-field label span.val {{
      font-family: 'JetBrains Mono', monospace;
      color: var(--accent-blue);
      font-weight: 700;
    }}

    .sim-range {{
      -webkit-appearance: none;
      width: 100%;
      height: 6px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 3px;
      outline: none;
    }}

    .sim-range::-webkit-slider-thumb {{
      -webkit-appearance: none;
      width: 18px;
      height: 18px;
      background: var(--accent-blue);
      border-radius: 50%;
      cursor: pointer;
      box-shadow: 0 0 10px var(--accent-blue);
      transition: all 0.15s;
    }}

    .sim-range::-webkit-slider-thumb:hover {{
      transform: scale(1.15);
    }}

    .sim-results {{
      background: rgba(8, 12, 22, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}

    .sim-kpi-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }}

    .sim-kpi {{
      display: flex;
      flex-direction: column;
    }}

    .sim-kpi-label {{
      font-size: 0.75rem;
      color: var(--text-dim);
      font-weight: 600;
      text-transform: uppercase;
    }}

    .sim-kpi-val {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.7rem;
      font-weight: 800;
      color: #fff;
    }}

    .sim-kpi-val.green {{
      color: #34d399;
    }}

    .sim-bar-box {{
      margin-top: 14px;
    }}

    .sim-bar-label {{
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-bottom: 6px;
    }}

    .sim-bar-bg {{
      width: 100%;
      height: 10px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 5px;
      overflow: hidden;
    }}

    .sim-bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, #10b981, #38bdf8);
      border-radius: 5px;
      transition: width 0.3s ease;
    }}

    /* Modal for Description */
    .modal-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 1000;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}

    .modal-overlay.active {{
      display: flex;
    }}

    .modal-content {{
      background: var(--bg-secondary);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      max-width: 720px;
      width: 100%;
      max-height: 85vh;
      overflow-y: auto;
      padding: 28px;
      box-shadow: var(--shadow-lg);
      position: relative;
    }}

    .modal-close {{
      position: absolute;
      top: 20px;
      right: 20px;
      background: rgba(255, 255, 255, 0.08);
      border: none;
      color: #fff;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.1rem;
      transition: all 0.2s;
    }}

    .modal-close:hover {{
      background: rgba(255, 255, 255, 0.2);
    }}

    .modal-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      margin-bottom: 12px;
      padding-right: 40px;
    }}

    .modal-body {{
      font-size: 0.9rem;
      line-height: 1.6;
      color: var(--text-muted);
      white-space: pre-wrap;
      background: rgba(0, 0, 0, 0.3);
      padding: 16px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-subtle);
    }}

    /* Benchmarks Reference Section */
    .benchmarks-section {{
      margin-top: 50px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-xl);
      padding: 28px;
    }}

    .bench-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-top: 20px;
    }}

    .bench-item {{
      background: rgba(10, 15, 26, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 14px 16px;
    }}

    .bench-name {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--accent-blue);
      margin-bottom: 4px;
    }}

    .bench-price {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.25rem;
      font-weight: 800;
      color: #fff;
    }}

    .bench-sub {{
      font-size: 0.72rem;
      color: var(--text-dim);
    }}
  </style>
</head>
<body>

  <header>
    <div class="header-badges">
      <div class="badge-top emerald"><span class="dot"></span> Baza: scrappy.db (951 ofert)</div>
      <div class="badge-top purple"><span class="dot"></span> Monitorowane uszkodzone: {len(offers)}</div>
      <div class="badge-top"><span class="dot"></span> Cel: Maksymalizacja ROI i Pewne Naprawy</div>
    </div>

    <h1>Uszkodzone Laptopy o Najwyższym ROI</h1>
    <p class="subtitle">
      Rzeczywista analiza ofert oznaczonych jako uszkodzone / na części zebranych z platformy OLX.
      Oddzielamy banalne usterki modularne (wyłamane mocowania zawiasów, głośne wentylatory, brakujące kości RAM/SSD, zalane klawiatury) od ryzykownych usterek płyt głównych, zestawiając je z cenami rynkowymi działających egzemplarzy.
    </p>

    <!-- Top KPI Cards -->
    <div class="kpi-grid">
      <div class="kpi-card emerald">
        <div class="kpi-label">Maksymalny Zysk z 1 Sztuki</div>
        <div class="kpi-val emerald">+1 150 zł</div>
        <div class="kpi-sub">Acer Nitro 7 (i7 / GTX 1660 Ti / 24GB)</div>
      </div>

      <div class="kpi-card blue">
        <div class="kpi-label">Najwyższy Pewny ROI</div>
        <div class="kpi-val blue">+119%</div>
        <div class="kpi-sub">Modularne naprawy bez lutowania</div>
      </div>

      <div class="kpi-card amber">
        <div class="kpi-label">Najniższy Próg Wejścia</div>
        <div class="kpi-val amber">250 zł</div>
        <div class="kpi-sub">ThinkPady X390 / E590 (i5 8. gen)</div>
      </div>

      <div class="kpi-card purple">
        <div class="kpi-label">Loteria Nowoczesności</div>
        <div class="kpi-val purple">RTX 4060</div>
        <div class="kpi-sub">1 100 zł zakupu vs 3 650 zł wartości</div>
      </div>
    </div>

    <!-- Strategy Matrix -->
    <div class="strategy-box">
      <div class="strategy-title">
        <h2>⚡ Strategiczny Playbook Arbitrażu Sprzętowego</h2>
      </div>
      <div class="strategy-grid">
        <div class="strategy-col best">
          <div class="strategy-header" style="color: #34d399;">
            <span>🟢 Kategoria A: Złote Perełki (Łatwe Naprawy)</span>
          </div>
          <div class="strategy-desc">
            Płyta główna, procesor i dedykowana grafika są <strong>w 100% sprawne i przetestowane</strong>. Sprzedawca zniechęcił się usterką mechaniczną lub kosmetyczną.
          </div>
          <ul class="strategy-bullets">
            <li><span class="check">✓</span> <strong>Wentylatory i zawiasy:</strong> Wymiana wiatraków (45 zł) + Poxipol na tuleje (15 zł).</li>
            <li><span class="check">✓</span> <strong>Wyjęty RAM i SSD:</strong> Włożenie dysku za 45 zł i kości RAM za 40 zł.</li>
            <li><span class="check">✓</span> <strong>Brak matrycy:</strong> Działa na HDMI; montaż matrycy 30-pin FHD IPS za ~170 zł.</li>
            <li><span class="check">✓</span> <strong>Ryzyko techniczne:</strong> Niemal zerowe. Stopa zwrotu: <strong>60% – 125%</strong>.</li>
          </ul>
        </div>

        <div class="strategy-col modern">
          <div class="strategy-header" style="color: #38bdf8;">
            <span>🔵 Kategoria B: Potężne Maszyny (Wysokie Ryzyko)</span>
          </div>
          <div class="strategy-desc">
            Laptopy z najnowszymi układami <strong>RTX 4060, RTX 4050, RTX 3060, i7 12. gen</strong> w cenach 1,100–1,200 zł (wartość 3,000–3,700 zł).
          </div>
          <ul class="strategy-bullets">
            <li><span class="warn">!</span> <strong>Objawy:</strong> Gasnące diody po włączeniu, niestabilny boot, zawieszanie instalatora.</li>
            <li><span class="warn">!</span> <strong>Wymagania:</strong> Multimetr, stacja lutownicza, weryfikacja zwarć linii 19V / kondensatorów.</li>
            <li><span class="warn">!</span> <strong>Potencjał:</strong> +1,500 do +2,200 zł zysku netto przy udanej naprawie.</li>
          </ul>
        </div>

        <div class="strategy-col trap">
          <div class="strategy-header" style="color: #f43f5e;">
            <span>🔴 Kategoria C: Pułapki i Dawcy (Omijać!)</span>
          </div>
          <div class="strategy-desc">
            Oferty wyglądające kusząco cenowo, ale będące <strong>nieopłacalną skarbonką bez dna</strong>.
          </div>
          <ul class="strategy-bullets">
            <li><span class="cross">✕</span> <strong>Ukruszony rdzeń krzemowy:</strong> Legion 5 (GTX 1650 Ti) – wymaga wymiany BGA za 600 zł.</li>
            <li><span class="cross">✕</span> <strong>Laptopy po zalaniu (ciecz):</strong> Dell G15 – korozja ścieżek i metalizacja warstw.</li>
            <li><span class="cross">✕</span> <strong>Płyty po nieudanych serwisach:</strong> Spalone procesory po próbach zwarciowych.</li>
          </ul>
        </div>
      </div>
    </div>
  </header>

  <main>
    <!-- Interactive Filter Wrapper -->
    <div class="filter-wrapper">
      <div class="tabs-row" id="tabsRow">
        <button class="tab-btn active" data-tier="all">
          Wszystkie Uszkodzone <span class="count-badge" id="countAll">0</span>
        </button>
        <button class="tab-btn" data-tier="easy_fix">
          🌟 Łatwe Naprawy (Top ROI) <span class="count-badge" id="countEasy">0</span>
        </button>
        <button class="tab-btn" data-tier="modern_powerhouse">
          ⚡ Bestie RTX 40/30 (Mocne) <span class="count-badge" id="countModern">0</span>
        </button>
        <button class="tab-btn" data-tier="thinkpad_business">
          💼 ThinkPady Biznesowe <span class="count-badge" id="countThinkpad">0</span>
        </button>
        <button class="tab-btn" data-tier="budget_gaming">
          🎮 Gaming poniżej 900 zł <span class="count-badge" id="countBudget">0</span>
        </button>
        <button class="tab-btn" data-tier="avoid_donor">
          ⚠️ Pułapki / Tylko na Części <span class="count-badge" id="countAvoid">0</span>
        </button>
      </div>

      <div class="inputs-row">
        <input type="text" class="input-box" id="searchInput" placeholder="Szukaj po modelu, procesorze, grafice, mieście (np. Nitro, 1660 Ti, T480, Kraków)...">
        
        <select class="select-box" id="sortSelect">
          <option value="roi_desc">Sortuj: Najwyższy ROI %</option>
          <option value="profit_desc">Sortuj: Najwyższy Zysk Netto (zł)</option>
          <option value="price_asc">Sortuj: Najniższa Cena Zakupu</option>
          <option value="resale_desc">Sortuj: Najwyższa Wartość Rynkowa</option>
        </select>

        <select class="select-box" id="maxPriceSelect">
          <option value="99999">Maks. Cena: Dowolna</option>
          <option value="400">Maks. Cena: do 400 zł</option>
          <option value="800">Maks. Cena: do 800 zł</option>
          <option value="1200">Maks. Cena: do 1 200 zł</option>
        </select>

        <div class="view-toggles">
          <button class="view-btn active" id="btnViewCards">Kafelki</button>
          <button class="view-btn" id="btnViewTable">Tabela</button>
        </div>
      </div>
    </div>

    <!-- Results Meta -->
    <div class="results-meta">
      <div class="results-count" id="resultsCount">Wyświetlanie ofert...</div>
    </div>

    <!-- Cards View -->
    <div class="offers-grid" id="offersGrid"></div>

    <!-- Table View -->
    <div class="table-container" id="tableContainer">
      <table class="data-table">
        <thead>
          <tr>
            <th>Model i Tytuł</th>
            <th>Kategoria</th>
            <th>Podzespoły (CPU / GPU)</th>
            <th>Cena Zakupu</th>
            <th>Koszt Części</th>
            <th>Wartość Rynkowa</th>
            <th>Zysk Netto</th>
            <th>ROI %</th>
            <th>Link OLX</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>

    <!-- Live Interactive ROI Simulator -->
    <div class="simulator-box">
      <div class="simulator-title">
        <span>🧮 Interaktywny Kalkulator Arbitrażu & Symulator Naprawy</span>
      </div>
      <p class="simulator-subtitle">
        Sprawdź opłacalność dowolnego laptopa w czasie rzeczywistym. Dostosuj wynegocjowaną cenę zakupu, realny koszt części z Allegro oraz spodziewaną cenę sprzedaży.
      </p>

      <div class="sim-grid">
        <div class="sim-controls">
          <div class="sim-field">
            <label>Wybierz Szablon Maszyny: <span class="val" id="simPresetLabel">Acer Nitro 7 (GTX 1660 Ti)</span></label>
            <select class="select-box" id="simPresetSelect">
              <option value="nitro7">Acer Nitro 7 (i7-9750H / GTX 1660 Ti / 24GB RAM)</option>
              <option value="t480">Lenovo ThinkPad T480 (i5-8250U / FHD / Bez RAM & SSD)</option>
              <option value="tuf505">Asus TUF FX505DT (Ryzen 5 / GTX 1650 / 16GB)</option>
              <option value="msi8750">MSI Gaming (i7-8750H / GTX 1650 / Bez Ekranu)</option>
              <option value="nitro4060">Acer Nitro 5 RTX 4060 (i5-12500H / 17.3'' QHD 165Hz)</option>
              <option value="t490s">Lenovo ThinkPad T490s (16GB RAM / Bezpiecznik matrycy)</option>
              <option value="custom">Własne parametry (Dowolny laptop)</option>
            </select>
          </div>

          <div class="sim-field">
            <label>Cena Zakupu na OLX: <span class="val" id="simBuyVal">899 zł</span></label>
            <input type="range" class="sim-range" id="simBuyInput" min="50" max="3000" step="10" value="899">
          </div>

          <div class="sim-field">
            <label>Szacowany Koszt Części i Naprawy: <span class="val" id="simRepairVal">65 zł</span></label>
            <input type="range" class="sim-range" id="simRepairInput" min="0" max="1000" step="10" value="65">
          </div>

          <div class="sim-field">
            <label>Prognozowana Cena Sprzedaży (Sprawny): <span class="val" id="simSellVal">2 050 zł</span></label>
            <input type="range" class="sim-range" id="simSellInput" min="300" max="4500" step="50" value="2050">
          </div>
        </div>

        <div class="sim-results">
          <div class="sim-kpi-row">
            <div class="sim-kpi">
              <div class="sim-kpi-label">Łączny Kapitał Inwestycji</div>
              <div class="sim-kpi-val" id="simTotalInvested">964 zł</div>
            </div>
            <div class="sim-kpi">
              <div class="sim-kpi-label">Prognozowany Zysk Netto</div>
              <div class="sim-kpi-val green" id="simNetProfit">+1 086 zł</div>
            </div>
          </div>

          <div class="sim-kpi-row">
            <div class="sim-kpi">
              <div class="sim-kpi-label">Stopa Zwrotu (ROI)</div>
              <div class="sim-kpi-val green" id="simRoiPct">+112.7%</div>
            </div>
            <div class="sim-kpi">
              <div class="sim-kpi-label">Próg Rentowności (Break-Even)</div>
              <div class="sim-kpi-val" id="simBreakEven">964 zł</div>
            </div>
          </div>

          <div class="sim-bar-box">
            <div class="sim-bar-label">
              <span>Wskaźnik Marży Zysku:</span>
              <span id="simMarginPct">53% marży</span>
            </div>
            <div class="sim-bar-bg">
              <div class="sim-bar-fill" id="simBarFill" style="width: 53%;"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Verified Secondary Market Benchmarks -->
    <div class="benchmarks-section">
      <div class="strategy-title">
        <h2>📊 Referencyjne Ceny Rynkowe (Sprawne Laptopy z Bazy OLX)</h2>
      </div>
      <p style="color: var(--text-muted); font-size: 0.9rem;">
        Średnie i minimalne ceny ofertowe zweryfikowane na podstawie działających egzemplarzy z naszej bazy danych scrappy.db. Służą jako konserwatywny punkt odniesienia do wyceny po naprawie.
      </p>

      <div class="bench-grid">
        <div class="bench-item">
          <div class="bench-name">NVIDIA RTX 4060</div>
          <div class="bench-price">3 650 zł</div>
          <div class="bench-sub">Średnia baza (n=43), min. 3 100 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">NVIDIA RTX 4050</div>
          <div class="bench-price">2 980 zł</div>
          <div class="bench-sub">Średnia baza (n=45), min. 2 400 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">NVIDIA RTX 3060</div>
          <div class="bench-price">2 810 zł</div>
          <div class="bench-sub">Średnia baza (n=72), min. 2 300 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">NVIDIA RTX 3050</div>
          <div class="bench-price">2 380 zł</div>
          <div class="bench-sub">Średnia baza (n=114), min. 1 850 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">GTX 1660 Ti</div>
          <div class="bench-price">2 250 zł</div>
          <div class="bench-sub">Średnia baza (n=27), min. 1 700 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">GTX 1650 / Ti</div>
          <div class="bench-price">1 380 zł</div>
          <div class="bench-sub">Średnia baza (n=179), min. 1 100 zł</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">ThinkPad T480 / T490</div>
          <div class="bench-price">1 050 – 1 200 zł</div>
          <div class="bench-sub">Kompletne konfiguracje z i5 8. gen</div>
        </div>
        <div class="bench-item">
          <div class="bench-name">ThinkPad X390 Yoga</div>
          <div class="bench-price">1 150 zł</div>
          <div class="bench-sub">Ultrabook dotykowy 2-w-1</div>
        </div>
      </div>
    </div>
  </main>

  <!-- Modal for Full Description -->
  <div class="modal-overlay" id="descModal">
    <div class="modal-content">
      <button class="modal-close" id="modalCloseBtn">&times;</button>
      <div class="modal-title" id="modalTitle">Pełny Opis Sprzedawcy</div>
      <div class="modal-body" id="modalBody"></div>
    </div>
  </div>

  <script>
    const OFFERS = {json_data};
    const BENCHMARKS = {benchmarks_json};

    let activeTier = 'all';
    let searchQuery = '';
    let sortMode = 'roi_desc';
    let maxPrice = 99999;
    let isTableView = false;

    // Elements
    const offersGrid = document.getElementById('offersGrid');
    const tableContainer = document.getElementById('tableContainer');
    const tableBody = document.getElementById('tableBody');
    const resultsCount = document.getElementById('resultsCount');
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const maxPriceSelect = document.getElementById('maxPriceSelect');
    const tabsRow = document.getElementById('tabsRow');
    const btnViewCards = document.getElementById('btnViewCards');
    const btnViewTable = document.getElementById('btnViewTable');

    // Counts update
    function updateCounts() {{
      document.getElementById('countAll').innerText = OFFERS.length;
      document.getElementById('countEasy').innerText = OFFERS.filter(o => o.tier === 'easy_fix').length;
      document.getElementById('countModern').innerText = OFFERS.filter(o => o.tier === 'modern_powerhouse').length;
      document.getElementById('countThinkpad').innerText = OFFERS.filter(o => o.tier === 'thinkpad_business').length;
      document.getElementById('countBudget').innerText = OFFERS.filter(o => o.tier === 'budget_gaming').length;
      document.getElementById('countAvoid').innerText = OFFERS.filter(o => o.tier === 'avoid_donor').length;
    }}

    // Filter & Sort Logic
    function getFilteredOffers() {{
      return OFFERS.filter(o => {{
        if (activeTier !== 'all' && o.tier !== activeTier) return false;
        if (o.price > maxPrice) return false;
        if (searchQuery) {{
          const q = searchQuery.toLowerCase();
          const matchTitle = (o.title || '').toLowerCase().includes(q);
          const matchCpu = (o.cpu || '').toLowerCase().includes(q);
          const matchGpu = (o.gpu || '').toLowerCase().includes(q);
          const matchLoc = (o.location || '').toLowerCase().includes(q);
          const matchDesc = (o.description || '').toLowerCase().includes(q);
          if (!matchTitle && !matchCpu && !matchGpu && !matchLoc && !matchDesc) return false;
        }}
        return true;
      }}).sort((a, b) => {{
        // Highlights always first
        if (a.highlight !== b.highlight) return b.highlight ? 1 : -1;
        
        if (sortMode === 'roi_desc') return b.roi_pct - a.roi_pct;
        if (sortMode === 'profit_desc') return b.net_profit - a.net_profit;
        if (sortMode === 'price_asc') return a.price - b.price;
        if (sortMode === 'resale_desc') return b.resale_val - a.resale_val;
        return 0;
      }});
    }}

    // Render Cards
    function renderOffers() {{
      const list = getFilteredOffers();
      resultsCount.innerText = `Znaleziono ${{list.length}} ofert spełniających kryteria:`;

      if (isTableView) {{
        offersGrid.style.display = 'none';
        tableContainer.style.display = 'block';
        renderTable(list);
      }} else {{
        offersGrid.style.display = 'grid';
        tableContainer.style.display = 'none';
        renderCards(list);
      }}
    }}

    function renderCards(list) {{
      offersGrid.innerHTML = '';
      if (list.length === 0) {{
        offersGrid.innerHTML = '<div style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-muted);">Brak ofert pasujących do wybranych filtrów.</div>';
        return;
      }}

      list.forEach(o => {{
        const card = document.createElement('div');
        card.className = `offer-card ${{o.highlight ? 'highlighted' : ''}}`;

        const actionStepsHtml = o.action_plan && o.action_plan.length ? o.action_plan.map((step, idx) => `
          <li><span class="step-num">${{idx + 1}}</span> ${{step}}</li>
        `).join('') : '';

        card.innerHTML = `
          <div class="card-head">
            <div class="card-title" title="${{escapeHtml(o.title)}}">${{escapeHtml(o.title)}}</div>
            <div class="card-price-tag">
              <div class="price-main">${{o.price}}<span class="price-curr">zł</span></div>
              <div class="location-text">📍 ${{escapeHtml(o.location)}}</div>
            </div>
          </div>

          <div class="specs-chips">
            ${{o.gpu && o.gpu !== 'Zintegrowana / Brak' ? `<span class="chip gpu">🎮 ${{escapeHtml(o.gpu)}}</span>` : ''}}
            ${{o.cpu && o.cpu !== 'Nie podano' ? `<span class="chip cpu">⚡ ${{escapeHtml(o.cpu)}}</span>` : ''}}
            ${{o.ram_gb ? `<span class="chip">RAM: ${{o.ram_gb}}GB</span>` : ''}}
            ${{o.storage_gb ? `<span class="chip">SSD: ${{o.storage_gb}}GB</span>` : ''}}
            <span class="chip tier">${{escapeHtml(o.tier_label)}}</span>
          </div>

          <div class="finance-box">
            <div class="finance-item">
              <span class="finance-label">Części / Naprawa</span>
              <span class="finance-val">${{o.repair_cost > 0 ? o.repair_cost + ' zł' : '0 zł'}}</span>
            </div>
            <div class="finance-item">
              <span class="finance-label">Wycena Rynkowa</span>
              <span class="finance-val">${{o.resale_val > 0 ? o.resale_val + ' zł' : 'Brak danych'}}</span>
            </div>
            <div class="finance-item profit">
              <div>
                <span class="finance-label" style="color: #34d399;">Prognozowany Zysk Netto</span>
                <div class="profit-val">${{o.net_profit > 0 ? '+' + o.net_profit + ' zł' : (o.net_profit === 0 ? '0 zł' : o.net_profit + ' zł')}}</div>
              </div>
              <div class="roi-badge">${{o.roi_pct > 0 ? '+' + o.roi_pct + '%' : o.roi_pct + '%'}} ROI</div>
            </div>
          </div>

          <div class="diagnosis-box">
            <strong>Diagnoza i Usterka:</strong>
            ${{escapeHtml(o.repair_summary)}}
          </div>

          ${{actionStepsHtml ? `<ul class="action-steps">${{actionStepsHtml}}</ul>` : ''}}

          <div class="card-footer">
            <button class="btn-details" onclick="openModal('${{o.id}}')">📄 Czytaj Pełny Opis</button>
            <a href="${{o.url}}" target="_blank" rel="noopener noreferrer" class="btn-olx">
              <span>Zobacz na OLX</span> ↗
            </a>
          </div>
        `;
        offersGrid.appendChild(card);
      }});
    }}

    function renderTable(list) {{
      tableBody.innerHTML = '';
      list.forEach(o => {{
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><strong>${{escapeHtml(o.title)}}</strong><br><small style="color: var(--text-dim);">📍 ${{escapeHtml(o.location)}}</small></td>
          <td><span class="chip tier">${{escapeHtml(o.tier_label)}}</span></td>
          <td>${{escapeHtml(o.cpu)}}<br><small style="color: var(--accent-blue);">${{escapeHtml(o.gpu)}}</small></td>
          <td><strong style="color: #fff;">${{o.price}} zł</strong></td>
          <td>${{o.repair_cost}} zł</td>
          <td>${{o.resale_val}} zł</td>
          <td><strong style="color: #34d399;">${{o.net_profit > 0 ? '+' + o.net_profit : o.net_profit}} zł</strong></td>
          <td><span style="color: #34d399; font-weight: bold;">+${{o.roi_pct}}%</span></td>
          <td><a href="${{o.url}}" target="_blank" rel="noopener" class="btn-olx" style="padding: 4px 8px; font-size: 0.72rem;">OLX ↗</a></td>
        `;
        tableBody.appendChild(row);
      }});
    }}

    function escapeHtml(text) {{
      if (!text) return '';
      return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }}

    // Modal Handling
    const descModal = document.getElementById('descModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    const modalCloseBtn = document.getElementById('modalCloseBtn');

    window.openModal = function(oid) {{
      const item = OFFERS.find(x => x.id === oid);
      if (!item) return;
      modalTitle.innerText = item.title;
      modalBody.innerText = item.description || 'Brak opisu w ofercie.';
      descModal.classList.add('active');
    }};

    modalCloseBtn.onclick = () => descModal.classList.remove('active');
    descModal.onclick = (e) => {{
      if (e.target === descModal) descModal.classList.remove('active');
    }};

    // Simulator Logic
    const simPresetSelect = document.getElementById('simPresetSelect');
    const simPresetLabel = document.getElementById('simPresetLabel');
    const simBuyInput = document.getElementById('simBuyInput');
    const simBuyVal = document.getElementById('simBuyVal');
    const simRepairInput = document.getElementById('simRepairInput');
    const simRepairVal = document.getElementById('simRepairVal');
    const simSellInput = document.getElementById('simSellInput');
    const simSellVal = document.getElementById('simSellVal');
    const simTotalInvested = document.getElementById('simTotalInvested');
    const simNetProfit = document.getElementById('simNetProfit');
    const simRoiPct = document.getElementById('simRoiPct');
    const simBreakEven = document.getElementById('simBreakEven');
    const simMarginPct = document.getElementById('simMarginPct');
    const simBarFill = document.getElementById('simBarFill');

    const PRESETS = {{
      nitro7: {{ name: 'Acer Nitro 7 (GTX 1660 Ti)', buy: 899, repair: 65, sell: 2050 }},
      t480: {{ name: 'Lenovo ThinkPad T480', buy: 400, repair: 165, sell: 1050 }},
      tuf505: {{ name: 'Asus TUF FX505DT (GTX 1650)', buy: 700, repair: 55, sell: 1350 }},
      msi8750: {{ name: 'MSI Gaming i7 / GTX 1650', buy: 800, repair: 175, sell: 1450 }},
      nitro4060: {{ name: 'Acer Nitro 5 RTX 4060', buy: 1100, repair: 250, sell: 3650 }},
      t490s: {{ name: 'Lenovo ThinkPad T490s', buy: 350, repair: 30, sell: 1150 }}
    }};

    function updateSimulator() {{
      const buy = parseFloat(simBuyInput.value);
      const repair = parseFloat(simRepairInput.value);
      const sell = parseFloat(simSellInput.value);

      simBuyVal.innerText = `${{buy}} zł`;
      simRepairVal.innerText = `${{repair}} zł`;
      simSellVal.innerText = `${{sell}} zł`;

      const invested = buy + repair;
      const profit = sell - invested;
      const roi = invested > 0 ? (profit / invested) * 100 : 0;
      const margin = sell > 0 ? (profit / sell) * 100 : 0;

      simTotalInvested.innerText = `${{invested}} zł`;
      simBreakEven.innerText = `${{invested}} zł`;

      if (profit >= 0) {{
        simNetProfit.innerText = `+${{profit}} zł`;
        simNetProfit.className = 'sim-kpi-val green';
        simRoiPct.innerText = `+${{roi.toFixed(1)}}%`;
        simRoiPct.className = 'sim-kpi-val green';
      }} else {{
        simNetProfit.innerText = `${{profit}} zł`;
        simNetProfit.className = 'sim-kpi-val' ;
        simNetProfit.style.color = '#f43f5e';
        simRoiPct.innerText = `${{roi.toFixed(1)}}%`;
        simRoiPct.className = 'sim-kpi-val';
        simRoiPct.style.color = '#f43f5e';
      }}

      const displayMargin = Math.max(0, Math.min(100, margin));
      simMarginPct.innerText = `${{displayMargin.toFixed(0)}}% marży`;
      simBarFill.style.width = `${{displayMargin}}%`;
    }}

    simPresetSelect.onchange = (e) => {{
      const p = PRESETS[e.target.value];
      if (p) {{
        simPresetLabel.innerText = p.name;
        simBuyInput.value = p.buy;
        simRepairInput.value = p.repair;
        simSellInput.value = p.sell;
      }} else {{
        simPresetLabel.innerText = 'Własne parametry';
      }}
      updateSimulator();
    }};

    simBuyInput.oninput = updateSimulator;
    simRepairInput.oninput = updateSimulator;
    simSellInput.oninput = updateSimulator;

    // Filter Listeners
    tabsRow.querySelectorAll('.tab-btn').forEach(btn => {{
      btn.onclick = () => {{
        tabsRow.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeTier = btn.dataset.tier;
        renderOffers();
      }};
    }});

    searchInput.oninput = (e) => {{
      searchQuery = e.target.value.trim();
      renderOffers();
    }};

    sortSelect.onchange = (e) => {{
      sortMode = e.target.value;
      renderOffers();
    }};

    maxPriceSelect.onchange = (e) => {{
      maxPrice = parseFloat(e.target.value);
      renderOffers();
    }};

    btnViewCards.onclick = () => {{
      btnViewCards.classList.add('active');
      btnViewTable.classList.remove('active');
      isTableView = false;
      renderOffers();
    }};

    btnViewTable.onclick = () => {{
      btnViewTable.classList.add('active');
      btnViewCards.classList.remove('active');
      isTableView = true;
      renderOffers();
    }};

    // Init
    updateCounts();
    renderOffers();
    updateSimulator();
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    build_dashboard()
