import json

with open("scratch/processed_laptops.json", "r", encoding="utf-8") as f:
    laptops = json.load(f)

json_data = json.dumps(laptops, ensure_ascii=False)

html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cheap Linux Laptops ROI Guide & Deals Analyzer | OLX Market Data</title>
  <meta name="description" content="Data-driven buyer guide and live deal ranker for capable cheap Linux laptops under 750 PLN based on 4,973 scraped marketplace offers. Featuring ThinkPad, Latitude, and EliteBook models.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-primary: #090d16;
      --bg-secondary: #0f172a;
      --bg-card: rgba(17, 24, 39, 0.75);
      --bg-card-hover: rgba(26, 36, 56, 0.9);
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
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --shadow-card: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
      --shadow-glow: 0 0 30px -5px rgba(56, 189, 248, 0.25);
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
        radial-gradient(circle at 10% 15%, rgba(56, 189, 248, 0.08) 0%, transparent 45%),
        radial-gradient(circle at 90% 25%, rgba(168, 85, 247, 0.07) 0%, transparent 45%),
        radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.06) 0%, transparent 50%);
      background-attachment: fixed;
    }}

    header {{
      padding: 48px 24px 32px;
      max-width: 1440px;
      margin: 0 auto;
    }}

    .header-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent-blue);
      font-size: 0.82rem;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 16px;
    }}

    .header-badge span.dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-emerald);
      box-shadow: 0 0 10px var(--accent-emerald);
    }}

    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: clamp(2rem, 4vw, 3.2rem);
      font-weight: 800;
      line-height: 1.15;
      background: linear-gradient(135deg, #ffffff 30%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 14px;
    }}

    .header-desc {{
      color: var(--text-muted);
      font-size: 1.1rem;
      max-width: 860px;
      line-height: 1.6;
    }}

    .nav-shortcuts {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }}

    .nav-btn {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      font-size: 0.88rem;
      font-weight: 500;
      text-decoration: none;
      transition: all 0.2s ease;
      cursor: pointer;
    }}

    .nav-btn:hover {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--accent-blue);
      color: #ffffff;
      transform: translateY(-2px);
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 0 24px;
    }}

    /* KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 18px;
      margin-bottom: 40px;
    }}

    .kpi-card {{
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 22px;
      transition: all 0.25s ease;
      position: relative;
      overflow: hidden;
    }}

    .kpi-card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      background: linear-gradient(90deg, transparent, var(--card-accent, var(--accent-blue)), transparent);
      opacity: 0;
      transition: opacity 0.3s;
    }}

    .kpi-card:hover {{
      border-color: var(--border-accent);
      transform: translateY(-3px);
      box-shadow: var(--shadow-card);
    }}

    .kpi-card:hover::before {{
      opacity: 1;
    }}

    .kpi-label {{
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 8px;
    }}

    .kpi-value {{
      font-family: 'Outfit', sans-serif;
      font-size: 2.2rem;
      font-weight: 700;
      color: #ffffff;
      line-height: 1.1;
      margin-bottom: 6px;
    }}

    .kpi-subtext {{
      font-size: 0.85rem;
      color: var(--text-dim);
    }}

    /* Section Styling */
    section {{
      margin-bottom: 50px;
    }}

    .section-header {{
      margin-bottom: 24px;
    }}

    .section-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.6rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }}

    .section-title .badge {{
      font-size: 0.75rem;
      padding: 3px 10px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--accent-emerald);
      font-family: 'Inter', sans-serif;
      font-weight: 600;
    }}

    .section-desc {{
      color: var(--text-muted);
      font-size: 0.95rem;
      max-width: 900px;
    }}

    /* Architecture Benchmarking & Comparison */
    .arch-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
      margin-bottom: 24px;
    }}

    .arch-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 24px;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}

    .arch-card.highlight {{
      border-color: rgba(56, 189, 248, 0.4);
      background: linear-gradient(180deg, rgba(56, 189, 248, 0.08) 0%, rgba(17, 24, 39, 0.85) 100%);
      box-shadow: var(--shadow-glow);
    }}

    .arch-card.warning {{
      border-color: rgba(244, 63, 94, 0.3);
      background: linear-gradient(180deg, rgba(244, 63, 94, 0.05) 0%, rgba(17, 24, 39, 0.85) 100%);
    }}

    .arch-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.3rem;
      font-weight: 700;
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .arch-meta {{
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-bottom: 16px;
    }}

    .arch-specs {{
      list-style: none;
      margin-bottom: 20px;
    }}

    .arch-specs li {{
      font-size: 0.88rem;
      padding: 6px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      display: flex;
      justify-content: space-between;
    }}

    .arch-specs li span.label {{
      color: var(--text-dim);
    }}

    .arch-verdict {{
      padding: 12px 14px;
      border-radius: var(--radius-sm);
      font-size: 0.85rem;
      line-height: 1.45;
    }}

    .verdict-bad {{
      background: rgba(244, 63, 94, 0.1);
      border: 1px solid rgba(244, 63, 94, 0.25);
      color: #fda4af;
    }}

    .verdict-good {{
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      color: #6ee7b7;
    }}

    .verdict-gold {{
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: #bae6fd;
    }}

    /* Guide Callout Grid */
    .guide-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 18px;
    }}

    .guide-box {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px;
    }}

    .guide-box h4 {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.1rem;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .guide-box p {{
      color: var(--text-muted);
      font-size: 0.88rem;
      line-height: 1.55;
      margin-bottom: 10px;
    }}

    .guide-box code {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      background: rgba(0, 0, 0, 0.4);
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--accent-cyan);
    }}

    /* Spotlight Grid */
    .spotlight-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 20px;
      margin-bottom: 30px;
    }}

    .spotlight-card {{
      background: linear-gradient(145deg, rgba(17, 24, 39, 0.9) 0%, rgba(13, 19, 33, 0.95) 100%);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: var(--radius-md);
      padding: 24px;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.25s ease;
    }}

    .spotlight-card:hover {{
      border-color: var(--accent-blue);
      transform: translateY(-4px);
      box-shadow: 0 12px 30px -5px rgba(56, 189, 248, 0.2);
    }}

    .spotlight-badge {{
      position: absolute;
      top: 18px;
      right: 18px;
      background: rgba(16, 185, 129, 0.2);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: var(--accent-emerald);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .spotlight-price {{
      font-family: 'Outfit', sans-serif;
      font-size: 2.2rem;
      font-weight: 800;
      color: var(--accent-blue);
      margin-bottom: 4px;
    }}

    .spotlight-title {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.25rem;
      font-weight: 700;
      color: #ffffff;
      margin-bottom: 12px;
      line-height: 1.3;
    }}

    .spotlight-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 16px;
    }}

    .tag {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: var(--text-muted);
    }}

    .tag.blue {{
      background: rgba(56, 189, 248, 0.1);
      border-color: rgba(56, 189, 248, 0.25);
      color: var(--accent-blue);
    }}

    .tag.green {{
      background: rgba(16, 185, 129, 0.1);
      border-color: rgba(16, 185, 129, 0.25);
      color: var(--accent-emerald);
    }}

    .tag.purple {{
      background: rgba(168, 85, 247, 0.1);
      border-color: rgba(168, 85, 247, 0.25);
      color: var(--accent-purple);
    }}

    .spotlight-meta {{
      font-size: 0.85rem;
      color: var(--text-dim);
      margin-bottom: 16px;
    }}

    .btn-buy {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      background: var(--accent-blue);
      color: #090d16;
      font-weight: 700;
      font-size: 0.9rem;
      padding: 10px 18px;
      border-radius: var(--radius-sm);
      text-decoration: none;
      transition: all 0.2s ease;
      width: 100%;
    }}

    .btn-buy:hover {{
      background: #7dd3fc;
      transform: translateY(-2px);
      box-shadow: 0 4px 14px rgba(56, 189, 248, 0.4);
    }}

    /* Interactive Filters & Browser */
    .controls-panel {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 24px;
      margin-bottom: 24px;
    }}

    .controls-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    }}

    .controls-row:last-child {{
      margin-bottom: 0;
      padding-top: 16px;
      border-top: 1px solid rgba(255, 255, 255, 0.05);
    }}

    .search-box {{
      flex: 1;
      min-width: 260px;
      position: relative;
    }}

    .search-input {{
      width: 100%;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 10px 14px 10px 38px;
      color: #ffffff;
      font-size: 0.9rem;
      font-family: inherit;
      transition: all 0.2s;
    }}

    .search-input:focus {{
      outline: none;
      border-color: var(--accent-blue);
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
    }}

    .search-icon {{
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
    }}

    .filter-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}

    .filter-pill {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
      user-select: none;
    }}

    .filter-pill:hover {{
      background: rgba(255, 255, 255, 0.08);
      color: #ffffff;
    }}

    .filter-pill.active {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--accent-blue);
      color: var(--accent-blue);
      font-weight: 600;
    }}

    .range-control {{
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 0.85rem;
      color: var(--text-muted);
    }}

    .range-slider {{
      accent-color: var(--accent-blue);
      cursor: pointer;
      width: 130px;
    }}

    .sort-control {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .select-dropdown {{
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid var(--border-subtle);
      color: #ffffff;
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      font-size: 0.85rem;
      font-family: inherit;
      outline: none;
      cursor: pointer;
    }}

    .view-toggle {{
      display: flex;
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }}

    .view-btn {{
      background: transparent;
      border: none;
      color: var(--text-dim);
      padding: 8px 12px;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .view-btn.active {{
      background: rgba(56, 189, 248, 0.2);
      color: var(--accent-blue);
    }}

    /* Grid Results */
    .deals-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 18px;
    }}

    .deal-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.2s ease;
      position: relative;
    }}

    .deal-card:hover {{
      border-color: var(--border-accent);
      transform: translateY(-3px);
      box-shadow: var(--shadow-card);
    }}

    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
    }}

    .card-price {{
      font-family: 'Outfit', sans-serif;
      font-size: 1.7rem;
      font-weight: 700;
      color: #ffffff;
    }}

    .card-roi {{
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent-blue);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
    }}

    .card-title {{
      font-size: 1rem;
      font-weight: 600;
      color: #f1f5f9;
      margin-bottom: 12px;
      line-height: 1.35;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      min-height: 2.7em;
    }}

    .card-specs-list {{
      list-style: none;
      font-size: 0.83rem;
      color: var(--text-muted);
      margin-bottom: 16px;
    }}

    .card-specs-list li {{
      display: flex;
      justify-content: space-between;
      padding: 4px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }}

    .card-specs-list li span.val {{
      color: var(--text-main);
      font-weight: 500;
    }}

    .card-location {{
      font-size: 0.78rem;
      color: var(--text-dim);
      margin-bottom: 14px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .card-btn {{
      display: block;
      text-align: center;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border-subtle);
      color: var(--accent-blue);
      font-size: 0.85rem;
      font-weight: 600;
      padding: 9px;
      border-radius: var(--radius-sm);
      text-decoration: none;
      transition: all 0.2s;
    }}

    .card-btn:hover {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--accent-blue);
      color: #ffffff;
    }}

    /* Table View */
    .table-container {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      overflow-x: auto;
      display: none;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.88rem;
    }}

    th {{
      background: rgba(15, 23, 42, 0.95);
      color: var(--text-muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border-subtle);
      cursor: pointer;
      user-select: none;
    }}

    th:hover {{
      color: var(--accent-blue);
    }}

    td {{
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }}

    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    .table-link {{
      color: var(--accent-blue);
      text-decoration: none;
      font-weight: 600;
    }}

    .table-link:hover {{
      text-decoration: underline;
    }}

    .empty-state {{
      grid-column: 1 / -1;
      text-align: center;
      padding: 60px 20px;
      color: var(--text-dim);
    }}

    /* Footer */
    footer {{
      margin-top: 80px;
      border-top: 1px solid var(--border-subtle);
      padding: 40px 24px;
      text-align: center;
      color: var(--text-dim);
      font-size: 0.85rem;
    }}

    footer a {{
      color: var(--accent-blue);
      text-decoration: none;
    }}

    @media (max-width: 768px) {{
      header {{
        padding: 30px 16px 20px;
      }}
      .container {{
        padding: 0 16px;
      }}
      .controls-row {{
        flex-direction: column;
        align-items: stretch;
      }}
      .search-box {{
        width: 100%;
      }}
    }}
  </style>
