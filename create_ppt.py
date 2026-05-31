#!/usr/bin/env python3
"""
无人机城市交通态势感知系统 — CTO技术汇报PPT生成器
Deep navy theme with cyan/teal accents
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import math

# ──────────────────── Theme Colors ────────────────────
BG_DARK    = RGBColor(0x0B, 0x14, 0x26)   # Deep navy
BG_CARD    = RGBColor(0x11, 0x1E, 0x36)   # Card background
BG_CARD2   = RGBColor(0x16, 0x25, 0x40)   # Slightly lighter card
ACCENT     = RGBColor(0x00, 0xD4, 0xAA)   # Cyan/teal
ACCENT2    = RGBColor(0x38, 0x8B, 0xFD)   # Blue
ACCENT3    = RGBColor(0xFF, 0x6B, 0x35)   # Orange
ACCENT4    = RGBColor(0xA8, 0x55, 0xF7)   # Purple
ACCENT4    = RGBColor(0xA8, 0x55, 0xF7)   # Purple
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xB0, 0xBC, 0xD0)
MID_GRAY   = RGBColor(0x7A, 0x8A, 0xA0)
DARK_LINE   = RGBColor(0x20, 0x30, 0x50)
RED         = RGBColor(0xEF, 0x44, 0x44)
YELLOW      = RGBColor(0xFB, 0xBF, 0x24)
GREEN       = RGBColor(0x22, 0xC5, 0x5E)

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)

W = prs.slide_width
H = prs.slide_height

# ──────────────────── Helper Functions ────────────────────
def set_slide_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_shape(slide, left, top, width, height, fill_color=None, border_color=None, border_width=Pt(0), shape_type=MSO_SHAPE.ROUNDED_RECTANGLE):
    shape = slide.shapes.add_shape(shape_type, left, top, width, height)
    shape.line.width = border_width
    if border_color:
        shape.line.color.rgb = border_color
    else:
        shape.line.fill.background()
    if fill_color:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
    else:
        shape.fill.background()
    return shape

def add_rect(slide, left, top, width, height, fill_color=None, border_color=None, border_width=Pt(0)):
    return add_shape(slide, left, top, width, height, fill_color, border_color, border_width, MSO_SHAPE.RECTANGLE)

def add_text_box(slide, left, top, width, height, text, font_size=14, color=WHITE, bold=False, alignment=PP_ALIGN.LEFT, font_name="Microsoft YaHei"):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return txBox

def add_multiline_text(slide, left, top, width, height, lines, font_size=13, color=WHITE, line_spacing=1.2, font_name="Microsoft YaHei"):
    """lines: list of (text, color, bold, size_override)"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, item in enumerate(lines):
        if isinstance(item, str):
            text, c, b, s = item, color, False, font_size
        elif len(item) == 2:
            text, c = item; b, s = False, font_size
        elif len(item) == 3:
            text, c, b = item; s = font_size
        else:
            text, c, b, s = item
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = text
        p.font.size = Pt(s)
        p.font.color.rgb = c
        p.font.bold = b
        p.font.name = font_name
        p.space_after = Pt(s * 0.3)
    return txBox

def add_card(slide, left, top, width, height, title, items, accent_color=ACCENT, icon_text=""):
    """Add a card with title bar and bullet items"""
    # Card background
    card = add_shape(slide, left, top, width, height, fill_color=BG_CARD, border_color=DARK_LINE, border_width=Pt(1))
    # Accent bar at top
    add_rect(slide, left + Inches(0.15), top + Inches(0.1), Inches(0.4), Pt(4), fill_color=accent_color)
    # Title
    title_text = f"  {title}" if not icon_text else f" {icon_text}  {title}"
    add_text_box(slide, left + Inches(0.5), top + Inches(0.05), width - Inches(0.6), Inches(0.45), title, font_size=15, color=WHITE, bold=True)
    # Items
    lines = []
    for item in items:
        if isinstance(item, tuple):
            lines.append(item)
        else:
            lines.append((f"• {item}", LIGHT_GRAY, False, 12))
    add_multiline_text(slide, left + Inches(0.25), top + Inches(0.55), width - Inches(0.5), height - Inches(0.65), lines, font_size=12)

def add_flow_box(slide, left, top, width, height, text, fill_color=BG_CARD2, text_color=WHITE, font_size=11, border_color=None):
    """Add a flow diagram box"""
    bc = border_color or ACCENT
    shape = add_shape(slide, left, top, width, height, fill_color=fill_color, border_color=bc, border_width=Pt(1.5))
    shape.text_frame.word_wrap = True
    p = shape.text_frame.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = text_color
    p.font.bold = True
    p.font.name = "Microsoft YaHei"
    p.alignment = PP_ALIGN.CENTER
    shape.text_frame.paragraphs[0].space_before = Pt(0)
    return shape

def add_arrow(slide, left, top, width, height, color=ACCENT):
    """Add a right-pointing arrow"""
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def add_down_arrow(slide, left, top, width, height, color=ACCENT):
    shape = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def add_page_number(slide, num, total):
    add_text_box(slide, Inches(12.3), Inches(7.1), Inches(0.8), Inches(0.3), f"{num}/{total}", font_size=10, color=MID_GRAY, alignment=PP_ALIGN.RIGHT)

def add_section_header(slide, title, subtitle=""):
    """Add consistent section header"""
    # Subtle gradient bar at top
    add_rect(slide, Inches(0), Inches(0), W, Pt(4), fill_color=ACCENT)
    add_text_box(slide, Inches(0.8), Inches(0.35), Inches(11), Inches(0.7), title, font_size=28, color=WHITE, bold=True)
    if subtitle:
        add_text_box(slide, Inches(0.8), Inches(1.0), Inches(11), Inches(0.4), subtitle, font_size=14, color=LIGHT_GRAY)

def add_kpi_box(slide, left, top, width, height, value, label, color=ACCENT):
    add_shape(slide, left, top, width, height, fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, left, top + Inches(0.15), width, Inches(0.5), value, font_size=26, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, left, top + Inches(0.6), width, Inches(0.3), label, font_size=11, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)

TOTAL_SLIDES = 20

# ════════════════════════════════════════════════════════
# SLIDE 1: Cover
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
set_slide_bg(slide, BG_DARK)

# Large decorative circle (subtle)
shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(9), Inches(-1), Inches(6), Inches(6))
shape.fill.solid()
shape.fill.fore_color.rgb = RGBColor(0x0F, 0x1C, 0x33)
shape.line.fill.background()

shape2 = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(-2), Inches(4.5), Inches(5), Inches(5))
shape2.fill.solid()
shape2.fill.fore_color.rgb = RGBColor(0x0D, 0x18, 0x2E)
shape2.line.fill.background()

# Accent line
add_rect(slide, Inches(1.2), Inches(2.5), Inches(0.8), Pt(5), fill_color=ACCENT)

# Title
add_text_box(slide, Inches(1.2), Inches(2.8), Inches(10), Inches(1.2),
    "无人机城市交通态势感知系统", font_size=42, color=WHITE, bold=True)
add_text_box(slide, Inches(1.2), Inches(4.0), Inches(10), Inches(0.6),
    "UAV-Based Urban Traffic Situation Awareness System", font_size=18, color=ACCENT)
add_text_box(slide, Inches(1.2), Inches(4.8), Inches(10), Inches(0.5),
    "技术方案汇报  |  CTO技术评审", font_size=16, color=LIGHT_GRAY)

# Bottom info bar
add_rect(slide, Inches(0), Inches(6.7), W, Inches(0.8), fill_color=RGBColor(0x08, 0x10, 0x1E))
add_text_box(slide, Inches(1.2), Inches(6.85), Inches(5), Inches(0.4),
    "YOLO11 + ByteTrack  |  Kafka + InfluxDB  |  双模式作业", font_size=13, color=MID_GRAY)
add_text_box(slide, Inches(9), Inches(6.85), Inches(3.5), Inches(0.4),
    "2026.05", font_size=13, color=MID_GRAY, alignment=PP_ALIGN.RIGHT)

# ════════════════════════════════════════════════════════
# SLIDE 2: 行业痛点与现有方案局限
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "行业痛点与现有方案局限性", "Why UAV? — 传统交通感知方案的三大瓶颈")
add_page_number(slide, 2, TOTAL_SLIDES)

