import json
import os

with open('scratch/master_power_laptops.json', 'r', encoding='utf-8') as f:
    laptops = json.load(f)

json_data = json.dumps(laptops, ensure_ascii=False)

html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Best Performance Laptops | Market Analysis & High-Power Upgrades</title>
  <meta name="description" content="Comprehensive marketplace analysis beyond Acer Nitro 7: Curated high-performance laptops featuring RTX 3060/4060 GPUs, 14-core Intel i7, Ryzen 7 5800H, and Lenovo Legion 5 Pro displays from real scraped OLX data.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-primary: #080c14;
      --bg-secondary: #0f1626;
      --bg-card: rgba(18, 26, 42, 0.78);
      --bg-card-hover: rgba(25, 38, 62, 0.95);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-accent: rgba(56, 189, 248, 0.35);
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent-blue: #38bdf8;
      --accent-cyan: #06b6d4;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --accent-purple: #a855f7;
      --accent-indigo: #6366f1;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --shadow-sm: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
      --shadow-lg: 0 20px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
      --shadow-glow: 0 0 35px -5px rgba(56, 189, 248, 0.25);
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
        radial-gradient(circle at 10% 12%, rgba(56, 189, 248, 0.09) 0%, transparent 45%),
        radial-gradient(circle at 88% 25%, rgba(168, 85, 247, 0.08) 0%, transparent 48%),
        radial-gradient(circle at 45% 75%, rgba(16, 185, 129, 0.06) 0%, transparent 50%);
      background-attachment: fixed;
    }}

    header {{
      padding: 44px 24px 24px;
      max-width: 1440px;
      margin: 0 auto;
    }}

    .badge-top {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent-blue);
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 6px 14px;
      border-radius: 9999px;
      margin-bottom: 16px;
    }}

    .badge-top span.dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: var(--accent-emerald);
      box-shadow: 0 0 10px var(--accent-emerald);
    }}

    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: clamp(2.1rem, 3.8vw, 3.4rem);
      font-weight: 800;
      letter-spacing: -0.025em;
      line-height: 1.15;
      background: linear-gradient(135deg, #ffffff 25%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 14px;
    }}

    .subtitle {{
      color: var(--text-muted);
      font-size: 1.12rem;
      max-width: 920px;
      margin-bottom: 30px;
      line-height: 1.6;
    }}

    /* Baseline Hero Card */
    .baseline-card {{
      background: linear-gradient(145deg, rgba(30, 41, 59, 0.85), rgba(15, 23, 42, 0.95));
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: var(--radius-lg);
      padding: 24px 28px;
      margin-bottom: 36px;
      box-shadow: var(--shadow-lg), var(--shadow-glow);
      position: relative;
      overflow: hidden;
    }}

    .baseline-card::before {{
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      width: 5px;
      height: 100%;
      background: linear-gradient(to bottom, var(--accent-cyan), var(--accent-purple));
    }}

    .baseline-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
    }}

    .baseline-title {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .baseline-title h2 {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.4rem;
      font-weight: 700;
      color: #fff;
    }}

    .pill-reference {{
      background: rgba(245, 158, 11, 0.16);
      border: 1px solid rgba(245, 158, 11, 0.35);
      color: var(--accent-amber);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 4px 12px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .baseline-specs {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
      background: rgba(11, 15, 25, 0.65);
      padding: 18px 20px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border-subtle);
    }}

    .spec-item {{
      display: flex;
      flex-direction: column;
    }}

    .spec-label {{
      font-size: 0.74rem;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 4px;
    }}

    .spec-value {{
      font-size: 0.98rem;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .spec-note {{
      font-size: 0.76rem;
      color: var(--accent-blue);
      margin-top: 3px;
    }}

    /* Key Metrics Grid */
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 16px;
      margin-bottom: 38px;
    }}

    .metric-card {{
      background: var(--bg-card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px 22px;
      transition: all 0.25s ease;
      position: relative;
    }}

    .metric-card:hover {{
      border-color: rgba(255, 255, 255, 0.18);
      transform: translateY(-2px);
    }}

    .metric-card .num {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.95rem;
      font-weight: 800;
      line-height: 1.1;
      margin-top: 6px;
      background: linear-gradient(135deg, #fff 35%, var(--accent-blue) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .metric-card .label {{
      font-size: 0.82rem;
      color: var(--text-muted);
      font-weight: 500;
    }}

    .metric-card .sub-note {{
      font-size: 0.72rem;
      color: var(--accent-emerald);
      margin-top: 4px;
      font-weight: 600;
    }}

    /* Architectural Comparison Pillars */
    .pillars-section {{
      max-width: 1440px;
      margin: 0 auto 36px;
      padding: 0 24px;
    }}

    .pillars-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
    }}

    .pillar-card {{
      background: linear-gradient(160deg, rgba(22, 32, 51, 0.7), rgba(12, 17, 28, 0.85));
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px 22px;
      position: relative;
    }}

    .pillar-icon {{
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.25);
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 12px;
      color: var(--accent-blue);
      font-size: 1.25rem;
    }}

    .pillar-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.1rem;
      font-weight: 700;
      color: #fff;
      margin-bottom: 6px;
    }}

    .pillar-desc {{
      font-size: 0.84rem;
      color: var(--text-muted);
      line-height: 1.5;
    }}

    .pillar-gain {{
      margin-top: 10px;
      font-size: 0.8rem;
      font-weight: 700;
      color: var(--accent-emerald);
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}

    /* Controls Bar */
    .controls-wrapper {{
      max-width: 1440px;
      margin: 0 auto 28px;
      padding: 0 24px;
    }}

    .controls-bar {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      box-shadow: var(--shadow-sm);
    }}

    .filter-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .tab-btn {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 8px 16px;
      border-radius: 9999px;
      font-size: 0.84rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}

    .tab-btn:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
      border-color: rgba(255, 255, 255, 0.2);
    }}

    .tab-btn.active {{
      background: var(--accent-blue);
      color: #080c14;
      border-color: var(--accent-blue);
      font-weight: 700;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
    }}

    .filter-inputs {{
      display: grid;
      grid-template-columns: 2fr 1fr 1fr auto;
      gap: 14px;
      align-items: center;
    }}

    @media (max-width: 900px) {{
      .filter-inputs {{
        grid-template-columns: 1fr;
      }}
    }}

    .input-box {{
      background: rgba(11, 15, 25, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 9px 14px;
      color: #fff;
      font-size: 0.9rem;
      font-family: inherit;
      outline: none;
      transition: border-color 0.2s ease;
      width: 100%;
    }}

    .input-box:focus {{
      border-color: var(--accent-blue);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
    }}

    .select-box {{
      background: rgba(11, 15, 25, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 9px 14px;
      color: #fff;
      font-size: 0.9rem;
      outline: none;
      cursor: pointer;
      width: 100%;
    }}

    .select-box option {{
      background: var(--bg-secondary);
      color: #fff;
    }}

    .view-toggle {{
      display: inline-flex;
      background: rgba(11, 15, 25, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 3px;
    }}

    .toggle-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .toggle-btn.active {{
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }}

    /* Offers Container */
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 24px;
    }}

    .section-headline {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
    }}

    .section-headline h3 {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.45rem;
      font-weight: 700;
      color: #fff;
    }}

    .count-indicator {{
      font-size: 0.86rem;
      color: var(--text-dim);
    }}

    /* Cards Grid */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
      gap: 22px;
    }}

    .offer-card {{
      background: var(--bg-card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 22px;
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

    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 12px;
    }}

    .badge-roi {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}

    .badge-roi.stellar {{
      background: rgba(16, 185, 129, 0.18);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.35);
    }}

    .badge-roi.highlight {{
      background: rgba(56, 189, 248, 0.18);
      color: var(--accent-blue);
      border: 1px solid rgba(56, 189, 248, 0.35);
    }}

    .badge-roi.upgrade {{
      background: rgba(168, 85, 247, 0.18);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.35);
    }}

    .badge-roi.value {{
      background: rgba(245, 158, 11, 0.18);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.35);
    }}

    .price-box {{
      text-align: right;
    }}

    .price-amount {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.75rem;
      font-weight: 800;
      color: #fff;
      line-height: 1;
    }}

    .price-currency {{
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent-blue);
      margin-left: 3px;
    }}

    .price-negotiable {{
      font-size: 0.72rem;
      color: var(--accent-emerald);
      display: block;
      margin-top: 3px;
      font-weight: 600;
    }}

    .card-title {{
      font-size: 1.08rem;
      font-weight: 700;
      color: #f8fafc;
      line-height: 1.35;
      margin-bottom: 12px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}

    .pills-cloud {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 14px;
    }}

    .pill {{
      font-size: 0.76rem;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-main);
      border: 1px solid var(--border-subtle);
    }}

    .pill.cpu {{
      background: rgba(56, 189, 248, 0.1);
      color: #7dd3fc;
      border-color: rgba(56, 189, 248, 0.25);
    }}

    .pill.gpu {{
      background: rgba(245, 158, 11, 0.12);
      color: #fcd34d;
      border-color: rgba(245, 158, 11, 0.25);
    }}

    .pill.refresh {{
      background: rgba(168, 85, 247, 0.12);
      color: #d8b4fe;
      border-color: rgba(168, 85, 247, 0.25);
    }}

    .pill.chassis {{
      background: rgba(16, 185, 129, 0.1);
      color: #6ee7b7;
      border-color: rgba(16, 185, 129, 0.25);
    }}

    /* Dual Performance Meters */
    .meter-box {{
      background: rgba(11, 15, 25, 0.65);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      margin-bottom: 12px;
      border: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .meter-row {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .meter-header {{
      display: flex;
      justify-content: space-between;
      font-size: 0.74rem;
    }}

    .meter-header span:first-child {{
      color: var(--text-muted);
      font-weight: 500;
    }}

    .meter-header span:last-child {{
      color: #fff;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
    }}

    .progress-bar-bg {{
      height: 5px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 9999px;
      overflow: hidden;
    }}

    .progress-bar-fill {{
      height: 100%;
      border-radius: 9999px;
      transition: width 0.6s ease;
    }}

    .card-highlights {{
      font-size: 0.83rem;
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.02);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      margin-bottom: 16px;
      flex-grow: 1;
      border-left: 2px solid var(--accent-blue);
      line-height: 1.5;
    }}

    .card-meta {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 12px;
      border-top: 1px solid var(--border-subtle);
      margin-top: auto;
    }}

    .location-text {{
      font-size: 0.78rem;
      color: var(--text-dim);
      display: flex;
      align-items: center;
      gap: 4px;
    }}

    .btn-link {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(6, 182, 212, 0.2));
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: #fff;
      text-decoration: none;
      font-size: 0.82rem;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: var(--radius-sm);
      transition: all 0.2s ease;
    }}

    .btn-link:hover {{
      background: var(--accent-blue);
      color: #080c14;
      box-shadow: 0 0 14px rgba(56, 189, 248, 0.4);
    }}

    /* Comparison Table View */
    .table-container {{
      display: none;
      background: var(--bg-card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow-x: auto;
      box-shadow: var(--shadow-sm);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.86rem;
    }}

    th {{
      background: rgba(11, 15, 25, 0.85);
      color: var(--text-muted);
      font-weight: 600;
      padding: 14px 18px;
      border-bottom: 1px solid var(--border-subtle);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.05em;
    }}

    td {{
      padding: 16px 18px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-main);
      vertical-align: middle;
    }}

    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    /* Pitfalls Section */
    .pitfalls-section {{
      max-width: 1440px;
      margin: 44px auto 0;
      padding: 0 24px;
    }}

    .pitfalls-card {{
      background: linear-gradient(145deg, rgba(30, 20, 25, 0.65), rgba(15, 10, 15, 0.95));
      border: 1px solid rgba(244, 63, 94, 0.35);
      border-radius: var(--radius-lg);
      padding: 24px 28px;
    }}

    .pitfalls-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      color: var(--accent-rose);
      font-family: 'Outfit', sans-serif;
      font-size: 1.28rem;
      font-weight: 700;
    }}

    .pitfalls-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}

    .pitfall-item {{
      background: rgba(11, 15, 25, 0.6);
      border: 1px solid rgba(244, 63, 94, 0.15);
      border-radius: var(--radius-md);
      padding: 14px 16px;
    }}

    .pitfall-title {{
      font-weight: 600;
      font-size: 0.9rem;
      color: #fff;
      margin-bottom: 4px;
    }}

    .pitfall-desc {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}

    .pitfall-price {{
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--accent-rose);
      margin-top: 6px;
      display: inline-block;
    }}

    /* Footer */
    footer {{
      max-width: 1440px;
      margin: 60px auto 0;
      padding: 0 24px;
      text-align: center;
      color: var(--text-dim);
      font-size: 0.85rem;
      border-top: 1px solid var(--border-subtle);
      padding-top: 24px;
    }}

    footer a {{
      color: var(--accent-blue);
      text-decoration: none;
    }}
  </style>
