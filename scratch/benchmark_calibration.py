import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('packages/server/data/scrappy.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Baseline: i5-9300H (Cinebench R23 Multi ~4250, PassMark ~7800)
# Baseline GPU: GTX 1660 Ti 6GB (TimeSpy ~5500, PassMark 3D ~12500)

cpu_scores = {
    'i5-9300H': (100, '4C / 8T (14nm Skylake refresh)'),
    'i5-10300H': (110, '4C / 8T (14nm Comet Lake)'),
    'i5-10500H': (165, '6C / 12T (14nm Comet Lake)'),
    'i7-10750H': (175, '6C / 12T (14nm Comet Lake)'),
    'Ryzen 5 4600H': (190, '6C / 12T (7nm Zen 2)'),
    'Ryzen 5 5600H': (235, '6C / 12T (7nm Zen 3)'),
    'Ryzen 5 6600H': (250, '6C / 12T (6nm Zen 3+, RDNA2)'),
    'i5-11300H': (125, '4C / 8T (10nm SuperFin Tiger Lake)'),
    'i5-11320H': (130, '4C / 8T (10nm SuperFin Tiger Lake)'),
    'i5-11400H': (230, '6C / 12T (10nm SuperFin Tiger Lake)'),
    'Ryzen 7 4800H': (260, '8C / 16T (7nm Zen 2)'),
    'Ryzen 7 5800H': (310, '8C / 16T (7nm Zen 3)'),
    'Ryzen 7 5800HS': (300, '8C / 16T (7nm Zen 3 35W)'),
    'Ryzen 7 6800H': (330, '8C / 16T (6nm Zen 3+, RDNA2)'),
    'Ryzen 5 8645HS': (340, '6C / 12T (4nm Zen 4 + Ryzen AI NPU)'),
    'i7-11800H': (320, '8C / 16T (10nm SuperFin Tiger Lake, 24MB Cache)'),
    'i5-12450H': (260, '8C / 12T (Alder Lake, 4P + 4E)'),
    'i5-12500H': (315, '12C / 16T (Alder Lake, 4P + 8E)'),
    'i7-12650H': (325, '10C / 16T (Alder Lake, 6P + 4E)'),
    'i7-12700H': (380, '14C / 20T (Intel 7 Alder Lake, 6P + 8E)'),
}

# GPU scores relative to GTX 1660 Ti (100%):
gpu_scores = {
    'GTX 1650': (62, '4GB GDDR5/6 (Entry 1080p)'),
    'GTX 1650 Ti': (70, '4GB GDDR6 (Entry 1080p)'),
    'GTX 1660 Ti': (100, '6GB GDDR6 (Baseline 100%)'),
    'RTX 2060': (110, '6GB GDDR6 (DLSS 2, RT)'),
    'RTX 3050': (85, '4GB GDDR6 (Ampere, DLSS 2/3.5)'),
    'RTX 3050 Ti': (95, '4GB GDDR6 (Ampere, DLSS 2/3.5)'),
    'RTX 3060': (165, '6GB GDDR6 (Ampere 130W, 3840 CUDA, TimeSpy ~9000)'),
    'RTX 4050': (175, '6GB GDDR6 (Ada Lovelace, DLSS 3 Frame Gen)'),
    'RTX 4060': (210, '8GB GDDR6 (Ada Lovelace, DLSS 3 Frame Gen, 8GB VRAM)'),
}

print("Benchmarks initialized.")