# Three pain point cards
pain_data = [
    ("固定摄像头方案", ACCENT3, [
        ("覆盖盲区多", RED, True, 13),
        ("• 单摄像头覆盖角度有限（≤120°）", LIGHT_GRAY, False, 12),
        ("• 路口改建后需重新布线安装", LIGHT_GRAY, False, 12),
        ("• 透视畸变导致远端检测精度下降>15%", LIGHT_GRAY, False, 12),
        ("• 无法灵活调度，硬件部署周期长", LIGHT_GRAY, False, 12),
    ]),
    ("地磁/线圈检测方案", ACCENT2, [
        ("维护成本高", RED, True, 13),
        ("• 需破路施工，影响交通通行", LIGHT_GRAY, False, 12),
        ("• 仅能检测通过/存在，无轨迹信息", LIGHT_GRAY, False, 12),
        ("• 传感器老化后精度衰减严重", LIGHT_GRAY, False, 12),
        ("• 无法识别车辆类型与行驶方向", LIGHT_GRAY, False, 12),
    ]),
    ("浮动车/GPS方案", ACCENT4, [
        ("数据粒度粗", RED, True, 13),
        ("• 依赖营运车辆GPS，覆盖率<15%", LIGHT_GRAY, False, 12),
        ("• 采样间隔5-30s，无法检测瞬时事件", LIGHT_GRAY, False, 12),
        ("• 无车道级精度，无法区分转向", LIGHT_GRAY, False, 12),
        ("• 行人/非机动车完全不可见", LIGHT_GRAY, False, 12),
    ]),
]

for i, (title, accent, items) in enumerate(pain_data):
    x = Inches(0.8 + i * 4.1)
    add_card(slide, x, Inches(1.7), Inches(3.7), Inches(3.6), title, items, accent)

# Bottom insight box
add_shape(slide, Inches(0.8), Inches(5.6), Inches(11.7), Inches(1.1), fill_color=BG_CARD, border_color=ACCENT, border_width=Pt(1.5))
add_multiline_text(slide, Inches(1.2), Inches(5.75), Inches(11), Inches(0.8), [
    ("核心矛盾：交管部门需要「全路段、全时段、全要素」的交通态势数据", WHITE, True, 14),
    ("而传统方案在覆盖灵活性、检测精度和部署成本之间存在不可调和的三角矛盾", LIGHT_GRAY, False, 12),
])

# ════════════════════════════════════════════════════════
# SLIDE 3: 方案定位与核心价值
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "无人机交通态势感知 — 核心价值主张", "一种机动、精确、全要素的新型交通感知基础设施")
add_page_number(slide, 3, TOTAL_SLIDES)

# Four value proposition cards
values = [
    ("🛩  机动覆盖", "5分钟抵达任意路口\n固定摄像头盲区即时接管\n无需破路施工布线", ACCENT),
    ("📊  全要素感知", "流量/车速/排队/车头时距\n转向分类/轨迹还原\n机非冲突事件检测", ACCENT2),
    ("⚡  秒级告警", "TTC<1s 触发P1告警\n异常停车/逆行识别\nWebhook推送<30s", ACCENT3),
    ("🔄  全天候运行", "热成像+可见光双通道\n夜间/大雾场景覆盖\nRTK厘米级定位", GREEN),
]
for i, (title, desc, color) in enumerate(values):
    x = Inches(0.6 + i * 3.15)
    card = add_shape(slide, x, Inches(1.7), Inches(2.9), Inches(2.8), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.2), Inches(1.85), Inches(2.5), Inches(0.5), title, font_size=16, color=color, bold=True)
    for j, line in enumerate(desc.split('\n')):
        add_text_box(slide, x + Inches(0.2), Inches(2.45 + j * 0.4), Inches(2.5), Inches(0.35), f"• {line}", font_size=11, color=LIGHT_GRAY)

# Key metrics bar
kpi_data = [("35+", "FPS处理帧率"), ("±2m", "GPS定位精度"), ("43路", "REST API端点"), ("<1s", "端到端延迟")]
for i, (val, label) in enumerate(kpi_data):
    add_kpi_box(slide, Inches(0.8 + i * 3.1), Inches(5.0), Inches(2.7), Inches(1.0), val, label)

# Bottom comparison
add_shape(slide, Inches(0.8), Inches(6.2), Inches(11.7), Inches(0.8), fill_color=BG_CARD2, border_color=DARK_LINE, border_width=Pt(1))
add_text_box(slide, Inches(1.2), Inches(6.35), Inches(11), Inches(0.5),
    "80%代码复用成熟开源项目 TrafficAnalyzer  →  新增风险集中在3个核心节点（IPM/EIS/VLM），工程可控",
    font_size=12, color=LIGHT_GRAY)

# ════════════════════════════════════════════════════════
# SLIDE 4: 双模式作业 — 巡飞 vs 悬停
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "双模式作业架构", "巡飞模式（路段级）×  悬停模式（交叉口级）")
add_page_number(slide, 4, TOTAL_SLIDES)

# Left card: Patrol mode
add_shape(slide, Inches(0.6), Inches(1.6), Inches(5.8), Inches(5.2), fill_color=BG_CARD, border_color=ACCENT, border_width=Pt(2))
add_text_box(slide, Inches(0.9), Inches(1.75), Inches(5), Inches(0.5), "巡飞模式 — 路段级覆盖", font_size=20, color=ACCENT, bold=True)

patrol_items = [
    ("作业参数", WHITE, True, 13),
    ("• 飞行高度：80-160m AGL  • 飞行速度：8-12 m/s", LIGHT_GRAY, False, 12),
    ("• 覆盖范围：2-5km路段  • 单架次时长：15-25min", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 8),
    ("检测能力", WHITE, True, 13),
    ("• 路段交通流量统计（辆/分钟）", LIGHT_GRAY, False, 12),
    ("• 区间平均车速估计（km/h，运动补偿后）", LIGHT_GRAY, False, 12),
    ("• 转向车流分类（左转/直行/右转/掉头）", LIGHT_GRAY, False, 12),
    ("• 机非冲突事件检测（TTC模型）", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 8),
    ("技术特点", WHITE, True, 13),
    ("• GPS锚定世界坐标系 + 帧间运动补偿", ACCENT, False, 12),
    ("• 无需预标注，零配置即可输出方向流量", ACCENT, False, 12),
    ("• 无人机速度>5m/s时方向分类降级为像素空间", MID_GRAY, False, 11),
]
add_multiline_text(slide, Inches(0.9), Inches(2.35), Inches(5.2), Inches(4.2), patrol_items)

# Right card: Hover mode
add_shape(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(5.2), fill_color=BG_CARD, border_color=ACCENT2, border_width=Pt(2))
add_text_box(slide, Inches(7.2), Inches(1.75), Inches(5), Inches(0.5), "悬停模式 — 交叉口精细化", font_size=20, color=ACCENT2, bold=True)

hover_items = [
    ("作业参数", WHITE, True, 13),
    ("• 悬停高度：50-120m AGL  • 悬停精度：±0.5m", LIGHT_GRAY, False, 12),
    ("• 覆盖范围：单路口全域  • 单架次时长：20-40min", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 8),
    ("检测能力", WHITE, True, 13),
    ("• 车道级流量/车速/排队长度/车头时距", LIGHT_GRAY, False, 12),
    ("• 精确转向轨迹还原（世界坐标米级）", LIGHT_GRAY, False, 12),
    ("• 进出口道路车辆归属判定", LIGHT_GRAY, False, 12),
    ("• 冲突事件精确定位（距离+TTC+坐标）", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 8),
    ("技术特点", WHITE, True, 13),
    ("• 遥测驱动自动单应性标定（Nadir/Oblique双模式）", ACCENT2, False, 12),
    ("• 车道多边形预标注，数据驱动自动输出", ACCENT2, False, 12),
    ("• 云台-90°正下方锁定，GSD恒定", ACCENT2, False, 12),
]
add_multiline_text(slide, Inches(7.2), Inches(2.35), Inches(5.2), Inches(4.2), hover_items)

# ════════════════════════════════════════════════════════
# SLIDE 5: 系统总体架构
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "系统总体架构", "四层架构：飞行平台 → 边缘计算 → 数据管道 → 业务平台")
add_page_number(slide, 5, TOTAL_SLIDES)

# Layer 1: UAV Platform
add_rect(slide, Inches(0.6), Inches(1.6), Inches(12.1), Inches(1.1), fill_color=RGBColor(0x0A, 0x2E, 0x1A), border_color=GREEN, border_width=Pt(1.5))
add_text_box(slide, Inches(0.9), Inches(1.65), Inches(2), Inches(0.35), "飞行平台层", font_size=13, color=GREEN, bold=True)
boxes_l1 = [("DJI M300 RTK", Inches(0.9)), ("RTSP图传", Inches(3.2)), ("MQTT遥测", Inches(5.3)), ("GPS/RTK定位", Inches(7.4)), ("三轴云台", Inches(9.7)), ("SRT字幕", Inches(11.2))]
for txt, x in boxes_l1:
    add_flow_box(slide, x, Inches(2.1), Inches(1.8), Inches(0.45), txt, fill_color=BG_CARD2, text_color=GREEN, font_size=10, border_color=GREEN)

# Arrow down
add_down_arrow(slide, Inches(6.2), Inches(2.75), Inches(0.6), Inches(0.35), ACCENT)

