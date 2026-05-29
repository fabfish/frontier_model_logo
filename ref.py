import os
import platform
import ctypes.util
import json

# macOS 下为 cairosvg 打补丁，使其能找到 Homebrew 安装的 cairo 动态库
if platform.system() == 'Darwin':
    _orig_find_library = ctypes.util.find_library
    def _patched_find_library(name):
        if name in ('cairo', 'cairo-2', 'libcairo-2', 'libcairo'):
            return '/opt/homebrew/lib/libcairo.dylib'
        return _orig_find_library(name)
    ctypes.util.find_library = _patched_find_library

import matplotlib
matplotlib.use('Agg')
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ---------------- 辅助函数：生成本地 Placeholder Logo ----------------
def generate_placeholder_logo(text, color, save_path, size=(200, 100)):
    """使用 PIL 在本地生成带文字和边框的 Placeholder Logo 图片，避免外部网络服务不可用。
    尺寸较大（200x100），后续绘图时通过 zoom 统一缩放，保证文字清晰。"""
    hex_color = color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    img = Image.new('RGBA', size, (*rgb, 255))
    draw = ImageDraw.Draw(img)

    font = None
    for font_path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_path, 36)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size[0] - text_w) // 2
    y = (size[1] - text_h) // 2
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    img.save(save_path, "PNG")
    return save_path


# ---------------- 辅助函数：下载并处理 Logo ----------------
def download_or_generate_logo(logo_url, brand, logo_dir, color):
    """
    根据 Logo_URL 下载真实 Logo，或在本地生成 Placeholder。
    同一家厂（Brand）的模型共用同一个 Logo 文件。
    Logo 统一存放在 logos/{Brand}/logo.png 子文件夹中，方便用户手动替换。
    支持 Wikipedia SVG 及第三方 CDN SVG 的自动转换。
    重要：已存在的本地文件绝不覆盖，尊重用户手动替换的成果。
    """
    brand_dir = os.path.join(logo_dir, brand.replace(' ', '_'))
    os.makedirs(brand_dir, exist_ok=True)
    save_path = os.path.join(brand_dir, "logo.png")

    # 已存在则直接返回（离线处理机制）
    if os.path.exists(save_path):
        return save_path

    is_svg = logo_url.lower().endswith(".svg")
    is_placeholder = "placeholder" in logo_url.lower() or "placehold" in logo_url.lower()

    if is_placeholder:
        generate_placeholder_logo(brand, color, save_path)
        return save_path

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    }
    for attempt in range(2):
        try:
            response = requests.get(logo_url, headers=headers, timeout=15)
            if response.status_code != 200:
                if attempt == 1:
                    print(f"  ⚠️ 下载失败 {brand} Logo, 状态码: {response.status_code}")
                continue

            content = response.content

            if is_svg or content[:5] == b'<?xml' or content[:4] == b'<svg':
                try:
                    import cairosvg
                    # 高分辨率转换，原样保存，不 resize，后续绘图时统一 zoom
                    png_data = cairosvg.svg2png(
                        bytestring=content, output_width=800, output_height=800
                    )
                    img = Image.open(BytesIO(png_data))
                except Exception as e:
                    if attempt == 1:
                        print(f"  ⚠️ SVG 转换失败 {brand}: {e}")
                    continue
            else:
                img = Image.open(BytesIO(content))

            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img.save(save_path, "PNG")
            return save_path

        except Exception as e:
            if attempt == 1:
                print(f"  ⚠️ 下载失败 {brand} Logo, 错误: {e}")

    return None


