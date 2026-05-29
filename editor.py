"""
交互式 Logo 位置编辑器 (PyQt5 版)
=================================
用法: python3 editor.py

核心设计：
- 保留原始 Logo 文件，绘图时动态 zoom 统一显示高度
- 标签紧贴 AnnotationBbox 底部外边缘
- 连线终点在框底外边缘，zorder=8 压在框上
- 所有鼠标交互统一使用像素坐标
"""

import json
import os
import sys

import matplotlib
matplotlib.use('Qt5Agg')

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import pandas as pd

CONFIG_PATH = "logo_offsets.json"
EXCEL_PATH = "model_data.xlsx"
LOGO_DIR = "logos"

# 统一的显示高度（像素），与 ref.py 保持一致
display_target_h = 60

# 默认 Logo 偏移（offset points）
DEFAULT_LOGO_OFFSETS = {
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


def _pt2px(pt, dpi):
    return pt * dpi / 72.0


def _px2pt(px, dpi):
    return px * 72.0 / dpi


class DraggableLogo:
    """可拖动的 Logo + 标签 + 连线组合。标签紧贴框底，连线压在框上。"""

    def __init__(self, ax, row, logo_path, color, saved_cfg):
        self.ax = ax
        self.model = row['Model']
        self.brand = row['Brand']
        self.x = mdates.date2num(row['Date'])
        self.y = row['Params_B']
        self.color = color
        self.logo_path = logo_path
        self.dpi = ax.figure.dpi
        self.pt_to_px = self.dpi / 72.0

        # 读取配置
        cfg = saved_cfg.get(self.model, {})
        default_xy = DEFAULT_LOGO_OFFSETS.get(self.model, (0, 40))
        self.logo_offset = list(cfg.get('logo', default_xy))

        # ---- 加载图片并计算动态 zoom ----
        img = plt.imread(logo_path)
        if img.ndim == 3:
            img_h, img_w = img.shape[:2]
        else:
            img_h, img_w = img.shape

        # 动态 zoom：统一显示高度为 display_target_h 像素
        self.zoom = display_target_h / img_h
        self.img_h_px = display_target_h * self.pt_to_px
        self.img_w_px = self.img_h_px * (img_w / img_h)
        self.pad_px = 3 * self.pt_to_px          # AnnotationBbox pad=0.3, 默认 fontsize=10pt → 3pt

        # 框半高（offset points）= 图片半高 + pad = target_h/2 + 3pt
        self.box_half_h_pt = display_target_h / 2 + 3
        self.label_margin_pt = 2

        # 标签偏移：紧贴框底；保存相对偏移以便拖动时同步
        if 'label' in cfg:
            self.label_offset = list(cfg['label'])
            self.label_rel_y = self.label_offset[1] - self.logo_offset[1]
        else:
            self.label_rel_y = -self.box_half_h_pt - self.label_margin_pt
            self.label_offset = [
                self.logo_offset[0],
                self.logo_offset[1] + self.label_rel_y
            ]

        # ---- 创建图形元素 ----
        self.scatter = ax.scatter(self.x, self.y, color=color, s=30, zorder=5)

        imagebox = OffsetImage(img, zoom=self.zoom)
        self.ab = AnnotationBbox(
            imagebox, (self.x, self.y),
            xybox=tuple(self.logo_offset),
            boxcoords="offset points",
            pad=0.3,
            frameon=True,
            bboxprops=dict(edgecolor=color, facecolor='white', linewidth=1.5),
            zorder=8
        )
        ax.add_artist(self.ab)

        self.label = ax.annotate(
            f"{self.model} ({self.y}B)",
            xy=(self.x, self.y),
            xytext=tuple(self.label_offset),
            textcoords='offset points',
            color=color,
            fontsize=8,
            ha='center',
            va='top',
            zorder=9
        )

        self._update_line()
        self.press = None
        self._connect()

    # ------------------------------------------------------------------
    # 坐标辅助
    # ------------------------------------------------------------------
    def _logo_center_px(self):
        display = self.ax.transData.transform((self.x, self.y))
        return (display[0] + _pt2px(self.logo_offset[0], self.dpi),
                display[1] + _pt2px(self.logo_offset[1], self.dpi))

    def _logo_bbox_px(self):
        cx, cy = self._logo_center_px()
        hw = self.img_w_px / 2 + self.pad_px
        hh = self.img_h_px / 2 + self.pad_px
        return cx - hw, cy - hh, cx + hw, cy + hh

    def _update_line(self):
        """使用 logo_offset 手动计算框底中心，避免 AnnotationBbox 位置未同步。"""
        if hasattr(self, 'line') and self.line is not None:
            self.line.remove()

        pt_to_px = self.dpi / 72.0
        display = self.ax.transData.transform((self.x, self.y))
        offset_px = (self.logo_offset[0] * pt_to_px, self.logo_offset[1] * pt_to_px)
        center_x = display[0] + offset_px[0]
        center_y = display[1] + offset_px[1]
        box_half_h_px = self.box_half_h_pt * pt_to_px
        bottom_x = center_x
        bottom_y = center_y - box_half_h_px
        logo_x, logo_y = self.ax.transData.inverted().transform((bottom_x, bottom_y))

        self.line, = self.ax.plot(
            [self.x, logo_x], [self.y, logo_y],
            color=self.color, lw=0.8, zorder=10
        )

    def _connect(self):
        canvas = self.ax.figure.canvas
        self.cid_press = canvas.mpl_connect('button_press_event', self.on_press)
        self.cid_release = canvas.mpl_connect('button_release_event', self.on_release)
        self.cid_motion = canvas.mpl_connect('motion_notify_event', self.on_motion)

    # ------------------------------------------------------------------
    # 鼠标事件
    # ------------------------------------------------------------------
    def on_press(self, event):
        if event.inaxes != self.ax or event.button != 1:
            return
        # 强制同步 AnnotationBbox 位置，确保 contains 判断准确
        try:
            renderer = self.ax.figure.canvas.get_renderer()
            self.ab.update_positions(renderer)
        except Exception:
            pass
        inside, _ = self.ab.contains(event)
        if not inside:
            left, bottom, right, top = self._logo_bbox_px()
            inside = left <= event.x <= right and bottom <= event.y <= top
        if inside:
            self.press = (event.x, event.y,
                          self.logo_offset[0], self.logo_offset[1])
            print(f"  🖱 开始拖动 {self.model} ...")

    def on_motion(self, event):
        if self.press is None or event.inaxes != self.ax:
            return
        x0, y0, ox, oy = self.press
        dx_px = event.x - x0
        dy_px = event.y - y0

        self.logo_offset[0] = ox + _px2pt(dx_px, self.dpi)
        self.logo_offset[1] = oy + _px2pt(dy_px, self.dpi)

        # 标签保持相对 logo 的固定偏移同步跟随
        self.label_offset[0] = self.logo_offset[0]
        self.label_offset[1] = self.logo_offset[1] + self.label_rel_y

        self.ab.xybox = (self.logo_offset[0], self.logo_offset[1])
        self.label.xytext = (self.label_offset[0], self.label_offset[1])

        # 强制更新 AnnotationBbox 内部位置
        try:
            renderer = self.ax.figure.canvas.get_renderer()
            self.ab.update_positions(renderer)
        except Exception:
            pass

        self._update_line()
        self.ax.figure.canvas.draw_idle()

    def on_release(self, event):
        if self.press is None:
            return
        self.press = None
        self._save_config()
        print(f"  ✅ {self.model} 已保存: logo_offset={self.logo_offset}")

    def _save_config(self):
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        cfg[self.model] = {
            'logo': self.logo_offset,
            'label': self.label_offset
        }
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)