# Layer 2: Edge Computing
add_rect(slide, Inches(0.6), Inches(3.2), Inches(12.1), Inches(1.1), fill_color=RGBColor(0x1A, 0x1A, 0x2E), border_color=ACCENT2, border_width=Pt(1.5))
add_text_box(slide, Inches(0.9), Inches(3.25), Inches(2), Inches(0.35), "边缘计算层", font_size=13, color=ACCENT2, bold=True)
boxes_l2 = [("EIS稳定", Inches(0.9)), ("IPM标定", Inches(2.8)), ("YOLO11检测", Inches(4.7)), ("ByteTrack", Inches(6.8)), ("运动补偿", Inches(8.7)), ("分析节点链", Inches(10.6))]
for txt, x in boxes_l2:
    add_flow_box(slide, x, Inches(3.7), Inches(1.6), Inches(0.45), txt, fill_color=BG_CARD2, text_color=ACCENT2, font_size=10, border_color=ACCENT2)

# Arrow down
add_down_arrow(slide, Inches(6.2), Inches(4.35), Inches(0.6), Inches(0.35), ACCENT)

# Layer 3: Data Pipeline
add_rect(slide, Inches(0.6), Inches(4.8), Inches(12.1), Inches(1.1), fill_color=RGBColor(0x2E, 0x1A, 0x0A), border_color=ACCENT3, border_width=Pt(1.5))
add_text_box(slide, Inches(0.9), Inches(4.85), Inches(2), Inches(0.35), "数据管道层", font_size=13, color=ACCENT3, bold=True)
boxes_l3 = [("Kafka 3-Topic", Inches(0.9)), ("Telegraf", Inches(3.6)), ("InfluxDB", Inches(5.5)), ("WebSocket", Inches(7.6)), ("AlertEngine", Inches(9.7)), ("PipelineManager", Inches(11.2))]
for txt, x in boxes_l3:
    add_flow_box(slide, x, Inches(5.3), Inches(1.4), Inches(0.45), txt, fill_color=BG_CARD2, text_color=ACCENT3, font_size=10, border_color=ACCENT3)

# Arrow down
add_down_arrow(slide, Inches(6.2), Inches(5.95), Inches(0.6), Inches(0.35), ACCENT)

# Layer 4: Business Platform
add_rect(slide, Inches(0.6), Inches(6.4), Inches(12.1), Inches(0.8), fill_color=RGBColor(0x2E, 0x0A, 0x1A), border_color=ACCENT4, border_width=Pt(1.5))
add_text_box(slide, Inches(0.9), Inches(6.45), Inches(2), Inches(0.35), "业务平台层", font_size=13, color=ACCENT4, bold=True)
boxes_l4 = [("FastAPI 43路API", Inches(3.2)), ("React SPA", Inches(5.8)), ("Grafana大屏", Inches(7.8)), ("GIS一张图", Inches(9.8))]
for txt, x in boxes_l4:
    add_flow_box(slide, x, Inches(6.55), Inches(1.7), Inches(0.4), txt, fill_color=BG_CARD2, text_color=ACCENT4, font_size=10, border_color=ACCENT4)

# ════════════════════════════════════════════════════════
# SLIDE 6: 核心Pipeline — 算法处理链
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "核心Pipeline — 视频分析处理链", "Node-based Architecture: 每帧流经12个功能节点，渐进式数据增强")
add_page_number(slide, 6, TOTAL_SLIDES)

# Pipeline flow - two rows
nodes_row1 = [
    ("VideoReader", "视频采集\n遥测注入", ACCENT),
    ("Detection+Tracking", "YOLO11检测\nByteTrack跟踪", ACCENT2),
    ("Homography", "遥测→H矩阵\nNadir/Oblique", GREEN),
    ("MotionComp", "GPS锚定\n速度补偿", GREEN),
    ("TrackerInfo", "道路分配\n轨迹累积", ACCENT),
    ("SpeedEst", "透视变换\n车速km/h", ACCENT2),
]
nodes_row2 = [
    ("DirectionFlow", "方向分类\n排队检测", ACCENT3),
    ("LaneAnalysis", "车道级统计\n数据驱动", ACCENT3),
    ("Trajectory", "轨迹还原\n转向分类", ACCENT4),
    ("ConflictDet", "TTC检测\n机非冲突", RED),
    ("CalcStats", "统计聚合\n指标计算", ACCENT),
    ("KafkaProd", "多Topic\n消息发布", ACCENT2),
]

for row_idx, nodes in enumerate([nodes_row1, nodes_row2]):
    y = Inches(1.8 + row_idx * 2.6)
    for i, (name, desc, color) in enumerate(nodes):
        x = Inches(0.4 + i * 2.1)
        # Node box
        shape = add_shape(slide, x, y, Inches(1.85), Inches(1.5), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
        add_text_box(slide, x + Inches(0.1), y + Inches(0.1), Inches(1.65), Inches(0.4), name, font_size=12, color=color, bold=True, alignment=PP_ALIGN.CENTER)
        for j, line in enumerate(desc.split('\n')):
            add_text_box(slide, x + Inches(0.1), y + Inches(0.55 + j * 0.35), Inches(1.65), Inches(0.3), line, font_size=10, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)
        # Arrow
        if i < len(nodes) - 1:
            add_arrow(slide, x + Inches(1.88), y + Inches(0.6), Inches(0.22), Inches(0.2), color=DARK_LINE)

# Row connector
add_down_arrow(slide, Inches(12.3), Inches(3.35), Inches(0.3), Inches(0.45), DARK_LINE)

# Bottom note
add_shape(slide, Inches(0.6), Inches(6.3), Inches(12.1), Inches(0.8), fill_color=BG_CARD2, border_color=DARK_LINE, border_width=Pt(1))
add_multiline_text(slide, Inches(1.0), Inches(6.4), Inches(11), Inches(0.6), [
    ("三进程并行架构：Process1(采集+GPU推理) | Process2(CPU计算链+Kafka) | Process3(渲染+IO)", WHITE, True, 12),
    ("队列maxsize=50，进程健康检查：is_alive() + Queue.get(timeout=10)，异常自动退出", LIGHT_GRAY, False, 11),
])

# ════════════════════════════════════════════════════════
# SLIDE 7: 目标检测与跟踪算法
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "目标检测与多目标跟踪", "YOLO11 (自训练UAV模型) + ByteTrack (双阈值关联)")
add_page_number(slide, 7, TOTAL_SLIDES)

# Left: YOLO detection
add_card(slide, Inches(0.6), Inches(1.6), Inches(5.8), Inches(2.5), "YOLO11 目标检测", [
    ("模型：uav_best.pt — 自训练无人机视角模型", WHITE, True, 12),
    ("• 检测类别：COCO 2-9（car/bus/truck/motorcycle等）", LIGHT_GRAY, False, 11),
    ("• 推理分辨率：imgsz=1280（俯视角小目标优化）", LIGHT_GRAY, False, 11),
    ("• 置信度阈值：0.10（低阈值 → 更多候选供二轮关联）", LIGHT_GRAY, False, 11),
    ("• NMS IoU阈值：0.7（允许密集场景重叠框通过）", LIGHT_GRAY, False, 11),
    ("• 推理速度：~15ms/帧 @ GPU（RTX 3060+）", LIGHT_GRAY, False, 11),
], accent_color=ACCENT2)

# Right: ByteTrack
add_card(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(2.5), "ByteTrack 多目标跟踪", [
    ("核心：利用低置信度框进行第二轮关联", WHITE, True, 12),
    ("• 第一轮：高分框(>0.5)与轨迹池IOU匹配(lapjv)", LIGHT_GRAY, False, 11),
    ("• 第二轮：低分框(>0.1)与未匹配轨迹再次关联", LIGHT_GRAY, False, 11),
    ("• 卡尔曼滤波：8维状态空间[cx,cy,ar,h,vx,vy,va,vh]", LIGHT_GRAY, False, 11),
    ("• track_buffer=250帧（容忍无人机抖动目标丢失）", LIGHT_GRAY, False, 11),
    ("• 纯IOU匹配，无外观特征提取，推理更快", LIGHT_GRAY, False, 11),
], accent_color=ACCENT)

# Bottom: Motor/Non-motor classification
add_card(slide, Inches(0.6), Inches(4.4), Inches(5.8), Inches(2.5), "车辆分类策略", [
    ("基于YOLO原始类别ID的Motor/Non-Motor二分法", WHITE, True, 12),
    ("• Motor类：{car(2), bus(5), truck(7), motorcycle(3)}", LIGHT_GRAY, False, 11),
    ("• Non-Motor类：{person(0), bicycle(1)}", LIGHT_GRAY, False, 11),
    ("• ByteTrack内部统一标记为class_id=2（不影响IOU匹配）", LIGHT_GRAY, False, 11),
    ("• 原始YOLO类别保存在tracked_cls_ids供下游使用", LIGHT_GRAY, False, 11),
], accent_color=ACCENT3)