# ---------------- 1. 准备数据并保存为 xlsx ----------------
data = [
    {"Model": "GPT-4o", "Date": "2024-05-15", "Params_B": 1800, "Type": "International", "Brand": "OpenAI", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/4/4d/OpenAI_Logo.svg"},
    {"Model": "Step-2", "Date": "2024-07-15", "Params_B": 1000, "Type": "Domestic", "Brand": "Step", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/stepfun-color.png"},
    {"Model": "MiniCPM-V", "Date": "2024-08-15", "Params_B": 8, "Type": "Domestic", "Brand": "CPM", "Logo_URL": "https://avatars.githubusercontent.com/u/89920319?s=400&v=4"},
    {"Model": "Qwen2.5-VL", "Date": "2024-09-15", "Params_B": 72, "Type": "Domestic", "Brand": "Qwen", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/qwen-color.png"},
    {"Model": "DeepSeek-VL2", "Date": "2024-10-15", "Params_B": 27, "Type": "Domestic", "Brand": "DeepSeek", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/deepseek-color.png"},
    {"Model": "Claude 4 Opus", "Date": "2025-01-20", "Params_B": 1000, "Type": "International", "Brand": "Anthropic", "Logo_URL": "https://dl.svgcdn.com/svg/logos/anthropic-icon.svg"},
    {"Model": "Llama 4 Maverick", "Date": "2025-02-15", "Params_B": 400, "Type": "International", "Brand": "Meta", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/7/7b/Meta_Platforms_Inc._logo.svg"},
    {"Model": "Llama 4 Scout", "Date": "2025-02-15", "Params_B": 109, "Type": "International", "Brand": "Meta", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/7/7b/Meta_Platforms_Inc._logo.svg"},
    {"Model": "GPT-5", "Date": "2025-03-15", "Params_B": 1500, "Type": "International", "Brand": "OpenAI", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/4/4d/OpenAI_Logo.svg"},
    {"Model": "InternVL 3.0", "Date": "2025-04-15", "Params_B": 78, "Type": "Domestic", "Brand": "InternVL", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/internlm-color.png"},
    {"Model": "InternVL 3.5", "Date": "2025-05-15", "Params_B": 241, "Type": "Domestic", "Brand": "InternVL", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/internlm-color.png"},
    {"Model": "Kimi K2.5", "Date": "2025-08-15", "Params_B": 1000, "Type": "Domestic", "Brand": "Kimi", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/kimi-color.png"},
    {"Model": "Qwen3-VL", "Date": "2025-08-15", "Params_B": 235, "Type": "Domestic", "Brand": "Qwen", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/qwen-color.png"},
    {"Model": "Gemini 3.1 Pro", "Date": "2025-09-15", "Params_B": 1000, "Type": "International", "Brand": "Google", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg"},
    {"Model": "GLM-5", "Date": "2025-10-15", "Params_B": 744, "Type": "Domestic", "Brand": "GLM", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/zhipu-color.png"},
    {"Model": "Qwen3.5", "Date": "2025-11-15", "Params_B": 397, "Type": "Domestic", "Brand": "Qwen", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/qwen-color.png"},
    {"Model": "Doubao 2.0", "Date": "2025-12-15", "Params_B": 500, "Type": "Domestic", "Brand": "Doubao", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/doubao-color.png"},
    {"Model": "Claude 5", "Date": "2026-03-15", "Params_B": 1200, "Type": "International", "Brand": "Anthropic", "Logo_URL": "https://dl.svgcdn.com/svg/logos/anthropic-icon.svg"},
    {"Model": "GPT-5.3", "Date": "2026-04-15", "Params_B": 1500, "Type": "International", "Brand": "OpenAI", "Logo_URL": "https://upload.wikimedia.org/wikipedia/commons/4/4d/OpenAI_Logo.svg"},
    {"Model": "GLM-6 Pro", "Date": "2026-05-15", "Params_B": 1000, "Type": "Domestic", "Brand": "GLM", "Logo_URL": "https://unpkg.com/@lobehub/icons-static-png@latest/light/zhipu-color.png"}
]

excel_path = "model_data.xlsx"
df = pd.DataFrame(data)
df.to_excel(excel_path, index=False)
print(f"✅ 数据已保存至 {excel_path}")

# ---------------- 2. 自动下载 Logo 到本地 ----------------
logo_dir = "logos"
os.makedirs(logo_dir, exist_ok=True)
df = pd.read_excel(excel_path)
df['Date'] = pd.to_datetime(df['Date'])

local_logo_paths = []
print("开始处理 Logos...")
for index, row in df.iterrows():
    color = '#2E5A88' if row['Type'] == 'International' else '#D8383A'
    path = download_or_generate_logo(row['Logo_URL'], row['Brand'], logo_dir, color)
    local_logo_paths.append(path)
    if path:
        print(f"  ✅ {row['Model']} ({row['Brand']}) Logo 已就绪")

df['Local_Logo'] = local_logo_paths

# ---------------- 3. 开始绘制图表 ----------------
if platform.system() == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Heiti TC', 'SimHei']
else:
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(14, 8))

ax.set_yscale('log')
ax.set_yticks([5, 10, 50, 100, 500, 1000, 2000])
ax.get_yaxis().set_major_formatter(plt.ScalarFormatter())

# 趋势线
trend_dates = pd.to_datetime(["2024-08-01", "2026-04-15"])
trend_params = [12, 1500]
ax.plot(trend_dates, trend_params, color='#00B050', linestyle='-', linewidth=2, label="增长趋势", zorder=1)

# 尝试加载自定义偏移配置
OFFSETS_PATH = "logo_offsets.json"
saved_offsets = {}
if os.path.exists(OFFSETS_PATH):
    with open(OFFSETS_PATH, 'r', encoding='utf-8') as f:
        saved_offsets = json.load(f)
    print(f"📂 已加载自定义偏移配置: {OFFSETS_PATH} ({len(saved_offsets)} 条)")
else:
    print(f"💡 提示: 运行 python editor.py 可交互式调整 Logo 与标签位置")

# 默认 Logo 偏移（offset points）
logo_offsets = {
    "InternVL 3.0": (20, 35),
    "InternVL 3.5": (-20, -30),
    "Kimi K2.5": (-28, 22),
    "Gemini 3.1 Pro": (28, 22),
    "GLM-5": (28, 22),
    "Qwen3.5": (-25, 19),
    "Doubao 2.0": (30, 18),
    "Claude 5": (-38, 28),
    "GPT-5.3": (22, 28),
    "GLM-6 Pro": (-5, 22),
}

# 统一的显示高度（像素），所有 Logo 按此高度动态 zoom
display_target_h = 60

for index, row in df.iterrows():
    color = '#2E5A88' if row['Type'] == 'International' else '#D8383A'
    x = mdates.date2num(row['Date'])
    y = row['Params_B']

    ax.scatter(x, y, color=color, s=30, zorder=5)

    model = row['Model']
    cfg = saved_offsets.get(model, {})
    default_logo_xy = logo_offsets.get(model, (0, 40))
    logo_xy = tuple(cfg.get('logo', default_logo_xy))

    if row['Local_Logo'] and os.path.exists(row['Local_Logo']):
        try:
            img = plt.imread(row['Local_Logo'])
            if img.ndim == 3:
                img_h, img_w = img.shape[:2]
            else:
                img_h, img_w = img.shape

            # 动态 zoom：让所有 Logo 显示高度统一为 display_target_h（像素）
            zoom = display_target_h / img_h
            imagebox = OffsetImage(img, zoom=zoom)

            ab = AnnotationBbox(imagebox, (x, y),
                                xybox=logo_xy,
                                boxcoords="offset points",
                                pad=0.3,
                                frameon=True,
                                bboxprops=dict(edgecolor=color, facecolor='white', linewidth=1.5),
                                zorder=8)
            ax.add_artist(ab)

            # 标签紧贴框底
            pt_to_px = fig.dpi / 72.0
            box_half_h_pt = display_target_h / 2 + 3   # 图片半高 + pad(3pt)
            label_margin_pt = 2

            if 'label' in cfg:
                label_xy = tuple(cfg['label'])
            else:
                label_xy = (logo_xy[0], logo_xy[1] - box_half_h_pt - label_margin_pt)

            ax.annotate(f"{row['Model']} ({row['Params_B']}B)",
                        xy=(x, y),
                        xytext=label_xy,
                        textcoords='offset points',
                        color=color,
                        fontsize=8,
                        ha='center',
                        va='top',
                        zorder=9)

            # 连线：终点在框底部外边缘，zorder=10 压在框上
            display = ax.transData.transform((x, y))
            offset_px = (logo_xy[0] * pt_to_px, logo_xy[1] * pt_to_px)
            center_x = display[0] + offset_px[0]
            center_y = display[1] + offset_px[1]
            box_half_h_px = box_half_h_pt * pt_to_px
            bottom_x = center_x
            bottom_y = center_y - box_half_h_px
            logo_x, logo_y = ax.transData.inverted().transform((bottom_x, bottom_y))
            ax.plot([x, logo_x], [y, logo_y], color=color, lw=0.8, zorder=10)

        except Exception:
            pass

ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%y年%m月'))
plt.xticks(rotation=0)

ax.set_ylabel("模型参数数量规模 (B)", fontsize=12)
ax.set_xlabel("发布时间线", fontsize=12)
ax.set_xlim(pd.to_datetime("2024-04-01"), pd.to_datetime("2026-07-01"))
ax.set_ylim(4, 3000)

import matplotlib.patches as mpatches
intl_patch = mpatches.Patch(color='white', label='国际模型', ec='#2E5A88', lw=2)
dom_patch = mpatches.Patch(color='white', label='国内模型', ec='#D8383A', lw=2)
trend_line = plt.Line2D([0], [0], color='#00B050', lw=2, label='增长趋势')
ax.legend(handles=[intl_patch, dom_patch, trend_line],
          loc='center right', title="图例", frameon=True,
          edgecolor='gray', facecolor='white')

plt.tight_layout()
plt.subplots_adjust(bottom=0.08)
plt.savefig("model_trend_chart.png", dpi=300, bbox_inches='tight')
print("✅ 图表已生成并保存为 model_trend_chart.png")