</head>
<body>

  <header>
    <div class="badge-top">
      <span class="dot"></span> Live Scraped Marketplace Analysis • 7,059 Offers Evaluated
    </div>
    <h1>Best Performance Laptops: Beyond the Acer Nitro 7</h1>
    <p class="subtitle">
      Comprehensive market evaluation moving past entry-level Acer Nitro laptops into <strong>14-core Intel Alder Lake, 8-core AMD Zen 3, full 140W RTX 3060/4060 graphics, and 165Hz QHD+ displays</strong> with top ROI.
    </p>

    <!-- Baseline Comparison Card -->
    <div class="baseline-card">
      <div class="baseline-header">
        <div class="baseline-title">
          <h2>Reference Baseline: Acer Nitro 7 (AN715-51)</h2>
          <span class="pill-reference">Starting Point (100%)</span>
        </div>
        <div style="font-size: 0.85rem; color: var(--text-dim); font-family: 'JetBrains Mono', monospace;">
          AN715-51-537Z • Model N18C3 • Market Price ~1,250 PLN
        </div>
      </div>
      <div class="baseline-specs">
        <div class="spec-item">
          <span class="spec-label">Processor</span>
          <span class="spec-value">Intel Core i5-9300H</span>
          <span class="spec-note">4 Cores / 8 Threads, 14nm (Baseline Multi-Core 100%)</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">Graphics (Turing)</span>
          <span class="spec-value">GTX 1660 Ti 6GB / GTX 1650</span>
          <span class="spec-note">Baseline GPU 100% (No DLSS, No Ray Tracing)</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">Display & Thermals</span>
          <span class="spec-value">15.6" IPS 144 Hz (250 nits, 45% NTSC)</span>
          <span class="spec-note">Entry budget panel, plastic chassis prone to throttle</span>
        </div>
        <div class="spec-item">
          <span class="spec-label">GPU Power & MUX</span>
          <span class="spec-value">80W TGP • No MUX Switch</span>
          <span class="spec-note">All display frames pass through Intel iGPU (+15% latency penalty)</span>
        </div>
      </div>
    </div>

    <!-- Key Metrics Grid -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="label">Top Multi-Core Compute Jump</div>
        <div class="num">+280%</div>
        <div class="sub-note">14-Core i7-12700H vs 4-Core i5-9300H</div>
      </div>
      <div class="metric-card">
        <div class="label">Top GPU Graphics Leap</div>
        <div class="num">+110% <span style="font-size:1.1rem; color:var(--text-dim)">vs 1660Ti</span></div>
        <div class="sub-note">+238% faster than GTX 1650 (RTX 4060 / 3060 140W)</div>
      </div>
      <div class="metric-card">
        <div class="label">Lowest RTX 3060 Price</div>
        <div class="num">1,899 <span style="font-size:1.1rem; color:var(--text-dim)">PLN</span></div>
        <div class="sub-note">Acer Triton (1,899) &amp; Gigabyte G5 240Hz (1,999)</div>
      </div>
      <div class="metric-card">
        <div class="label">Chassis &amp; Display Winner</div>
        <div class="num" style="font-size:1.45rem; line-height: 1.4;">Legion 5 Pro 16</div>
        <div class="sub-note">16" QHD+ 165Hz 500 nits HDR400 + MUX Switch</div>
      </div>
    </div>
  </header>

  <!-- Architectural Pillars -->
  <section class="pillars-section">
    <div class="pillars-grid">
      <div class="pillar-card">
        <div class="pillar-icon">⚡</div>
        <h4 class="pillar-title">Full TGP vs Crippled Wattage</h4>
        <p class="pillar-desc">
          Budget laptops cap GPUs at 75W–85W. Machines like the <strong>Lenovo Legion 5 (130W)</strong> and <strong>HP Omen 17 (140W)</strong> feed maximum allowable power, yielding up to +25% higher real-world FPS on the exact same GPU silicon.
        </p>
        <span class="pillar-gain">▲ Up to +25% more frame rate on 130W–140W GPUs</span>
      </div>

      <div class="pillar-card">
        <div class="pillar-icon">🖥️</div>
        <h4 class="pillar-title">Display Quality Leap</h4>
        <p class="pillar-desc">
          Acer Nitro uses entry 250-nit 45% NTSC panels with slow pixel response. The <strong>Legion 5 Pro</strong> features a calibrated <strong>16" 2560x1600 500-nit HDR400 100% sRGB</strong> screen, while the <strong>Gigabyte G5</strong> delivers esports 240Hz.
        </p>
        <span class="pillar-gain">▲ 2× Brightness &amp; 100% sRGB Color Accuracy</span>
      </div>

      <div class="pillar-card">
        <div class="pillar-icon">🔄</div>
        <h4 class="pillar-title">Hardware MUX Switch</h4>
        <p class="pillar-desc">
          Without a MUX switch (like older Nitro models), discrete GPU frames route through the slow integrated Intel GPU before the display, causing a 10–15% FPS bottleneck and micro-stutter. Legion 5 and Omen 17 feature hardware MUX bypass.
        </p>
        <span class="pillar-gain">▲ +10% to +15% Free FPS via Direct Display Pipe</span>
      </div>

      <div class="pillar-card">
        <div class="pillar-icon">❄️</div>
        <h4 class="pillar-title">Vapor Chambers &amp; PTM7950</h4>
        <p class="pillar-desc">
          Instead of single-heatpipe throttled cooling, premium chassis utilize dual large-diameter fans, four high-density copper exhausts, and industrial phase-change pads (Honeywell PTM7950) that never dry out or pump out over time.
        </p>
        <span class="pillar-gain">▲ 15–20°C Cooler Thermals Under Continuous Load</span>
      </div>
    </div>
  </section>

  <!-- Interactive Controls Bar -->
  <div class="controls-wrapper">
    <div class="controls-bar">
      <!-- Strategy Filter Tabs -->
      <div class="filter-tabs">
        <button class="tab-btn active" data-filter="all">All Top Performance Picks (18)</button>
        <button class="tab-btn" data-filter="flagship-power">🚀 14-Core &amp; 8-Core Compute Titans (12700H / Omen)</button>
        <button class="tab-btn" data-filter="legion-champions">👑 Legion 5 &amp; 5 Pro (Coldfront &amp; MUX)</button>
        <button class="tab-btn" data-filter="sub-2000-titans">⚡ Sub-2,000 PLN RTX 3060 Titans</button>
        <button class="tab-btn" data-filter="next-gen-ada">💎 Next-Gen Ada Lovelace (RTX 4060 / DLSS 3)</button>
        <button class="tab-btn" data-filter="budget-steals">💰 High-Value Steals (&le; 1,650 PLN)</button>
        <button class="tab-btn" data-filter="ultraportable">🪶 Ultraportable Studio (Zephyrus G14 1.7kg)</button>
      </div>

      <!-- Search & Sort Row -->
      <div class="filter-inputs">
        <input type="text" id="searchInput" class="input-box" placeholder="Search by model, CPU (12700H, 5800H), GPU (3060, 4060), display, or town...">
        
        <select id="sortSelect" class="select-box">
          <option value="roi-desc">Sort: Best Overall Value &amp; ROI</option>
          <option value="cpu-desc">Sort: CPU Compute (Multi-Core Power)</option>
          <option value="gpu-desc">Sort: GPU Muscle (Graphics Power)</option>
          <option value="price-asc">Sort: Price (Lowest First)</option>
          <option value="price-desc">Sort: Price (Highest First)</option>
        </select>

        <select id="maxPriceSelect" class="select-box">
          <option value="9999">Max Price: Any</option>
          <option value="1650">Max Price: 1,650 PLN</option>
          <option value="2000">Max Price: 2,000 PLN</option>
          <option value="2300">Max Price: 2,300 PLN</option>
          <option value="2600">Max Price: 2,600 PLN</option>
        </select>

        <div class="view-toggle">
          <button class="toggle-btn active" id="viewCardsBtn" title="Cards View">Cards</button>
          <button class="toggle-btn" id="viewTableBtn" title="Table View">Table</button>
        </div>
      </div>
    </div>
  </div>

  <main>
    <div class="section-headline">
      <h3 id="currentCategoryTitle">Curated Candidate Laptops</h3>
      <div class="count-indicator" id="showingCount">Showing 18 offers</div>
    </div>

    <!-- Cards Grid Container -->
    <div class="cards-grid" id="cardsContainer">
      <!-- Populated via JavaScript -->
    </div>

    <!-- Table View Container -->
    <div class="table-container" id="tableContainer">
      <table>
        <thead>
          <tr>
            <th>Model &amp; Title</th>
            <th>Category</th>
            <th>Price</th>
            <th>CPU &amp; Cores</th>
            <th>CPU vs 9300H</th>
            <th>GPU &amp; TGP</th>
            <th>GPU vs 1660Ti</th>
            <th>Display</th>
            <th>RAM &amp; Storage</th>
            <th>Location</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <!-- Populated via JavaScript -->
        </tbody>
      </table>
    </div>

    <!-- Pitfalls Section -->
    <section class="pitfalls-section">
      <div class="pitfalls-card">
        <div class="pitfalls-header">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          Deceptive Traps &amp; Filtered Listings in High-Performance Segment
        </div>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 16px;">
          When shopping for used RTX laptops on OLX, automated extraction flagged severe hidden flaws in seemingly cheap listings:
        </p>
        <div class="pitfalls-grid">
          <div class="pitfall-item">
            <div class="pitfall-title">Acer Nitro 5 AN515-55 (bez dysku)</div>
            <div class="pitfall-desc">Seller advertises RTX 2060, but buried in description admits: <em>"nie wykrywa karty graficznej"</em> (dead dGPU, only integrated Intel graphics work).</div>
            <div class="pitfall-price">899 PLN (Trap!)</div>
          </div>
          <div class="pitfall-item">
            <div class="pitfall-title">Lenovo Legion 5 Pro 16ACH6 (1,800 PLN)</div>
            <div class="pitfall-desc">Price looks tempting for a Legion Pro, but seller admits: <em>"dwie małe plamki na ekranie oraz lekkie pęknięcie"</em> (damaged panel and chassis crack).</div>
            <div class="pitfall-price">1,800 PLN (Impaired)</div>
          </div>
          <div class="pitfall-item">
            <div class="pitfall-title">Desktop GPU / PC Listings Masked as Laptops</div>
            <div class="pitfall-desc">Sellers tagging desktop graphics cards (e.g. <em>"ASUS TUF RTX 3060 Ti karta graficzna jak nowa"</em>) or desktop towers under the laptop category. Filtered out.</div>
            <div class="pitfall-price">1,499–1,850 PLN (Not Laptops)</div>
          </div>
          <div class="pitfall-item">
            <div class="pitfall-title">Dell XPS 15 7590 (4K OLED)</div>
            <div class="pitfall-desc">Broken DC barrel charger jack, completely missing internal battery, powered only via secondary 65W USB-C charger which limits CPU throttling.</div>
            <div class="pitfall-price">1,199 PLN (Missing Battery)</div>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <p>Generated for pair programming analysis &bull; Data queried live from <code>packages/server/data/scrappy.db</code> &bull; All outbound links point directly to active OLX listings.</p>
  </footer>

  <script>
    // Master Dataset of Curated Offers
    const offers = {json_data};

    // State
    let activeFilter = 'all';
    let searchQuery = '';
    let sortMethod = 'roi-desc';
    let maxPrice = 9999;
    let currentView = 'cards';

    // DOM Elements
    const cardsContainer = document.getElementById('cardsContainer');
    const tableContainer = document.getElementById('tableContainer');
    const tableBody = document.getElementById('tableBody');
    const searchInput = document.getElementById('searchInput');
    const sortSelect = document.getElementById('sortSelect');
    const maxPriceSelect = document.getElementById('maxPriceSelect');
    const viewCardsBtn = document.getElementById('viewCardsBtn');
    const viewTableBtn = document.getElementById('viewTableBtn');
    const showingCount = document.getElementById('showingCount');
    const filterTabs = document.querySelectorAll('.tab-btn');

    // Filter & Sort Logic
    function getFilteredOffers() {{
      return offers.filter(offer => {{
        // Category Tab
        if (activeFilter !== 'all' && offer.category !== activeFilter) {{
          return false;
        }}
        // Max Price
        if (offer.price > maxPrice) {{
          return false;
        }}
        // Search text
        if (searchQuery.trim() !== '') {{
          const q = searchQuery.toLowerCase();
          const matchTitle = (offer.title || '').toLowerCase().includes(q);
          const matchCpu = (offer.cpu || '').toLowerCase().includes(q);
          const matchGpu = (offer.gpu || '').toLowerCase().includes(q);
          const matchLoc = (offer.location || '').toLowerCase().includes(q);
          const matchHigh = (offer.highlights || '').toLowerCase().includes(q);
          const matchDisplay = (offer.display || '').toLowerCase().includes(q);
          const matchChassis = (offer.chassisGrade || '').toLowerCase().includes(q);
          if (!matchTitle && !matchCpu && !matchGpu && !matchLoc && !matchHigh && !matchDisplay && !matchChassis) {{
            return false;
          }}
        }}
        return true;
      }}).sort((a, b) => {{
        if (sortMethod === 'price-asc') return a.price - b.price;
        if (sortMethod === 'price-desc') return b.price - a.price;
        if (sortMethod === 'cpu-desc') return b.cpuVsBaseline - a.cpuVsBaseline;
        if (sortMethod === 'gpu-desc') return b.gpuVsBaseline - a.gpuVsBaseline;
        return b.roiScore - a.roiScore; // roi-desc default
      }});
    }}

    // Render Cards
    function renderCards(list) {{
      cardsContainer.innerHTML = '';
      if (list.length === 0) {{
        cardsContainer.innerHTML = `
          <div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; color: var(--text-dim);">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 12px; opacity: 0.5;">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <p style="font-size: 1.1rem; color: var(--text-muted);">No laptops match your criteria.</p>
            <p style="font-size: 0.85rem;">Try widening your price limit or clearing the search query.</p>
          </div>
        `;
        return;
      }}

      list.forEach(offer => {{
        const card = document.createElement('div');
        card.className = 'offer-card';

        // Calculate progress bar width based on CPU vs baseline (baseline is 100%, max is 380%)
        const cpuWidth = Math.min(100, Math.round((offer.cpuVsBaseline / 380) * 100));
        // Calculate GPU progress bar width based on GPU vs baseline (baseline 1660Ti is 100%, max 4060 is 210%)
        const gpuWidth = Math.min(100, Math.round((offer.gpuVsBaseline / 210) * 100));

        card.innerHTML = `
          <div class="card-top">
            <span class="badge-roi ${{offer.badge.type}}">
              ${{offer.badge.text}} &bull; ROI ${{offer.roiScore}}/100
            </span>
            <div class="price-box">
              <div>
                <span class="price-amount">${{offer.price}}</span>
                <span class="price-currency">PLN</span>
              </div>
              ${{offer.negotiable ? '<span class="price-negotiable">Do negocjacji</span>' : ''}}
            </div>
          </div>

          <h4 class="card-title">${{offer.title}}</h4>

          <div class="pills-cloud">
            <span class="pill cpu">${{offer.cpu}}</span>
            <span class="pill gpu">${{offer.gpu}}</span>
            <span class="pill refresh">${{offer.display}}</span>
            <span class="pill chassis">🛡️ ${{offer.chassisGrade}}</span>
          </div>

          <!-- Dual Performance Meters -->
          <div class="meter-box">
            <div class="meter-row">
              <div class="meter-header">
                <span>Multi-Core Compute vs i5-9300H</span>
                <span style="color: ${{offer.cpuVsBaseline >= 200 ? 'var(--accent-emerald)' : 'var(--accent-blue)'}}">
                  ${{offer.cpuPercentText}}
                </span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${{cpuWidth}}%; background: ${{offer.colorBar}};"></div>
              </div>
            </div>

            <div class="meter-row">
              <div class="meter-header">
                <span>GPU Power vs GTX 1660 Ti</span>
                <span style="color: ${{offer.gpuVsBaseline >= 150 ? 'var(--accent-emerald)' : 'var(--accent-amber)'}}">
                  ${{offer.gpuPercentText}}
                </span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${{gpuWidth}}%; background: linear-gradient(90deg, #f59e0b, #10b981);"></div>
              </div>
            </div>
          </div>

          <div class="card-highlights">
            ${{offer.highlights}}
          </div>

          <div class="card-meta">
            <span class="location-text">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/>
                <circle cx="12" cy="10" r="3"/>
              </svg>
              ${{offer.location}}
            </span>
            <a href="${{offer.url}}" target="_blank" rel="noopener noreferrer" class="btn-link">
              View on OLX
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </a>
          </div>
        `;
        cardsContainer.appendChild(card);
      }});
    }}

    // Render Table
    function renderTable(list) {{
      tableBody.innerHTML = '';
      if (list.length === 0) {{
        tableBody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding: 40px; color: var(--text-dim);">No offers found.</td></tr>`;
        return;
      }}

      list.forEach(offer => {{
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><strong>${{offer.title}}</strong></td>
          <td><span class="badge-roi ${{offer.badge.type}}">${{offer.badge.text}}</span></td>
          <td><strong style="color: #fff; font-size: 1.05rem;">${{offer.price}} PLN</strong></td>
          <td><span style="color: var(--accent-blue); font-weight:600;">${{offer.cpu}}</span><br><small style="color: var(--text-dim);">${{offer.cpuCores}}</small></td>
          <td><strong style="color: ${{offer.cpuVsBaseline >= 200 ? 'var(--accent-emerald)' : 'var(--accent-blue)'}}">${{offer.cpuPercentText}}</strong></td>
          <td><span style="color: var(--accent-amber); font-weight:600;">${{offer.gpu}}</span></td>
          <td><strong style="color: ${{offer.gpuVsBaseline >= 150 ? 'var(--accent-emerald)' : 'var(--accent-amber)'}}">${{offer.gpuPercentText}}</strong></td>
          <td>${{offer.display}}</td>
          <td>${{offer.ram}} &bull; ${{offer.storage}}</td>
          <td><small style="color: var(--text-dim);">${{offer.location}}</small></td>
          <td>
            <a href="${{offer.url}}" target="_blank" rel="noopener noreferrer" class="btn-link" style="padding: 4px 10px; font-size: 0.78rem;">
              OLX &rarr;
            </a>
          </td>
        `;
        tableBody.appendChild(row);
      }});
    }}

    // Master Update
    function updateUI() {{
      const list = getFilteredOffers();
      showingCount.textContent = `Showing ${{list.length}} of ${{offers.length}} power offers`;
      if (currentView === 'cards') {{
        cardsContainer.style.display = 'grid';
        tableContainer.style.display = 'none';
        renderCards(list);
      }} else {{
        cardsContainer.style.display = 'none';
        tableContainer.style.display = 'block';
        renderTable(list);
      }}
    }}

    // Event Listeners
    filterTabs.forEach(tab => {{
      tab.addEventListener('click', () => {{
        filterTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        activeFilter = tab.getAttribute('data-filter');
        document.getElementById('currentCategoryTitle').textContent = tab.textContent;
        updateUI();
      }});
    }});

    searchInput.addEventListener('input', (e) => {{
      searchQuery = e.target.value;
      updateUI();
    }});

    sortSelect.addEventListener('change', (e) => {{
      sortMethod = e.target.value;
      updateUI();
    }});

    maxPriceSelect.addEventListener('change', (e) => {{
      maxPrice = parseInt(e.target.value, 10);
      updateUI();
    }});

    viewCardsBtn.addEventListener('click', () => {{
      currentView = 'cards';
      viewCardsBtn.classList.add('active');
      viewTableBtn.classList.remove('active');
      updateUI();
    }});

    viewTableBtn.addEventListener('click', () => {{
      currentView = 'table';
      viewTableBtn.classList.add('active');
      viewCardsBtn.classList.remove('active');
      updateUI();
    }});

    // Initial render
    updateUI();
  </script>
</body>
</html>
'''

with open('analysis/nitro_7_alternatives.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("Updated analysis/nitro_7_alternatives.html successfully!")