# Bottom: Key innovation
add_card(slide, Inches(6.9), Inches(4.4), Inches(5.8), Inches(2.5), "无人机场景优化", [
    ("针对俯视角的特殊处理", WHITE, True, 12),
    ("• 检测分辨率提升至1280（vs固定摄像头640）", LIGHT_GRAY, False, 11),
    ("• track_buffer从125增至250（容忍抖动丢失）", LIGHT_GRAY, False, 11),
    ("• 置信度阈值从0.10调至0.18（减小俯视角误检）", LIGHT_GRAY, False, 11),
    ("• 三轴云台机械防抖 + EIS软件补偿双层稳定", LIGHT_GRAY, False, 11),
    ("• 运动补偿：减去无人机速度矢量→真实地面速度", ACCENT, False, 11),
], accent_color=GREEN)

# ════════════════════════════════════════════════════════
# SLIDE 8: 无人机运动补偿
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "无人机运动补偿技术", "GPS锚定世界坐标系 + 帧间遥测速度积分 + 悬停自动跳过")
add_page_number(slide, 8, TOTAL_SLIDES)

# Problem statement
add_shape(slide, Inches(0.6), Inches(1.6), Inches(12.1), Inches(0.8), fill_color=RGBColor(0x2E, 0x0A, 0x0A), border_color=RED, border_width=Pt(1.5))
add_multiline_text(slide, Inches(1.0), Inches(1.7), Inches(11), Inches(0.6), [
    ("核心问题：无人机巡飞速度可达12m/s (43km/h)，不减去自身速度将导致车速估计误差±43km/h", RED, True, 13),
    ("云台偏航旋转污染像素空间方向分类 | GPS提供绝对参考，帧间速度积分平滑GPS噪声", LIGHT_GRAY, False, 11),
])

# Three step solution
steps = [
    ("Step 1: GPS锚定", ACCENT, [
        "首10帧GPS均值 → 世界锚点",
        "ENU坐标系（东北天，米）",
        "lat/lon → 米级偏移量",
        "RTK固定解精度 < 2m",
    ]),
    ("Step 2: 帧间补偿", ACCENT2, [
        "遥测速度矢量投影到地面",
        "drone_displacement_m增量累计",
        "drone_velocity_ms实时注入",
        "SpeedNode减去无人机速度",
    ]),
    ("Step 3: 悬停检测", ACCENT3, [
        "horizontal_speed < 0.5m/s",
        "自动跳过运动补偿",
        "is_hovering标记输出",
        "Gimbal yaw delta校正方向",
    ]),
]
for i, (title, color, items) in enumerate(steps):
    x = Inches(0.6 + i * 4.1)
    add_shape(slide, x, Inches(2.7), Inches(3.7), Inches(2.8), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.2), Inches(2.85), Inches(3.3), Inches(0.4), title, font_size=15, color=color, bold=True)
    for j, item in enumerate(items):
        add_text_box(slide, x + Inches(0.3), Inches(3.4 + j * 0.4), Inches(3.2), Inches(0.35), f"• {item}", font_size=12, color=LIGHT_GRAY)

# Formula box
add_shape(slide, Inches(0.6), Inches(5.8), Inches(12.1), Inches(1.2), fill_color=BG_CARD2, border_color=ACCENT, border_width=Pt(1.5))
formula_lines = [
    ("关键公式", ACCENT, True, 14),
    ("v_vehicle = v_pixel×GSD×fps − v_drone      GSD = altitude_agl × sensor_width / (focal_length × image_width)  [m/px]", WHITE, False, 12),
    ("世界坐标：easting_m = (lon − anchor_lon) × 111320 × cos(anchor_lat)     northing_m = (lat − anchor_lat) × 111320", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(1.0), Inches(5.9), Inches(11), Inches(1.0), formula_lines)

# ════════════════════════════════════════════════════════
# SLIDE 9: 遥测驱动自动标定
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "遥测驱动自动标定系统", "像素→世界坐标映射：Nadir/Oblique双模式自动切换")
add_page_number(slide, 9, TOTAL_SLIDES)