</head>
<body>

  <header id="top">
    <div class="header-badge">
      <span class="dot"></span> 4,973 Active Listings Scraped • OLX.pl
    </div>
    <h1>Cheap Linux Laptops: Maximum ROI Guide</h1>
    <p class="header-desc">
      A data-driven buyer guide and interactive deal ranker for capable second-hand notebooks under 750 PLN. 
      Filter live offers by quad-core architecture, expandable memory, and upstream Linux kernel compatibility.
    </p>

    <div class="nav-shortcuts">
      <a href="#spotlight" class="nav-btn">⭐ Top 5 Value Deals</a>
      <a href="#arch" class="nav-btn">⚡ Dual vs Quad-Core Analysis</a>
      <a href="#guide" class="nav-btn">🐧 Linux Compatibility Guide</a>
      <a href="#browser" class="nav-btn">🔍 Live Offers Browser ({len(laptops)})</a>
    </div>
  </header>

  <main class="container">

    <!-- KPI Summary Grid -->
    <div class="kpi-grid">
      <div class="kpi-card" style="--card-accent: var(--accent-blue);">
        <div class="kpi-label">Market Sweet Spot (16GB RAM)</div>
        <div class="kpi-value">550 <span style="font-size: 1.1rem; color: var(--accent-blue);">PLN</span></div>
        <div class="kpi-subtext">Median price for 16GB RAM quad-core business notebooks (183 offers analyzed)</div>
      </div>

      <div class="kpi-card" style="--card-accent: var(--accent-emerald);">
        <div class="kpi-label">Dual vs Quad-Core Price Delta</div>
        <div class="kpi-value">+62 <span style="font-size: 1.1rem; color: var(--accent-emerald);">PLN</span></div>
        <div class="kpi-subtext">Avg 515 PLN (7th gen dual) vs 577 PLN (8th gen quad) — 100% more cores for 12% extra cost</div>
      </div>

      <div class="kpi-card" style="--card-accent: var(--accent-purple);">
        <div class="kpi-label">Open-Source Driver Rate</div>
        <div class="kpi-value">100%</div>
        <div class="kpi-subtext">Intel UHD & AMD Radeon Vega work out of the box with zero proprietary binary blob hassle</div>
      </div>

      <div class="kpi-card" style="--card-accent: var(--accent-cyan);">
        <div class="kpi-label">Firmware Support (LVFS)</div>
        <div class="kpi-value">fwupd</div>
        <div class="kpi-subtext">Lenovo ThinkPad & Dell Latitude allow direct UEFI updates via terminal: <code>fwupdmgr update</code></div>
      </div>
    </div>

    <!-- Spotlight Top Deals -->
    <section id="spotlight">
      <div class="section-header">
        <h2 class="section-title">
          ⭐ Editor's Choice: Top 5 Active Value Deals
          <span class="badge">Tested &amp; Undamaged</span>
        </h2>
        <p class="section-desc">
          These five listings represent the highest benchmark return on investment currently active in the database.
          They offer modern 4-core/8-thread processors, 8–16GB RAM, and pristine Linux compatibility for 300–550 PLN.
        </p>
      </div>

      <div class="spotlight-grid">

        <!-- Deal 1 -->
        <div class="spotlight-card">
          <span class="spotlight-badge">#1 Overall ROI</span>
          <div>
            <div class="spotlight-price">500 PLN</div>
            <h3 class="spotlight-title">Lenovo ThinkPad T495</h3>
            <div class="spotlight-tags">
              <span class="tag green">Ryzen 5 Pro 3500U</span>
              <span class="tag blue">16 GB DDR4</span>
              <span class="tag purple">256 GB NVMe</span>
              <span class="tag">14" FHD IPS</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              Enterprise AMD Ryzen Pro with integrated Vega 8 GPU (AMDGPU kernel driver). Outstanding Wayland &amp; desktop Linux performance, pre-configured with 16GB dual-channel memory.
            </p>
            <div class="spotlight-meta">📍 Warszawa, Mazowieckie • Verified working with charger</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/laptop-lenovo-thinkpad-t495-ryzen-5-pro-pamiec-16-gb-ddr4-dysk-256-gb-nvme-windows-11-pro-CID99-ID1bxa65.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

        <!-- Deal 2 -->
        <div class="spotlight-card">
          <span class="spotlight-badge">15.6" Workhorse</span>
          <div>
            <div class="spotlight-price">500 PLN</div>
            <h3 class="spotlight-title">Lenovo ThinkPad T580</h3>
            <div class="spotlight-tags">
              <span class="tag blue">Intel i5-8250U (4C/8T)</span>
              <span class="tag green">16 GB RAM</span>
              <span class="tag purple">256 GB NVMe</span>
              <span class="tag">15.6" FHD IPS</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              Large screen with numpad, dual SO-DIMM sockets (upgradable up to 64GB DDR4), dual battery support (PowerBridge), and backlit keyboard.
            </p>
            <div class="spotlight-meta">📍 Warszawa, Mazowieckie • Working battery &amp; backlit keys</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/laptop-lenovo-t580-intel-i5-8250-pamiec-16gb-ram-dysk-256-gb-nvme-CID99-ID1bHwUa.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

        <!-- Deal 3 -->
        <div class="spotlight-card">
          <span class="spotlight-badge">Whisper Quiet</span>
          <div>
            <div class="spotlight-price">550 PLN</div>
            <h3 class="spotlight-title">Lenovo ThinkPad L490</h3>
            <div class="spotlight-tags">
              <span class="tag blue">Intel i5-8265U (3.9 GHz)</span>
              <span class="tag green">16 GB DDR4</span>
              <span class="tag purple">256 GB SSD</span>
              <span class="tag">14" FHD IPS</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              Whiskey Lake i5 architecture running at up to 3.9GHz boost. 16GB RAM, Full HD IPS screen, clean chassis with ~2.5h battery runtime.
            </p>
            <div class="spotlight-meta">📍 Warszawa, Mazowieckie • Solid battery health</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/laptop-lenovo-l490-i5-8265u-16gb-256gb-ssd-w11-CID99-ID1bHX54.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

        <!-- Deal 4 -->
        <div class="spotlight-card">
          <span class="spotlight-badge">Sub-500 Bargain</span>
          <div>
            <div class="spotlight-price">400 PLN</div>
            <h3 class="spotlight-title">Dell Latitude 5400</h3>
            <div class="spotlight-tags">
              <span class="tag blue">Intel i5-8265U (4C/8T)</span>
              <span class="tag">8 GB DDR4</span>
              <span class="tag purple">256 GB SSD</span>
              <span class="tag">14" Full HD</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              Pristine enterprise Dell Latitude with backlit keyboard and working battery. Dual SO-DIMM slots allow dropping in another 8GB stick for 40 PLN.
            </p>
            <div class="spotlight-meta">📍 Warszawa, Mazowieckie • Verified working with charger</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/laptop-dell-5400-i5-8265-CID99-ID16HtF2.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

        <!-- Deal 5 -->
        <div class="spotlight-card">
          <span class="spotlight-badge">Lowest Price Floor</span>
          <div>
            <div class="spotlight-price">300 PLN</div>
            <h3 class="spotlight-title">HP ProBook 440 G6</h3>
            <div class="spotlight-tags">
              <span class="tag blue">Intel i5-8265U (4C/8T)</span>
              <span class="tag">8 GB DDR4</span>
              <span class="tag">128 GB SSD</span>
              <span class="tag">14" Compact</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              An unbelievable price for a 4-core, 8-thread modern laptop. Price is negotiable. Just swap in a 512GB NVMe SSD and you have a sub-400 PLN powerhouse.
            </p>
            <div class="spotlight-meta">📍 Warszawa, Mazowieckie • Negotiable price</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/profesjonalny-laptop-probook-hp-440-g6-CID99-ID1c9mrC.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

        <!-- Deal 6 (T480 Cult Classic) -->
        <div class="spotlight-card">
          <span class="spotlight-badge">Linux Cult Classic</span>
          <div>
            <div class="spotlight-price">650 PLN</div>
            <h3 class="spotlight-title">Lenovo ThinkPad T480</h3>
            <div class="spotlight-tags">
              <span class="tag blue">Intel i5 8th Gen</span>
              <span class="tag green">16 GB RAM</span>
              <span class="tag purple">256 GB NVMe</span>
              <span class="tag">14" FHD IPS</span>
            </div>
            <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 14px;">
              The community benchmark for portable Linux. Dual batteries (internal + hot-swappable external), dual Thunderbolt 3 ports, and endless replacement parts availability.
            </p>
            <div class="spotlight-meta">📍 Borek, Wielkopolskie • Full HD IPS Panel</div>
          </div>
          <a href="https://www.olx.pl/d/oferta/laptop-lenovo-thinkpad-t480-w-dobrym-stanie-CID99-ID1cBUVX.html" target="_blank" rel="noopener" class="btn-buy">
            Open Offer on OLX ↗
          </a>
        </div>

      </div>
    </section>

    <!-- Architecture & ROI Benchmark -->
    <section id="arch">
      <div class="section-header">
        <h2 class="section-title">⚡ The Architecture Value Gap: Avoid the Dual-Core Trap</h2>
        <p class="section-desc">
          Analysis of 2,300+ listings between 250 and 750 PLN shows that older dual-core laptops are severely overpriced relative to their 8th Gen quad-core successors.
        </p>
      </div>

      <div class="arch-grid">
        <!-- Dual Core Card -->
        <div class="arch-card warning">
          <div>
            <div class="arch-title">
              Dual-Core Intel (6th / 7th Gen)
              <span style="color: var(--accent-rose); font-size: 0.9rem;">⚠️ Poor ROI</span>
            </div>
            <div class="arch-meta">e.g. i5-6200U, i5-6300U, i5-7200U (T460, T470, E5470)</div>
            <ul class="arch-specs">
              <li><span class="label">Cores / Threads:</span> <span style="color: var(--accent-rose); font-weight: 600;">2 Cores / 4 Threads</span></li>
              <li><span class="label">Market Avg Price:</span> <span>515 PLN (189 active offers)</span></li>
              <li><span class="label">Hardware Video Decode:</span> <span>Missing 10-bit VP9 / modern codecs</span></li>
              <li><span class="label">Multitasking:</span> <span>High latency with modern JS/Electron &amp; compile jobs</span></li>
            </ul>
          </div>
          <div class="arch-verdict verdict-bad">
            <strong>Verdict: Avoid unless below 250 PLN.</strong> Sellers still ask ~500 PLN for these older chips, even though they lack the physical cores to handle modern web workflows smoothly.
          </div>
        </div>

        <!-- 8th Gen Quad Core Card -->
        <div class="arch-card highlight">
          <div>
            <div class="arch-title">
              Quad-Core Intel (8th Gen Core)
              <span style="color: var(--accent-blue); font-size: 0.9rem;">🏆 Sweet Spot</span>
            </div>
            <div class="arch-meta">e.g. i5-8250U, i5-8265U, i5-8350U (T480, L490, 5400, 7490)</div>
            <ul class="arch-specs">
              <li><span class="label">Cores / Threads:</span> <span style="color: var(--accent-emerald); font-weight: 600;">4 Cores / 8 Threads (+100%)</span></li>
              <li><span class="label">Market Avg Price:</span> <span>577 PLN (Starts at 300 PLN!)</span></li>
              <li><span class="label">Hardware Video Decode:</span> <span>Full VP9 / H.265 10-bit VA-API acceleration</span></li>
              <li><span class="label">Power &amp; Charging:</span> <span>USB-C Power Delivery standard</span></li>
            </ul>
          </div>
          <div class="arch-verdict verdict-good">
            <strong>Verdict: Best Value Per Złoty.</strong> For an average premium of just 62 PLN over a dual-core, you get double the CPU capacity and seamless modern Linux performance.
          </div>
        </div>

        <!-- AMD Ryzen Pro Card -->
        <div class="arch-card">
          <div>
            <div class="arch-title">
              AMD Ryzen Pro (3000 / 4000)
              <span style="color: var(--accent-emerald); font-size: 0.9rem;">🚀 GPU Champion</span>
            </div>
            <div class="arch-meta">e.g. Ryzen 5 Pro 3500U, Ryzen 5 4500U (T495, EliteBook 745)</div>
            <ul class="arch-specs">
              <li><span class="label">Cores / Threads:</span> <span style="color: var(--accent-emerald); font-weight: 600;">4C/8T or 6C/6T</span></li>
              <li><span class="label">Market Avg Price:</span> <span>605 PLN (Starts at 500 PLN)</span></li>
              <li><span class="label">Integrated Graphics:</span> <span style="color: var(--accent-emerald);">Radeon Vega 8 (AMDGPU kernel)</span></li>
              <li><span class="label">Wayland / Compositing:</span> <span>Superb frame pacing &amp; render smoothness</span></li>
            </ul>
          </div>
          <div class="arch-verdict verdict-gold">
            <strong>Verdict: Ideal for UI &amp; Graphics.</strong> The open-source AMDGPU driver is integrated directly into the Linux kernel with zero out-of-tree setup.
          </div>
        </div>
      </div>
    </section>

    <!-- Linux Buyer's Guide & Verification Checklist -->
    <section id="guide">
      <div class="section-header">
        <h2 class="section-title">🐧 Linux Buyer's Checklist on OLX</h2>
        <p class="section-desc">
          Four critical verification steps to ensure smooth hardware onboarding before completing a purchase.
        </p>
      </div>

      <div class="guide-grid">
        <div class="guide-box">
          <h4>🔒 1. BIOS / UEFI Password Lock</h4>
          <p>
            Many corporate off-lease laptops still have administrative BIOS locks (<code>bios_locked</code>) or Computrace active. Always ask the seller in OLX chat:
          </p>
          <p style="font-style: italic; color: #bae6fd;">
            "Czy BIOS jest odblokowany i można zmienić bootowanie na pendrive USB / wyłączyć Secure Boot?"
          </p>
        </div>

        <div class="guide-box">
          <h4>🖥️ 2. Screen Resolution (FHD vs HD)</h4>
          <p>
            Aim for <strong>1920x1080 (Full HD IPS)</strong>. Avoid 1366x768 (HD TN) panels: they have poor viewing angles and low pixel density that degrades terminal and editor readability.
          </p>
          <p>
            Check listing photos or search the exact serial/model number to confirm IPS panel specs.
          </p>
        </div>

        <div class="guide-box">
          <h4>⚡ 3. ThinkPad T480 Thunderbolt Patch</h4>
          <p>
            Early 2018 ThinkPads had an Intel Thunderbolt firmware bug that caused controller write-wear. On Linux, this is a one-minute fix:
          </p>
          <p>
            Simply run <code>fwupdmgr refresh && fwupdmgr update</code> to flash the patched firmware directly via LVFS.
          </p>
        </div>

        <div class="guide-box">
          <h4>🔋 4. Battery Health &amp; PowerBridge</h4>
          <p>
            ThinkPad T480 and T580 feature two batteries: one internal, one external hot-swappable. Replacement external batteries (e.g. 72Wh 6-cell) cost under 100 PLN on Allegro.
          </p>
          <p>
            On Linux, install <code>tlp</code> or <code>auto-cpufreq</code> for optimal thermal throttling and battery longevity.
          </p>
        </div>
      </div>
    </section>

    <!-- Live Offers Browser -->
    <section id="browser">
      <div class="section-header">
        <h2 class="section-title">
          🔍 Live Offers Browser
          <span class="badge" id="resultsCount">{len(laptops)} Matching Offers</span>
        </h2>
        <p class="section-desc">
          Real-time interactive filter across verified active quad-core and high-ROI laptop listings.
        </p>
      </div>

      <div class="controls-panel">
        <div class="controls-row">
          <!-- Text Search -->
          <div class="search-box">
            <span class="search-icon">🔍</span>
            <input type="text" id="searchInput" class="search-input" placeholder="Search by model, CPU, location (e.g. T480, 16GB, Warszawa)...">
          </div>

          <!-- Price Slider -->
          <div class="range-control">
            <span>Max Price:</span>
            <input type="range" id="priceRange" class="range-slider" min="300" max="750" step="25" value="750">
            <strong id="priceDisplay" style="color: var(--accent-blue); min-width: 65px;">750 PLN</strong>
          </div>

          <!-- Sort Select -->
          <div class="sort-control">
            <span style="font-size: 0.85rem; color: var(--text-muted);">Sort:</span>
            <select id="sortSelect" class="select-dropdown">
              <option value="roi">Best ROI Score</option>
              <option value="price_asc">Price: Low to High</option>
              <option value="price_desc">Price: High to Low</option>
              <option value="ram_desc">RAM: Highest First</option>
            </select>
          </div>

          <!-- View Toggle -->
          <div class="view-toggle">
            <button id="viewGridBtn" class="view-btn active" title="Grid View">🔲 Grid</button>
            <button id="viewTableBtn" class="view-btn" title="Table View">📋 Table</button>
          </div>
        </div>

        <div class="controls-row">
          <!-- Brand Filter Pills -->
          <div class="filter-pills" id="brandPills">
            <span style="font-size: 0.82rem; color: var(--text-dim); margin-right: 4px;">Brand:</span>
            <button class="filter-pill active" data-brand="all">All Brands</button>
            <button class="filter-pill" data-brand="ThinkPad">ThinkPad</button>
            <button class="filter-pill" data-brand="Dell Latitude">Dell Latitude</button>
            <button class="filter-pill" data-brand="HP Elite/ProBook">HP ProBook / EliteBook</button>
            <button class="filter-pill" data-brand="Other">Other</button>
          </div>

          <!-- RAM Filter Pills -->
          <div class="filter-pills" id="ramPills">
            <span style="font-size: 0.82rem; color: var(--text-dim); margin-right: 4px;">Min RAM:</span>
            <button class="filter-pill active" data-ram="0">All</button>
            <button class="filter-pill" data-ram="8">8 GB+</button>
            <button class="filter-pill" data-ram="16">16 GB+</button>
          </div>
        </div>
      </div>

      <!-- Results Grid -->
      <div id="dealsGrid" class="deals-grid">
        <!-- Injected via JavaScript -->
      </div>

      <!-- Results Table -->
      <div id="tableContainer" class="table-container">
        <table>
          <thead>
            <tr>
              <th onclick="handleSort('title')">Model</th>
              <th onclick="handleSort('price')">Price</th>
              <th onclick="handleSort('cpu')">CPU</th>
              <th onclick="handleSort('cores')">Cores</th>
              <th onclick="handleSort('ram')">RAM</th>
              <th onclick="handleSort('storage')">Storage</th>
              <th onclick="handleSort('res')">Display</th>
              <th onclick="handleSort('roi_score')">ROI Score</th>
              <th>Location</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody id="tableBody">
            <!-- Injected via JavaScript -->
          </tbody>
        </table>
      </div>

    </section>

  </main>

  <footer>
    <p>
      Database snapshot generated from <strong>scrappy-data</strong> on active marketplace listings.
      All prices in Polish Złoty (PLN). Links point directly to OLX.pl seller listings.
    </p>
    <p style="margin-top: 8px;">
      <a href="#top">Back to top ↑</a>
    </p>
  </footer>

  <script>
    const laptopsData = {json_data};

    // State
    let currentBrand = 'all';
    let currentMinRam = 0;
    let currentMaxPrice = 750;
    let currentSearch = '';
    let currentSort = 'roi';
    let currentView = 'grid';

    // Elements
    const searchInput = document.getElementById('searchInput');
    const priceRange = document.getElementById('priceRange');
    const priceDisplay = document.getElementById('priceDisplay');
    const sortSelect = document.getElementById('sortSelect');
    const dealsGrid = document.getElementById('dealsGrid');
    const tableContainer = document.getElementById('tableContainer');
    const tableBody = document.getElementById('tableBody');
    const resultsCount = document.getElementById('resultsCount');
    const viewGridBtn = document.getElementById('viewGridBtn');
    const viewTableBtn = document.getElementById('viewTableBtn');

    // Event Listeners
    searchInput.addEventListener('input', (e) => {{
      currentSearch = e.target.value.toLowerCase().trim();
      render();
    }});

    priceRange.addEventListener('input', (e) => {{
      currentMaxPrice = parseInt(e.target.value);
      priceDisplay.textContent = `${{currentMaxPrice}} PLN`;
      render();
    }});

    sortSelect.addEventListener('change', (e) => {{
      currentSort = e.target.value;
      render();
    }});

    // Brand pills
    document.querySelectorAll('#brandPills .filter-pill').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('#brandPills .filter-pill').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentBrand = btn.dataset.brand;
        render();
      }});
    }});

    // RAM pills
    document.querySelectorAll('#ramPills .filter-pill').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('#ramPills .filter-pill').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentMinRam = parseInt(btn.dataset.ram);
        render();
      }});
    }});

    // View toggles
    viewGridBtn.addEventListener('click', () => {{
      currentView = 'grid';
      viewGridBtn.classList.add('active');
      viewTableBtn.classList.remove('active');
      dealsGrid.style.display = 'grid';
      tableContainer.style.display = 'none';
    }});

    viewTableBtn.addEventListener('click', () => {{
      currentView = 'table';
      viewTableBtn.classList.add('active');
      viewGridBtn.classList.remove('active');
      dealsGrid.style.display = 'none';
      tableContainer.style.display = 'block';
    }});

    function filterAndSortLaptops() {{
      return laptopsData.filter(item => {{
        if (item.price > currentMaxPrice) return false;
        if (item.ram < currentMinRam) return false;
        if (currentBrand !== 'all' && item.brand !== currentBrand) return false;

        if (currentSearch) {{
          const searchStr = `${{item.title}} ${{item.cpu}} ${{item.loc}} ${{item.brand}} ${{item.arch}}`.toLowerCase();
          if (!searchStr.includes(currentSearch)) return false;
        }}

        return true;
      }}).sort((a, b) => {{
        if (currentSort === 'roi') return b.roi_score - a.roi_score;
        if (currentSort === 'price_asc') return a.price - b.price;
        if (currentSort === 'price_desc') return b.price - a.price;
        if (currentSort === 'ram_desc') return b.ram - a.ram;
        return 0;
      }});
    }}

    function render() {{
      const filtered = filterAndSortLaptops();
      resultsCount.textContent = `${{filtered.length}} Matching Offers`;

      if (filtered.length === 0) {{
        dealsGrid.innerHTML = `
          <div class="empty-state">
            <h3>No matching offers found</h3>
            <p>Try loosening your search terms or expanding the maximum price filter.</p>
          </div>
        `;
        tableBody.innerHTML = `
          <tr><td colspan="10" style="text-align: center; padding: 40px; color: var(--text-dim);">No matching offers found</td></tr>
        `;
        return;
      }}

      // Render Grid Cards
      dealsGrid.innerHTML = filtered.map(item => {{
        const isHighRam = item.ram >= 16;
        const ramTag = isHighRam 
          ? `<span class="tag green">${{item.ram}} GB DDR4</span>`
          : `<span class="tag">${{item.ram}} GB DDR4</span>`;

        const isRyzen = item.arch.includes('Ryzen');
        const cpuTag = isRyzen
          ? `<span class="tag purple">${{item.cpu}}</span>`
          : `<span class="tag blue">${{item.cpu}}</span>`;

        const fhdTag = item.res.includes('1920')
          ? `<span class="tag blue">1080p FHD</span>`
          : `<span class="tag">HD Screen</span>`;

        return `
          <div class="deal-card">
            <div>
              <div class="card-top">
                <div class="card-price">${{item.price}} <span style="font-size: 0.95rem; color: var(--text-dim); font-weight: normal;">PLN</span></div>
                <div class="card-roi" title="Calculated ROI Score: Cores, RAM &amp; Screen value per 100 PLN">ROI ${{item.roi_score}}</div>
              </div>
              <h3 class="card-title" title="${{item.title}}">${{item.title}}</h3>

              <div class="spotlight-tags" style="margin-bottom: 12px;">
                ${{cpuTag}}
                ${{ramTag}}
                ${{fhdTag}}
              </div>

              <ul class="card-specs-list">
                <li><span class="label">CPU Architecture:</span> <span class="val">${{item.arch}}</span></li>
                <li><span class="label">Cores / Threads:</span> <span class="val">${{item.cores}}C / ${{item.threads}}T</span></li>
                <li><span class="label">Storage:</span> <span class="val">${{item.storage}} GB ${{item.storage_type.toUpperCase()}}</span></li>
                <li><span class="label">Graphics:</span> <span class="val">${{item.gpu}}</span></li>
                <li><span class="label">Linux Support:</span> <span class="val" style="color: var(--accent-emerald);">${{item.linux_tier}}</span></li>
              </ul>
            </div>

            <div>
              <div class="card-location" title="${{item.loc}}">📍 ${{item.loc}}</div>
              <a href="${{item.url}}" target="_blank" rel="noopener" class="card-btn">
                View on OLX ↗
              </a>
            </div>
          </div>
        `;
      }}).join('');

      // Render Table Rows
      tableBody.innerHTML = filtered.map(item => `
        <tr>
          <td><strong style="color: #ffffff;">${{item.title}}</strong></td>
          <td><span style="font-family: 'Outfit'; font-weight: 700; color: var(--accent-blue);">${{item.price}} PLN</span></td>
          <td><span style="font-family: 'JetBrains Mono'; font-size: 0.82rem;">${{item.cpu}}</span></td>
          <td>${{item.cores}}C / ${{item.threads}}T</td>
          <td><strong style="${{item.ram >= 16 ? 'color: var(--accent-emerald);' : ''}}">${{item.ram}} GB</strong></td>
          <td>${{item.storage}} GB</td>
          <td><span style="font-size: 0.8rem; color: var(--text-muted);">${{item.res}}</span></td>
          <td><span style="font-family: 'JetBrains Mono'; color: var(--accent-blue); font-weight: 600;">${{item.roi_score}}</span></td>
          <td style="font-size: 0.8rem; color: var(--text-dim);">${{item.loc}}</td>
          <td><a href="${{item.url}}" target="_blank" rel="noopener" class="table-link">OLX ↗</a></td>
        </tr>
      `).join('');
    }}

    function handleSort(key) {{
      if (key === 'price') {{
        currentSort = currentSort === 'price_asc' ? 'price_desc' : 'price_asc';
      }} else if (key === 'ram') {{
        currentSort = 'ram_desc';
      }} else if (key === 'roi_score') {{
        currentSort = 'roi';
      }}
      sortSelect.value = currentSort;
      render();
    }}

    // Initial render
    render();
  </script>
</body>
</html>
'''

with open("analysis/cheap_linux_laptops_roi.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Generated analysis/cheap_linux_laptops_roi.html successfully with {len(laptops)} laptops!")