def build_chart():
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Heiti TC', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.set_yscale('log')
    ax.set_yticks([5, 10, 50, 100, 500, 1000, 2000])
    ax.get_yaxis().set_major_formatter(plt.ScalarFormatter())

    trend_dates = pd.to_datetime(["2024-08-01", "2026-04-15"])
    trend_params = [12, 1500]
    ax.plot(trend_dates, trend_params, color='#00B050',
            linestyle='-', linewidth=2, label="增长趋势", zorder=1)

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

    return fig, ax


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logo 位置编辑器")
        self.setGeometry(80, 60, 1500, 950)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        info = QLabel("🖱 左键按住 Logo 白色边框或内部拖动 → 标签紧贴框底联动 → 松手自动保存")
        info_font = QFont()
        info_font.setPointSize(11)
        info.setFont(info_font)
        info.setStyleSheet("color: #444; padding: 4px;")
        layout.addWidget(info)

        self.fig, self.ax = build_chart()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setFocusPolicy(Qt.ClickFocus)
        self.canvas.setFocus()
        layout.addWidget(self.canvas)

        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.reset_btn = QPushButton("🔄 重置所有位置")
        self.reset_btn.setToolTip("删除自定义配置，恢复默认布局")
        self.reset_btn.setStyleSheet("padding: 6px 16px; font-size: 12px;")
        self.reset_btn.clicked.connect(self.reset_all)
        btn_layout.addWidget(self.reset_btn)

        self.save_btn = QPushButton("💾 保存并退出")
        self.save_btn.setToolTip("保存当前配置并关闭编辑器")
        self.save_btn.setStyleSheet("padding: 6px 16px; font-size: 12px;")
        self.save_btn.clicked.connect(self.save_and_quit)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

        self.items = []
        self._init_items()

    def _init_items(self):
        if not os.path.exists(EXCEL_PATH):
            QMessageBox.critical(self, "错误", f"未找到 {EXCEL_PATH}\n请先运行 python3 ref.py 生成数据文件")
            return

        df = pd.read_excel(EXCEL_PATH)
        df['Date'] = pd.to_datetime(df['Date'])

        saved_cfg = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    saved_cfg = json.load(f)
                print(f"📂 已加载配置: {CONFIG_PATH} ({len(saved_cfg)} 条记录)")
            except Exception as e:
                print(f"⚠️ 读取配置失败: {e}")

        for _, row in df.iterrows():
            color = '#2E5A88' if row['Type'] == 'International' else '#D8383A'
            logo_path = os.path.join(LOGO_DIR, row['Brand'].replace(' ', '_'), "logo.png")

            if not os.path.exists(logo_path):
                print(f"  ⚠️ 跳过 {row['Model']}: 未找到 {logo_path}")
                continue

            item = DraggableLogo(self.ax, row, logo_path, color, saved_cfg)
            self.items.append(item)

        self.canvas.draw_idle()

    def reset_all(self):
        reply = QMessageBox.question(
            self, "确认重置",
            "确定要删除所有自定义位置配置，恢复默认布局吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if os.path.exists(CONFIG_PATH):
                os.remove(CONFIG_PATH)
                print("🗑 已删除自定义配置")

            for item in self.items:
                canvas = item.ax.figure.canvas
                canvas.mpl_disconnect(item.cid_press)
                canvas.mpl_disconnect(item.cid_release)
                canvas.mpl_disconnect(item.cid_motion)
                item.scatter.remove()
                item.ab.remove()
                item.label.remove()
                item.line.remove()
            self.items.clear()

            self.ax.clear()
            self._setup_ax(self.ax)
            self._init_items()
            self.canvas.draw_idle()

    def _setup_ax(self, ax):
        ax.set_yscale('log')
        ax.set_yticks([5, 10, 50, 100, 500, 1000, 2000])
        ax.get_yaxis().set_major_formatter(plt.ScalarFormatter())

        import matplotlib.patches as mpatches
        trend_dates = pd.to_datetime(["2024-08-01", "2026-04-15"])
        trend_params = [12, 1500]
        ax.plot(trend_dates, trend_params, color='#00B050',
                linestyle='-', linewidth=2, label="增长趋势", zorder=1)

        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%y年%m月'))
        ax.set_ylabel("模型参数数量规模 (B)", fontsize=12)
        ax.set_xlabel("发布时间线", fontsize=12)
        ax.set_xlim(pd.to_datetime("2024-04-01"), pd.to_datetime("2026-07-01"))
        ax.set_ylim(4, 3000)

        intl_patch = mpatches.Patch(color='white', label='国际模型', ec='#2E5A88', lw=2)
        dom_patch = mpatches.Patch(color='white', label='国内模型', ec='#D8383A', lw=2)
        trend_line = plt.Line2D([0], [0], color='#00B050', lw=2, label='增长趋势')
        ax.legend(handles=[intl_patch, dom_patch, trend_line],
                  loc='center right', title="图例", frameon=True,
                  edgecolor='gray', facecolor='white')

    def save_and_quit(self):
        print(f"\n✅ 所有偏移已保存到 {CONFIG_PATH}")
        print("   现在可以运行: python3 ref.py")
        self.close()


def main():
    print("=" * 60)
    print("交互式 Logo 位置编辑器 (PyQt5)")
    print("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("Logo Editor")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