# Left: Nadir mode
add_shape(slide, Inches(0.6), Inches(1.6), Inches(5.8), Inches(3.0), fill_color=BG_CARD, border_color=ACCENT, border_width=Pt(2))
add_text_box(slide, Inches(0.9), Inches(1.75), Inches(5), Inches(0.4), "Nadir模式  |gimbal_pitch| > 80°", font_size=16, color=ACCENT, bold=True)
nadir_lines = [
    ("简化2D相似变换，计算快、精度高", WHITE, True, 12),
    ("GSD = AGL × sensor_width / (focal × img_width)", ACCENT, False, 12),
    ("H = T(ground_offset) × R(yaw) × S(GSD)", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 6),
    ("• 适用：云台正下方(-90°)，悬停拍摄常用", LIGHT_GRAY, False, 11),
    ("• 精度：GSD误差<2%（AGL稳定±0.3m时）", LIGHT_GRAY, False, 11),
    ("• 实际数据：小清河 AGL=163.4m, GSD≈0.05m/px", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(0.9), Inches(2.25), Inches(5.2), Inches(2.2), nadir_lines)

# Right: Oblique mode
add_shape(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(3.0), fill_color=BG_CARD, border_color=ACCENT2, border_width=Pt(2))
add_text_box(slide, Inches(7.2), Inches(1.75), Inches(5), Inches(0.4), "Oblique模式  |gimbal_pitch| ≤ 80°", font_size=16, color=ACCENT2, bold=True)
oblique_lines = [
    ("完整透视变换，处理斜视畸变", WHITE, True, 12),
    ("R = Rz(yaw) × Ry(pitch) × Rx(roll)", ACCENT2, False, 12),
    ("P = K × [R|t] → H = P[:2,:]", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 6),
    ("• 适用：巡飞时云台非正下方角度", LIGHT_GRAY, False, 11),
    ("• 需相机内参：焦距+传感器尺寸（一次性配置）", LIGHT_GRAY, False, 11),
    ("• 变焦补偿：effective_fl = focal / zoom_factor", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(7.2), Inches(2.25), Inches(5.2), Inches(2.2), oblique_lines)

# Bottom: Three telemetry sources
add_shape(slide, Inches(0.6), Inches(4.9), Inches(12.1), Inches(2.2), fill_color=BG_CARD, border_color=DARK_LINE, border_width=Pt(1))
add_text_box(slide, Inches(0.9), Inches(5.0), Inches(3), Inches(0.4), "遥测数据源（统一接口）", font_size=14, color=WHITE, bold=True)

src_data = [
    ("MQTT 实时", "DJI Cloud API JSON\n生产环境直播", GREEN),
    ("SRT 字幕", "DJI视频字幕(.srt)\n离线逐帧精确回放", ACCENT2),
    ("JSON 文件", "遥测导出文件\n历史数据分析", ACCENT3),
]
for i, (name, desc, color) in enumerate(src_data):
    x = Inches(0.9 + i * 3.9)
    add_shape(slide, x, Inches(5.5), Inches(3.5), Inches(1.3), fill_color=BG_CARD2, border_color=color, border_width=Pt(1.5))
    add_text_box(slide, x + Inches(0.15), Inches(5.6), Inches(3.2), Inches(0.35), name, font_size=13, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    for j, line in enumerate(desc.split('\n')):
        add_text_box(slide, x + Inches(0.15), Inches(6.0 + j * 0.3), Inches(3.2), Inches(0.3), line, font_size=10, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)

add_text_box(slide, Inches(0.9), Inches(5.0), Inches(10), Inches(0.35),
    "遥测数据源 — 统一 get_nearest(timestamp) → dict 接口，VideoReader透明切换", font_size=13, color=WHITE, bold=True)

# ════════════════════════════════════════════════════════
# SLIDE 10: 方向流量与车道级分析
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "检测指标 — 方向流量与车道级分析", "零标注方向分类 + 数据驱动车道增强")
add_page_number(slide, 10, TOTAL_SLIDES)

# Direction flow (left)
add_shape(slide, Inches(0.6), Inches(1.6), Inches(6.0), Inches(5.3), fill_color=BG_CARD, border_color=ACCENT, border_width=Pt(2))
add_text_box(slide, Inches(0.9), Inches(1.7), Inches(5), Inches(0.4), "DirectionFlowNode — 始终运行（零标注）", font_size=15, color=ACCENT, bold=True)
df_lines = [
    ("方向分类算法", WHITE, True, 13),
    ("• 计算轨迹前半段(entry)和后半段(exit)的运动方向", LIGHT_GRAY, False, 12),
    ("• delta = exit_heading − entry_heading（归一化到±180°）", LIGHT_GRAY, False, 12),
    ("• |delta| ≤ 25° → 直行   |delta| ≥ 120° → 掉头", ACCENT, False, 12),
    ("• delta > 0 → 左转       delta < 0 → 右转", ACCENT, False, 12),
    ("", WHITE, False, 6),
    ("输出指标（每秒更新）", WHITE, True, 13),
    ("• direction_flow: {straight, left_turn, right_turn, u_turn}", LIGHT_GRAY, False, 11),
    ("• queue_count: 排队车辆数（speed < 5km/h）", LIGHT_GRAY, False, 11),
    ("• avg_speed_by_direction: 各方向平均车速", LIGHT_GRAY, False, 11),
    ("• headway_sec: 同方向连续车辆的车头时距", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 6),
    ("约束：轨迹需存活≥2秒（~6帧）方可分类", MID_GRAY, False, 11),
]
add_multiline_text(slide, Inches(0.9), Inches(2.2), Inches(5.5), Inches(4.5), df_lines)

# Lane analysis (right)
add_shape(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(5.3), fill_color=BG_CARD, border_color=ACCENT2, border_width=Pt(2))
add_text_box(slide, Inches(7.2), Inches(1.7), Inches(5), Inches(0.4), "LaneAnalysisNode — 数据驱动", font_size=15, color=ACCENT2, bold=True)
la_lines = [
    ("自动启用逻辑（无需配置开关）", WHITE, True, 13),
    ("• lane_polygons 为空？ → 自动跳过", LIGHT_GRAY, False, 12),
    ("• 非空 + 命中？ → 输出车道级指标", LIGHT_GRAY, False, 12),
    ("• 非空 + 未命中？ → 仅保留方向流量", LIGHT_GRAY, False, 12),
    ("", WHITE, False, 6),
    ("车道级输出指标", WHITE, True, 13),
    ("• 车道级流量：各车道多边形内车辆计数", LIGHT_GRAY, False, 11),
    ("• 车道级车速：各车道平均/最大车速", LIGHT_GRAY, False, 11),
    ("• 排队长度：速度<5km/h车辆到停车线距离(m)", LIGHT_GRAY, False, 11),
    ("• 车头时距：同车道连续车辆通过时间差", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 6),
    ("分配算法：Shapely point-in-polygon (bbox中心点)", MID_GRAY, False, 11),
    ("排队分段：相邻排队车辆间距>8m视为不同队列", MID_GRAY, False, 11),
]
add_multiline_text(slide, Inches(7.2), Inches(2.2), Inches(5.3), Inches(4.5), la_lines)

# ════════════════════════════════════════════════════════
# SLIDE 11: 车速估计与轨迹还原
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "检测指标 — 车速估计与轨迹还原", "透视变换+帧间位移 → km/h  |  世界坐标轨迹+转向分类")
add_page_number(slide, 11, TOTAL_SLIDES)

# Speed estimation (top left)
add_card(slide, Inches(0.6), Inches(1.6), Inches(5.8), Inches(2.5), "SpeedEstimationNode 车速估计", [
    ("算法流程", WHITE, True, 13),
    ("1. bbox中心点 → 单应性矩阵H → 世界坐标(米)", LIGHT_GRAY, False, 12),
    ("2. 最近15帧的位移向量 / dt → 瞬时速度", LIGHT_GRAY, False, 12),
    ("3. 减去无人机速度矢量 → 真实地面速度", ACCENT, False, 12),
    ("4. EMA平滑(窗口=5) → 消除bbox抖动噪声", LIGHT_GRAY, False, 12),
    ("5. 记录max_speed_kmh用于超速检测", LIGHT_GRAY, False, 12),
], accent_color=ACCENT)

# Trajectory (top right)
add_card(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(2.5), "TrajectoryNode 轨迹还原", [
    ("轨迹构建与输出", WHITE, True, 13),
    ("• 每帧追加bbox中心到track.trajectory_points", LIGHT_GRAY, False, 12),
    ("• 轨迹完成时发射：像素轨迹+世界坐标轨迹", LIGHT_GRAY, False, 12),
    ("• 转向分类：entry→exit向量夹角（含掉头检测）", ACCENT2, False, 12),
    ("• 独立Kafka topic: track_complete_{n}", LIGHT_GRAY, False, 12),
    ("• 含entry/exit_point_m世界坐标（米级精度）", LIGHT_GRAY, False, 12),
], accent_color=ACCENT2)

# Conflict detection (bottom left)
add_card(slide, Inches(0.6), Inches(4.4), Inches(5.8), Inches(2.5), "ConflictDetectionNode 机非冲突", [
    ("TTC (Time-To-Collision) 模型", WHITE, True, 13),
    ("• 仅Motor vs Non-Motor配对检测", LIGHT_GRAY, False, 12),
    ("• 距离计算：pixel_to_world → 米级欧式距离", LIGHT_GRAY, False, 12),
    ("• TTC = distance_m / speed_ms（接近速度）", ACCENT3, False, 12),
    ("• 配对冷却5秒，避免重复告警", LIGHT_GRAY, False, 12),
    ("• 无标定时自动跳过（避免误报）", LIGHT_GRAY, False, 12),
], accent_color=ACCENT3)

# Severity table (bottom right)
add_shape(slide, Inches(6.9), Inches(4.4), Inches(5.8), Inches(2.5), fill_color=BG_CARD, border_color=RED, border_width=Pt(2))
add_text_box(slide, Inches(7.2), Inches(4.5), Inches(5), Inches(0.4), "冲突严重度分级", font_size=15, color=RED, bold=True)
sev_lines = [
    ("级别       TTC阈值     距离阈值    告警等级", WHITE, True, 12),
    ("Critical    < 1.0s       < 1.5m        P1 — 即时推送", RED, False, 12),
    ("Warning    < 2.0s       < 3.0m        P2 — 高优先级", YELLOW, False, 12),
    ("Info           < 3.0s       < 5.0m        P3 — 记录", GREEN, False, 12),
    ("", WHITE, False, 6),
    ("输出字段：motor_id, non_motor_id, distance_m,", LIGHT_GRAY, False, 11),
    ("ttc_sec, severity, motor_speed_kmh, position_m", LIGHT_GRAY, False, 11),
    ("世界锚点：world_anchor_lat_lon（可GPS还原）", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(7.2), Inches(5.0), Inches(5.3), Inches(1.8), sev_lines)

# ════════════════════════════════════════════════════════
# SLIDE 12: 数据流架构 — Kafka + InfluxDB
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "数据流架构 — 消息总线与时序存储", "Kafka 3-Topic模型 → Telegraf → InfluxDB → Grafana/Platform")
add_page_number(slide, 12, TOTAL_SLIDES)

# Three Kafka topics
topics = [
    ("statistics_{n}", "每秒1次", ACCENT, [
        "cars: 车辆总数（滑动窗口均值）",
        "road_1~5: 各道路活跃度(辆/min)",
        "direction_flow: 方向流量统计",
        "avg_speed_kmh: 整体平均车速",
        "queue_count: 排队车辆数",
        "lane_stats: 车道级统计(可选)",
        "drone_position: 无人机位置",
        "is_hovering: 是否悬停",
    ]),
    ("track_complete_{n}", "轨迹完成时", ACCENT2, [
        "track_id: 轨迹ID",
        "start_road / exit_road: 进出口",
        "turn_behavior: 转向分类",
        "vehicle_class: motor/non_motor",
        "duration_sec: 轨迹持续时间",
        "avg/max_speed_kmh: 车速",
        "trajectory_px: 像素轨迹序列",
        "trajectory_world_m: 世界坐标轨迹",
    ]),
    ("conflicts_{n}", "事件触发时", RED, [
        "motor_id / non_motor_id",
        "distance_m: 米级距离",
        "ttc_sec: 碰撞时间",
        "severity: critical/warning/info",
        "motor_speed_kmh: 机动车速度",
        "position_m: 世界坐标位置",
        "world_anchor_lat_lon: GPS锚点",
        "",
    ]),
]

for i, (topic, freq, color, fields) in enumerate(topics):
    x = Inches(0.4 + i * 4.2)
    add_shape(slide, x, Inches(1.6), Inches(3.9), Inches(4.2), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.15), Inches(1.7), Inches(3.6), Inches(0.35), topic, font_size=14, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, x + Inches(0.15), Inches(2.05), Inches(3.6), Inches(0.25), f"频率: {freq}", font_size=10, color=MID_GRAY, alignment=PP_ALIGN.CENTER)
    field_lines = [(f"  {f}", LIGHT_GRAY, False, 10) for f in fields]
    add_multiline_text(slide, x + Inches(0.15), Inches(2.4), Inches(3.6), Inches(3.2), field_lines, font_size=10)

# Bottom: Data path
add_shape(slide, Inches(0.6), Inches(6.0), Inches(12.1), Inches(1.1), fill_color=BG_CARD2, border_color=DARK_LINE, border_width=Pt(1))
path_lines = [
    ("数据路径", WHITE, True, 13),
    ("Pipeline → Kafka(3 topics/camera) → Telegraf(json flat) → InfluxDB(measurement: camera_{N}) → Grafana", ACCENT, False, 11),
    ("Platform Consumer(aiokafka) → WebSocket(intersection:{id}) + AlertEngine + InfluxDB(track_events)", ACCENT2, False, 11),
]
add_multiline_text(slide, Inches(1.0), Inches(6.1), Inches(11), Inches(0.9), path_lines)

# ════════════════════════════════════════════════════════
# SLIDE 13: 平台API与集成接口
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "平台Web服务 — API与集成接口", "FastAPI单体架构 | 43条路由 | JWT认证 | WebSocket实时推送")
add_page_number(slide, 13, TOTAL_SLIDES)

# API categories
api_cats = [
    ("管道管理 /pipelines", ACCENT, [
        "POST   / — 启动管道(子进程)",
        "GET    / — 列出所有管道",
        "GET    /{id}/status — 健康检查",
        "DELETE /{id} — 停止(SIGTERM→SIGKILL)",
    ]),
    ("路口管理 /intersections", ACCENT2, [
        "GET / — 列出所有路口",
        "GET /summary — 系统级概览",
        "GET /{id}/stats — 历史统计(InfluxDB)",
        "GET /{id}/lane-stats — 车道级统计",
    ]),
    ("无人机管理 /drones", ACCENT3, [
        "GET  / — 实时状态(drone_store)",
        "GET  /{id}/trajectory — 飞行轨迹",
        "GET  /{id}/hover-points — 悬停点",
        "GET  /telemetry/{id} — 遥测数据",
    ]),
    ("系统监控 /system", GREEN, [
        "GET /health — 健康检查",
        "GET /gpu — GPU实时指标",
        "GET /kafka/topics — Topic状态",
        "GET /models — YOLO模型列表",
    ]),
]

for i, (title, color, items) in enumerate(api_cats):
    x = Inches(0.4 + i * 3.2)
    add_shape(slide, x, Inches(1.6), Inches(3.0), Inches(3.0), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.15), Inches(1.7), Inches(2.7), Inches(0.4), title, font_size=12, color=color, bold=True)
    item_lines = [(f"  {it}", LIGHT_GRAY, False, 10) for it in items]
    add_multiline_text(slide, x + Inches(0.15), Inches(2.2), Inches(2.7), Inches(2.2), item_lines, font_size=10)

# WebSocket section
add_shape(slide, Inches(0.6), Inches(4.9), Inches(12.1), Inches(2.2), fill_color=BG_CARD, border_color=ACCENT4, border_width=Pt(2))
add_text_box(slide, Inches(0.9), Inches(5.0), Inches(5), Inches(0.4), "WebSocket 实时推送 (WS /ws/{channel})", font_size=15, color=ACCENT4, bold=True)

ws_channels = [
    ("intersection:{id}", "stats + track_complete + conflict", ACCENT),
    ("alerts", "P1/P2/P3告警推送", RED),
    ("telemetry:{drone_id}", "GPS/高度/云台/速度", ACCENT2),
    ("system", "GPU/管道健康状态", GREEN),
]
for i, (ch, desc, color) in enumerate(ws_channels):
    x = Inches(0.9 + i * 3.0)
    add_shape(slide, x, Inches(5.5), Inches(2.7), Inches(1.2), fill_color=BG_CARD2, border_color=color, border_width=Pt(1))
    add_text_box(slide, x + Inches(0.1), Inches(5.6), Inches(2.5), Inches(0.35), ch, font_size=10, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, x + Inches(0.1), Inches(6.0), Inches(2.5), Inches(0.35), desc, font_size=10, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)

# ════════════════════════════════════════════════════════
# SLIDE 14: 输出数据规格
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "输出数据规格与接口标准", "结构化JSON消息 | InfluxDB时序存储 | 标准化坐标体系")
add_page_number(slide, 14, TOTAL_SLIDES)

# Statistics message sample
add_shape(slide, Inches(0.6), Inches(1.6), Inches(6.0), Inches(5.0), fill_color=BG_CARD, border_color=ACCENT, border_width=Pt(1.5))
add_text_box(slide, Inches(0.9), Inches(1.7), Inches(5), Inches(0.35), "统计消息示例 (statistics_{n})", font_size=14, color=ACCENT, bold=True)
json_lines = [
    ("{", LIGHT_GRAY, False, 10),
    ('  "camera_id": "id_1",', WHITE, False, 10),
    ('  "cars": 12,', WHITE, False, 10),
    ('  "intersection_id": "INT_camera_1",', WHITE, False, 10),
    ('  "direction_flow": {', ACCENT, False, 10),
    ('    "straight": {"count":5, "avg_speed_kmh":28.3,', ACCENT, False, 10),
    ('      "avg_headway_sec":2.1},', ACCENT, False, 10),
    ('    "left_turn": {"count":3, "avg_speed_kmh":22.1},', ACCENT, False, 10),
    ('    "right_turn": {"count":2, "avg_speed_kmh":25.0}', ACCENT, False, 10),
    ('  },', ACCENT, False, 10),
    ('  "queue_count": 2,', WHITE, False, 10),
    ('  "avg_speed_kmh": 26.5,', WHITE, False, 10),
    ('  "lane_stats": {"L1_1": {"count":3,...}},', ACCENT2, False, 10),
    ('  "drone_position": {', ACCENT3, False, 10),
    ('    "anchor_lat":31.23, "easting_m":15.3},', ACCENT3, False, 10),
    ('  "is_hovering": false', WHITE, False, 10),
    ("}", LIGHT_GRAY, False, 10),
]
add_multiline_text(slide, Inches(0.9), Inches(2.15), Inches(5.5), Inches(4.2), json_lines, font_size=10)

# Right: Data standards
add_shape(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(2.3), fill_color=BG_CARD, border_color=ACCENT2, border_width=Pt(1.5))
add_text_box(slide, Inches(7.2), Inches(1.7), Inches(5), Inches(0.35), "坐标体系标准", font_size=14, color=ACCENT2, bold=True)
coord_lines = [
    ("世界坐标：东北天(ENU)坐标系，单位：米", WHITE, True, 12),
    ("原点：世界锚点GPS位置（首10帧均值）", LIGHT_GRAY, False, 11),
    ("easting_m (+X) = 东向偏移", ACCENT, False, 11),
    ("northing_m (+Y) = 北向偏移", ACCENT, False, 11),
    ("GPS还原：lat = anchor + northing / 111320", LIGHT_GRAY, False, 11),
    ("lon = anchor + easting / (111320×cos(lat))", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(7.2), Inches(2.15), Inches(5.3), Inches(1.6), coord_lines)

# Right: InfluxDB schema
add_shape(slide, Inches(6.9), Inches(4.1), Inches(5.8), Inches(2.5), fill_color=BG_CARD, border_color=ACCENT3, border_width=Pt(1.5))
add_text_box(slide, Inches(7.2), Inches(4.2), Inches(5), Inches(0.35), "InfluxDB 存储结构", font_size=14, color=ACCENT3, bold=True)
influx_lines = [
    ("Measurement: camera_{N} (时序统计)", WHITE, True, 11),
    ("  fields: cars, road_1~5, avg_speed_kmh,", LIGHT_GRAY, False, 10),
    ("  direction_flow_*, queue_count, conflict_count", LIGHT_GRAY, False, 10),
    ("", WHITE, False, 4),
    ("Measurement: track_events (完成轨迹)", WHITE, True, 11),
    ("  tags: intersection_id, turn_behavior", LIGHT_GRAY, False, 10),
    ("  fields: track_id, duration, speed, trajectory", LIGHT_GRAY, False, 10),
    ("", WHITE, False, 4),
    ("Measurement: conflict_events (冲突事件)", WHITE, True, 11),
    ("  tags: severity", LIGHT_GRAY, False, 10),
    ("  fields: ttc_sec, distance_m, motor_speed", LIGHT_GRAY, False, 10),
]
add_multiline_text(slide, Inches(7.2), Inches(4.65), Inches(5.3), Inches(1.8), influx_lines)

# ════════════════════════════════════════════════════════
# SLIDE 15: 精度与可靠性指标
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "精度与可靠性指标", "端到端测试验证 | 49项自动化测试用例 | 真实飞行数据")
add_page_number(slide, 15, TOTAL_SLIDES)

# KPI boxes row 1
kpi_row1 = [
    ("35+ FPS", "处理帧率", "GPU RTX3060+", ACCENT),
    ("49/49", "E2E测试通过", "inter_xqh视频", ACCENT2),
    ("<5%", "BEV误判率", "vs 像素域>15%", GREEN),
    ("±2m", "GPS定位精度", "RTK固定解", ACCENT3),
]
for i, (val, label, sub, color) in enumerate(kpi_row1):
    x = Inches(0.6 + i * 3.15)
    add_shape(slide, x, Inches(1.6), Inches(2.85), Inches(1.5), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x, Inches(1.75), Inches(2.85), Inches(0.5), val, font_size=28, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, x, Inches(2.25), Inches(2.85), Inches(0.3), label, font_size=13, color=WHITE, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, x, Inches(2.55), Inches(2.85), Inches(0.3), sub, font_size=10, color=MID_GRAY, alignment=PP_ALIGN.CENTER)

# Reliability table
add_shape(slide, Inches(0.6), Inches(3.4), Inches(12.1), Inches(3.5), fill_color=BG_CARD, border_color=DARK_LINE, border_width=Pt(1))
add_text_box(slide, Inches(0.9), Inches(3.5), Inches(5), Inches(0.4), "各模块精度与可靠性", font_size=15, color=WHITE, bold=True)

metrics = [
    ("检测模块", "YOLO11 mAP@0.5", "自训练UAV模型，俯视角优化", "conf=0.10低阈值+ByteTrack二轮关联恢复漏检", ACCENT),
    ("跟踪模块", "ByteTrack IDF1", "双阈值关联，密集场景鲁棒", "track_buffer=250帧容忍抖动丢失", ACCENT2),
    ("车速估计", "±3km/h (EMA后)", "15帧位移+单应性变换", "减去无人机速度矢量，EMA窗口=5平滑", GREEN),
    ("方向分类", ">85% 准确率", "轨迹首尾向量夹角", "需轨迹≥2秒，短轨迹归入unknown", ACCENT3),
    ("标定系统", "GSD误差<2%", "遥测驱动自动H矩阵", "AGL稳定±0.3m，三级查表+插值", ACCENT4),
    ("冲突检测", "TTC精度±0.3s", "世界坐标米级距离", "配对冷却5s避免重复，无标定时自动跳过", RED),
]

header = ("模块", "指标", "方法", "可靠性保障", ACCENT)
cols = [Inches(0.9), Inches(2.8), Inches(5.2), Inches(8.2), Inches(11.2)]
col_widths = [Inches(1.8), Inches(2.3), Inches(2.9), Inches(2.9), Inches(0.5)]

# Header
add_text_box(slide, cols[0], Inches(3.95), col_widths[0], Inches(0.3), "模块", font_size=11, color=MID_GRAY, bold=True)
add_text_box(slide, cols[1], Inches(3.95), col_widths[1], Inches(0.3), "核心指标", font_size=11, color=MID_GRAY, bold=True)
add_text_box(slide, cols[2], Inches(3.95), col_widths[2], Inches(0.3), "算法方法", font_size=11, color=MID_GRAY, bold=True)
add_text_box(slide, cols[3], Inches(3.95), col_widths[3], Inches(0.3), "可靠性保障", font_size=11, color=MID_GRAY, bold=True)

for i, (module, metric, method, guarantee, color) in enumerate(metrics):
    y = Inches(4.3 + i * 0.4)
    add_text_box(slide, cols[0], y, col_widths[0], Inches(0.35), module, font_size=11, color=color, bold=True)
    add_text_box(slide, cols[1], y, col_widths[1], Inches(0.35), metric, font_size=11, color=WHITE)
    add_text_box(slide, cols[2], y, col_widths[2], Inches(0.35), method, font_size=10, color=LIGHT_GRAY)
    add_text_box(slide, cols[3], y, col_widths[3], Inches(0.35), guarantee, font_size=10, color=LIGHT_GRAY)

# ════════════════════════════════════════════════════════
# SLIDE 16: 典型落地场景
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "典型落地场景", "从POC验证到规模化部署的应用路径")
add_page_number(slide, 16, TOTAL_SLIDES)

scenarios = [
    ("路口信号配时优化", ACCENT, [
        "悬停模式采集路口全要素数据",
        "各进口道转向流量精确统计",
        "排队长度+车头时距→配时参数",
        "信号周期效率评估与优化建议",
    ], "交警/交规院"),
    ("交通事故快速响应", ACCENT3, [
        "巡飞模式路段全覆盖",
        "TTC模型实时检测冲突事件",
        "P1告警<30s推送到指挥中心",
        "事故现场自动标注+轨迹回溯",
    ], "交警/应急"),
    ("大型活动交通保障", ACCENT2, [
        "多机协同覆盖活动周边路网",
        "实时流量热力图→分流决策",
        "VLM语义旁路生成态势简报",
        "事后自动生成分析报告(PDF)",
    ], "大型活动安保"),
    ("城市交通规划评估", GREEN, [
        "多时段多路口数据采集",
        "轨迹还原→OD矩阵估计",
        "InfluxDB时序数据长期趋势分析",
        "Grafana可视化支撑规划决策",
    ], "规划局/设计院"),
]

for i, (title, color, items, user) in enumerate(scenarios):
    x = Inches(0.4 + i * 3.2)
    add_shape(slide, x, Inches(1.6), Inches(3.0), Inches(4.4), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.15), Inches(1.7), Inches(2.7), Inches(0.4), title, font_size=14, color=color, bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, x + Inches(0.15), Inches(2.1), Inches(2.7), Inches(0.25), f"目标用户: {user}", font_size=9, color=MID_GRAY, alignment=PP_ALIGN.CENTER)
    for j, item in enumerate(items):
        add_text_box(slide, x + Inches(0.2), Inches(2.5 + j * 0.45), Inches(2.6), Inches(0.4), f"• {item}", font_size=11, color=LIGHT_GRAY)

# Validated data
add_shape(slide, Inches(0.6), Inches(6.2), Inches(12.1), Inches(0.9), fill_color=BG_CARD2, border_color=ACCENT, border_width=Pt(1.5))
add_multiline_text(slide, Inches(1.0), Inches(6.3), Inches(11), Inches(0.7), [
    ("已验证飞行数据", WHITE, True, 13),
    ("小清河北路×水屯路 — 20min悬停 | AGL 163.4m | RTK固定解 | 云台-90° | 453帧悬停数据 | 已用于端到端49项测试", ACCENT, False, 11),
])

# ════════════════════════════════════════════════════════
# SLIDE 17: 系统集成方案
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "系统集成方案", "Docker Compose一键部署 | 水平扩展 | 标准化接口对接")
add_page_number(slide, 17, TOTAL_SLIDES)

# Deployment architecture
add_card(slide, Inches(0.6), Inches(1.6), Inches(5.8), Inches(2.3), "部署架构", [
    ("Docker Compose全栈编排", WHITE, True, 12),
    ("• 检测管道容器（GPU）× N（按路口数扩展）", LIGHT_GRAY, False, 11),
    ("• Kafka + Zookeeper（消息总线）", LIGHT_GRAY, False, 11),
    ("• InfluxDB 1.8（时序存储，30天保留策略）", LIGHT_GRAY, False, 11),
    ("• Telegraf（Kafka→InfluxDB桥接）", LIGHT_GRAY, False, 11),
    ("• Grafana（可视化仪表盘，自动provisioning）", LIGHT_GRAY, False, 11),
    ("• Nginx（视频流聚合+API反代）", LIGHT_GRAY, False, 11),
], accent_color=ACCENT)

add_card(slide, Inches(6.9), Inches(1.6), Inches(5.8), Inches(2.3), "扩展策略", [
    ("水平扩展：+1路口 = +1容器", WHITE, True, 12),
    ("• 新增VIDEO_SRC/ROADS_JSON/TOPIC_NAME环境变量", LIGHT_GRAY, False, 11),
    ("• 自动创建Kafka topic（statistics_N+1）", LIGHT_GRAY, False, 11),
    ("• 独立Grafana仪表盘（provisioning模板化）", LIGHT_GRAY, False, 11),
    ("• PipelineManager管理子进程生命周期", LIGHT_GRAY, False, 11),
    ("• 支持GPU A(YOLO) + GPU B(VLM)双卡方案", LIGHT_GRAY, False, 11),
], accent_color=ACCENT2)

# Integration points
add_card(slide, Inches(0.6), Inches(4.2), Inches(3.7), Inches(2.8), "集成对接方式", [
    ("REST API (43条路由)", ACCENT, True, 12),
    ("标准JSON + JWT认证", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 4),
    ("WebSocket (4频道)", ACCENT2, True, 12),
    ("实时数据推送", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 4),
    ("Kafka Consumer", ACCENT3, True, 12),
    ("直接消费原始消息", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 4),
    ("InfluxDB InfluxQL", GREEN, True, 12),
    ("时序数据直查", LIGHT_GRAY, False, 11),
], accent_color=ACCENT)

add_card(slide, Inches(4.6), Inches(4.2), Inches(4.0), Inches(2.8), "配置管理", [
    ("Hydra 分层配置", WHITE, True, 12),
    ("• configs/app_config.yaml 主配置", LIGHT_GRAY, False, 11),
    ("• 环境变量覆盖(oc.env)", LIGHT_GRAY, False, 11),
    ("• CLI覆盖(pipeline.save=True)", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 4),
    ("Pydantic Settings (Platform)", WHITE, True, 12),
    ("• 环境变量统一管理", LIGHT_GRAY, False, 11),
    ("• Docker compose环境注入", LIGHT_GRAY, False, 11),
], accent_color=ACCENT2)

add_card(slide, Inches(8.9), Inches(4.2), Inches(3.8), Inches(2.8), "运维监控", [
    ("健康检查端点", WHITE, True, 12),
    ("• /health — 存活检查", LIGHT_GRAY, False, 11),
    ("• /ready — 就绪检查", LIGHT_GRAY, False, 11),
    ("• 各依赖状态(degraded/healthy)", LIGHT_GRAY, False, 11),
    ("", WHITE, False, 4),
    ("进程健康", WHITE, True, 12),
    ("• is_alive() + Queue timeout", LIGHT_GRAY, False, 11),
    ("• 5s存活状态后台监控", LIGHT_GRAY, False, 11),
], accent_color=ACCENT3)

# ════════════════════════════════════════════════════════
# SLIDE 18: 风险与应对策略
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "风险分析与应对策略", "技术风险 + 工程风险 + 运营风险 — 全面预案")
add_page_number(slide, 18, TOTAL_SLIDES)

risks = [
    ("GPS信号丢失/漂移", "高", RED, 
     "保持上次位移增量（非绝对准确）\n首10帧GPS锚点初始化\nRTK固定解质量监控",
     "降级为像素空间分析"),
    ("无人机抖动超限", "中", YELLOW,
     "三轴云台硬件防抖为主\nEIS软件层ORB特征匹配补偿\ntrack_buffer=250帧容忍丢失",
     "选风速<6m/s窗口期飞行"),
    ("GPU算力瓶颈", "中", YELLOW,
     "VLM旁路独立GPU（双卡方案）\n旁路崩溃不影响主链路\n单卡降级：VLM降频至120帧/次",
     "边缘计算+云端VLM混合"),
    ("标定参数失效", "中", YELLOW,
     "三级查表（精确→插值→告警）\n俯仰/高度/匹配率三指标监控\n自动重标定+回退航点",
     "calib_quality标记降级数据"),
    ("模型泛化不足", "低", GREEN,
     "自训练UAV视角模型(uav_best.pt)\n行人/自行车类别待微调\n在线学习框架预留",
     "分场景模型库管理"),
    ("网络传输中断", "低", GREEN,
     "Kafka消息持久化\nRTSP断线自动重连\n本地缓存+补传机制",
     "4G/5G双链路冗余"),
]

for i, (risk, level, color, mitigation, fallback) in enumerate(risks):
    row = i // 3
    col = i % 3
    x = Inches(0.4 + col * 4.2)
    y = Inches(1.6 + row * 2.9)
    
    add_shape(slide, x, y, Inches(3.9), Inches(2.6), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.15), y + Inches(0.1), Inches(2.8), Inches(0.35), risk, font_size=13, color=WHITE, bold=True)
    add_text_box(slide, x + Inches(3.0), y + Inches(0.1), Inches(0.8), Inches(0.3), f"风险:{level}", font_size=9, color=color, bold=True, alignment=PP_ALIGN.RIGHT)
    
    mit_lines = [(f"• {l}", LIGHT_GRAY, False, 10) for l in mitigation.split('\n')]
    add_multiline_text(slide, x + Inches(0.15), y + Inches(0.5), Inches(3.6), Inches(1.4), mit_lines, font_size=10)
    
    add_text_box(slide, x + Inches(0.15), y + Inches(2.0), Inches(3.6), Inches(0.4), f"→ {fallback}", font_size=10, color=ACCENT)

# ════════════════════════════════════════════════════════
# SLIDE 19: 合作推进路径
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)
add_section_header(slide, "合作推进路径", "三期交付路线 — 从POC验证到规模化部署")
add_page_number(slide, 19, TOTAL_SLIDES)

phases = [
    ("Phase 1: POC验证", "W1-W4", ACCENT, [
        ("M1: 单路口端到端联调", WHITE, True, 12),
        ("• 小清河路口标定+IPM透视变换", LIGHT_GRAY, False, 11),
        ("• YOLO11检测+ByteTrack跟踪", LIGHT_GRAY, False, 11),
        ("• Grafana实时大屏4面板", LIGHT_GRAY, False, 11),
        ("• 标注工具Web UI(5分钟新路口接入)", ACCENT, False, 11),
        ("• Kafka 3-Topic数据流验证", LIGHT_GRAY, False, 11),
    ]),
    ("Phase 2: 功能完善", "W5-W8", ACCENT2, [
        ("M2: 全要素感知+告警", WHITE, True, 12),
        ("• VLM语义旁路(Qwen-VL 7B)", LIGHT_GRAY, False, 11),
        ("• 告警规则引擎+Webhook推送(<30s)", LIGHT_GRAY, False, 11),
        ("• 热成像双通道融合", LIGHT_GRAY, False, 11),
        ("• 早高峰自动分析报告(PDF)", LIGHT_GRAY, False, 11),
        ("• 冲突检测模型微调(person+bicycle)", LIGHT_GRAY, False, 11),
    ]),
    ("Phase 3: 规模部署", "W9-W12", ACCENT3, [
        ("M3: 多机多路口协同", WHITE, True, 12),
        ("• GIS多路口一张图", LIGHT_GRAY, False, 11),
        ("• 飞行轨迹回放面板", LIGHT_GRAY, False, 11),
        ("• EIS画面稳定+强风场景优化", LIGHT_GRAY, False, 11),
        ("• 精度基准离线评估(mAP/误判率)", LIGHT_GRAY, False, 11),
        ("• 25分钟CTO演示无卡顿", LIGHT_GRAY, False, 11),
    ]),
]

for i, (title, period, color, items) in enumerate(phases):
    x = Inches(0.4 + i * 4.2)
    add_shape(slide, x, Inches(1.6), Inches(3.9), Inches(4.0), fill_color=BG_CARD, border_color=color, border_width=Pt(2))
    add_text_box(slide, x + Inches(0.2), Inches(1.7), Inches(3.5), Inches(0.4), title, font_size=16, color=color, bold=True)
    add_text_box(slide, x + Inches(0.2), Inches(2.1), Inches(3.5), Inches(0.25), period, font_size=11, color=MID_GRAY)
    add_multiline_text(slide, x + Inches(0.2), Inches(2.45), Inches(3.5), Inches(3.0), items, font_size=11)

# Dependencies
add_shape(slide, Inches(0.6), Inches(5.9), Inches(12.1), Inches(1.2), fill_color=BG_CARD2, border_color=DARK_LINE, border_width=Pt(1))
dep_lines = [
    ("依赖关系与关键路径", WHITE, True, 13),
    ("P1(标定) → P2(检测) → P3(方向流量) → P4(轨迹) → P5(遥测) → P6(冲突，依赖模型微调) → P7(清理集成)", ACCENT, False, 11),
    ("VLM旁路(W5-7) 与 EIS+联调(W4-5) 可并行    |    冲突检测(Phase 6) 依赖 YOLO模型微调(person+bicycle)", LIGHT_GRAY, False, 11),
]
add_multiline_text(slide, Inches(1.0), Inches(6.0), Inches(11), Inches(1.0), dep_lines)

# ════════════════════════════════════════════════════════
# SLIDE 20: 结尾页
# ════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, BG_DARK)

# Decorative elements
shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(8.5), Inches(-1.5), Inches(7), Inches(7))
shape.fill.solid()
shape.fill.fore_color.rgb = RGBColor(0x0F, 0x1C, 0x33)
shape.line.fill.background()

shape2 = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(-3), Inches(4), Inches(6), Inches(6))
shape2.fill.solid()
shape2.fill.fore_color.rgb = RGBColor(0x0D, 0x18, 0x2E)
shape2.line.fill.background()

# Accent line
add_rect(slide, Inches(1.2), Inches(2.2), Inches(0.8), Pt(5), fill_color=ACCENT)

# Thank you text
add_text_box(slide, Inches(1.2), Inches(2.5), Inches(10), Inches(1.0),
    "谢谢", font_size=48, color=WHITE, bold=True)
add_text_box(slide, Inches(1.2), Inches(3.5), Inches(10), Inches(0.6),
    "期待与您共同推进无人机交通态势感知的落地应用", font_size=18, color=LIGHT_GRAY)

# Summary highlights
add_rect(slide, Inches(1.2), Inches(4.5), Inches(10), Pt(1), fill_color=DARK_LINE)

highlights = [
    ("双模式覆盖", "巡飞路段级 + 悬停路口级"),
    ("全要素感知", "流量/车速/排队/转向/轨迹/冲突"),
    ("即插即用", "Docker一键部署，Kafka标准接口"),
    ("已验证", "49项E2E测试通过，真实飞行数据"),
]
for i, (title, desc) in enumerate(highlights):
    x = Inches(1.2 + i * 2.7)
    add_text_box(slide, x, Inches(4.8), Inches(2.5), Inches(0.35), title, font_size=14, color=ACCENT, bold=True)
    add_text_box(slide, x, Inches(5.15), Inches(2.5), Inches(0.3), desc, font_size=11, color=LIGHT_GRAY)

# Bottom bar
add_rect(slide, Inches(0), Inches(6.7), W, Inches(0.8), fill_color=RGBColor(0x08, 0x10, 0x1E))
add_text_box(slide, Inches(1.2), Inches(6.85), Inches(10), Inches(0.4),
    "UAV-Based Urban Traffic Situation Awareness  |  2026.05", font_size=12, color=MID_GRAY)

# ──────────────────── Save ────────────────────
output_path = "/Users/yaoyao/ai/TrafficAnalyzer/uav_traffic_cto_v2.pptx"
prs.save(output_path)
print(f"PPT saved to: {output_path}")
print(f"Total slides: {len(prs.slides)}")
