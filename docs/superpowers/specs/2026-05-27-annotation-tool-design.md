# 标注工具（Annotation Tool）设计规格

> 日期：2026-05-27  
> 方案：C — 混合式（引导式标定工作流 + 独立管理面板）  
> 关联规划：`docs/无人机交通态势监测_POC规划_v1.0.md` §5.2

---

## 1. Context

### 1.1 为什么需要这个工具

无人机路口交通态势监测系统的核心瓶颈是**透视标定**：无人机每次换高度/角度，原有的像素坐标车道配置就失效。标定工具必须让操作员在 5 分钟内完成新路口的透视标定 + 车道多边形标注，这是 CTO 演示的核心亮点，也是生产环境多路口扩展的基础。

### 1.2 设计目标

| 目标 | 说明 |
|---|---|
| 演示流畅 | CTO 现场 5 分钟完成新路口标定，流程连贯无卡顿 |
| 生产可用 | 多人操作、版本管理、编辑锁、数据安全 |
| 零构建前端 | 无 React/Vue 依赖，Vanilla JS + Konva.js，直接 serve 静态文件 |
| 与管道解耦 | 标注工具是独立应用，不嵌入管道进程，通过 `calibration_db.json` 文件通信 |

### 1.3 非目标

- 不做实时视频流接入（标注工具处理的是静态帧或录制视频）
- 不做用户认证系统（POC 阶段用简单用户名，不做 OAuth/LDAP）
- 不做 GIS 地图集成（P2 阶段再做）

---

## 2. 整体架构

### 2.1 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端框架 | Flask | 与项目已有 FlaskServerVideoNode 技术栈一致 |
| API 风格 | RESTful JSON | 前后端分离，前端用 fetch 调用 |
| 几何计算 | OpenCV + NumPy | `cv2.findHomography(RANSAC)` + `cv2.warpPerspective`，项目已有依赖 |
| 视频处理 | OpenCV VideoCapture | 帧提取，项目已有依赖 |
| 存储 | JSON 文件 | `calibration_db.json`，与管道读取端格式一致 |
| 前端框架 | Vanilla JS | 无构建步骤，降低复杂度 |
| Canvas 库 | Konva.js | 多边形绘制、拖拽、缩放、事件处理成熟 |
| 样式 | CSS 变量 + Flexbox | 深色主题，与 Grafana 风格统一 |
| 路由 | 原生 History API | 3 个页面，不需要 SPA 框架 |

### 2.2 页面路由

| URL | 页面 | 功能 |
|---|---|---|
| `GET /` | 仪表盘首页 | 状态概览 + 入口卡片 |
| `GET /calibrate` | 标定工作流 | 4 步引导：选帧 → 透视标定 → 车道编辑 → 验证保存 |
| `GET /manage` | 标定管理面板 | 标定列表 + 覆盖率热图 + 版本历史 |

### 2.3 API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| `POST` | `/api/frame/extract` | 从视频/图片提取帧 + 解析 SRT 遥测数据 |
| `POST` | `/api/frame/select` | 从飞行数据目录扫描视频+SRT 匹配 |
| `POST` | `/api/calibrate/homography` | 传入 4 组像素-世界坐标对应点，计算 H_mat |
| `POST` | `/api/calibrate/preview` | 传入 H_mat + 帧，返回 BEV 预览图 |
| `POST` | `/api/calibrate/lanes` | 保存车道多边形到标定库 |
| `POST` | `/api/calibrate/validate` | 验证标定质量（重投影误差 + 后续帧匹配率） |
| `POST` | `/api/calibrate/save` | 保存完整标定记录（H_mat + 车道 + 质量评分） |
| `GET` | `/api/calibrations` | 查询标定列表（支持过滤、搜索） |
| `GET` | `/api/calibrations/{key}` | 获取单条标定详情（含版本历史） |
| `DELETE` | `/api/calibrations/{key}` | 删除标定记录 |
| `GET` | `/api/calibrations/coverage` | 覆盖率热图数据（高度×俯仰角矩阵） |
| `POST` | `/api/calibrations/{key}/lock` | 锁定编辑 |
| `POST` | `/api/calibrations/{key}/unlock` | 解锁编辑 |
| `POST` | `/api/calibrations/{key}/rollback` | 回滚到指定版本 |
| `GET` | `/api/calibrations/{key}/versions` | 获取版本历史列表 |
| `GET` | `/api/templates` | 获取先验模板列表（标准车道配置） |

### 2.4 目录结构

```
annotation/
├── app.py                        # Flask 应用入口 + 路由注册
├── api/
│   ├── __init__.py
│   ├── frame_routes.py           # 帧提取 API（/api/frame/*）
│   ├── calibrate_routes.py       # 标定工作流 API（/api/calibrate/*）
│   ├── manage_routes.py          # 标定管理 API（/api/calibrations/*）
│   └── lock_routes.py            # 锁定/解锁 API
├── core/
│   ├── __init__.py
│   ├── srt_parser.py             # SRT 遥测文件解析器
│   ├── homography.py             # 单应矩阵计算（RANSAC）+ 质量评估
│   ├── bev_preview.py            # BEV 鸟瞰图渲染（warpPerspective）
│   ├── quality_scorer.py         # 标定质量评分（重投影误差 + 宽度一致性 + 平行度）
│   ├── video_frame_extractor.py  # 视频帧提取（支持 MP4 进度条选帧）
│   └── template_engine.py        # 先验模板管理（标准车道宽度配置）
├── storage/
│   ├── __init__.py
│   ├── calib_store.py            # calibration_db.json CRUD 操作
│   ├── version_manager.py        # 版本历史管理（保留最近 10 版）
│   └── lock_manager.py           # 编辑锁管理（30 分钟自动释放）
├── static/
│   ├── css/
│   │   └── main.css              # 全局样式（深色主题 + CSS 变量）
│   ├── js/
│   │   ├── app.js                # 路由 + 页面切换（History API）
│   │   ├── dashboard.js          # 仪表盘首页逻辑
│   │   ├── calibrate.js          # 标定工作流 4 步引导逻辑
│   │   ├── lane-editor.js        # Konva.js 车道多边形编辑器
│   │   ├── manage.js             # 管理面板（列表 + 搜索 + 过滤）
│   │   └── heatmap.js            # 覆盖率热图渲染
│   └── vendor/
│       └── konva.min.js          # Konva.js 库（v9.x）
├── templates/
│   └── index.html                # SPA 入口页（含路由容器 div）
└── configs/
    └── templates.json            # 先验模板定义（标准车道配置）
```

---

## 3. 标定工作流（4 步引导）

### 3.1 Step 1：选帧（Frame Selection）

**输入方式**（三选一）：

1. **上传单帧图片**：拖拽或点击上传 JPG/PNG，手动填写遥测参数
2. **加载视频文件**：上传 MP4，进度条拖拽选帧，自动提取该帧
3. **飞行数据目录**：扫描 `flights/` 目录，自动匹配视频文件与同名 SRT 文件，用户选择后加载

**自动处理**：

- 从 SRT 文件解析遥测数据：`intersection_id`、`alt_agl`、`gimbal_pitch`、GPS 坐标、`gps_type`
- 根据 `alt_agl` 和 `gimbal_pitch` 生成 `calib_key`：`{intersection_id}__H{int(alt/2)*2}__P{int((pitch+90)/2)*2-90}`
- 根据 `calib_key` 查询标定库，如果已有标定则提示"该参数组合已存在标定，是否覆盖？"
- 根据 GPS 坐标和路口 ID 匹配先验模板（标准车道配置）

**模板匹配逻辑**：

```python
# core/template_engine.py
TEMPLATES = {
    "standard_4lane": {
        "description": "标准四车道（3.5m/车道）",
        "lane_count": 4,
        "lane_width_m": 3.5,
        "road_length_m": 50.0,
        "world_points": [[0,0],[14,0],[0,50],[14,50]]  # 4 个基准点世界坐标
    },
    "standard_5lane": {
        "description": "标准五车道（3.5m/车道）",
        "lane_count": 5,
        "lane_width_m": 3.5,
        "road_length_m": 50.0,
        "world_points": [[0,0],[17.5,0],[0,50],[17.5,50]]
    },
    "wide_4lane": {
        "description": "宽幅四车道（3.75m/车道）",
        "lane_count": 4,
        "lane_width_m": 3.75,
        "road_length_m": 50.0,
        "world_points": [[0,0],[15,0],[0,50],[15,50]]
    }
}
```

**模板匹配逻辑**：模板是通用先验，不按路口 ID 或 GPS 匹配。系统默认选择 `standard_4lane` 作为初始推荐，用户在 Step 1 的下拉菜单中可切换其他模板。如果 `calibration_db.json` 中已有同路口（相同 `intersection_id`）的历史标定记录，则沿用该记录使用过的模板。

**输出**：选中帧的 numpy 数组 + SRT 遥测数据字典 + 匹配的先验模板

### 3.2 Step 2：透视标定（Homography Calibration）

**操作流程**：

1. 左侧显示原始帧，右侧显示 BEV 预览（初始为空白）
2. 系统根据 SRT 自动估算初始单应矩阵（正射投影近似）：
   - `pixel_scale = sensor_width_mm / (focal_length_mm * alt_agl) * image_width_px`（简化模型）
   - 生成初始 H_mat，渲染 BEV 预览
3. 用户在原始帧上点击 4 个路面基准点（斑马线角点、停车线端点）
4. 每点一个点，右侧 BEV 实时更新
5. 4 点完成后，调用 `cv2.findHomography(src_pts, dst_pts, cv2.RANSAC)` 计算精确 H_mat
6. 世界坐标基准点来自匹配的先验模板，用户可在下方面板微调

**SRT 自动估算初始 H_mat**：

```python
# core/homography.py
def estimate_initial_homography(alt_agl: float, gimbal_pitch: float, 
                                 image_shape: tuple, pixel_scale: float) -> np.ndarray:
    """
    基于无人机高度和正射投影近似估算初始单应矩阵。
    仅用于 BEV 预览初始渲染，精确值由用户 4 点标定覆盖。
    """
    h, w = image_shape[:2]
    # 正射投影：像素坐标 → 世界坐标（米）
    # 简化模型：假设 gimbal_pitch = -90°（正射）
    scale = pixel_scale  # 米/像素
    cx, cy = w / 2, h / 2  # 图像中心 = 世界坐标原点
    H = np.array([
        [scale, 0, -cx * scale],
        [0, scale, -cy * scale],
        [0, 0, 1]
    ], dtype=np.float64)
    return H
```

**精确标定计算**：

```python
# core/homography.py
def compute_homography(pixel_points: list, world_points: list) -> dict:
    """
    用 RANSAC 计算精确单应矩阵。
    返回 H_mat + 重投影误差 + 内点数。
    """
    src = np.array(pixel_points, dtype=np.float32)
    dst = np.array(world_points, dtype=np.float32)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=3.0)
    inliers = int(mask.sum()) if mask is not None else len(src)
    # 重投影误差
    projected = cv2.perspectiveTransform(src.reshape(1, -1, 2), H).reshape(-1, 2)
    error = np.mean(np.sqrt(np.sum((projected - dst) ** 2, axis=1)))
    return {
        "H_mat": H.tolist(),
        "reprojection_error": float(error),
        "inliers": inliers,
        "total_points": len(src)
    }
```

**交互细节**：

- 左键点击 = 添加基准点，按顺序编号（P1 → P2 → P3 → P4）
- 右键点击 = 撤销上一个点
- 基准点渲染为红色圆点 + 编号标签
- BEV 预览使用 `cv2.warpPerspective` 实时渲染

### 3.3 Step 3：车道编辑（Lane Polygon Editor）

**核心组件**：Konva.js Canvas（BEV 坐标系）

**功能**：

1. **绘制车道多边形**：在 BEV 画布上点击添加顶点，双击闭合多边形
2. **拖拽编辑**：选中多边形后可拖拽整体移动，选中顶点可单独拖拽
3. **属性面板**：右侧面板编辑车道 ID、名称、方向（进入/离开路口）
4. **辅助功能**：
   - 网格对齐（0.5m 间距）
   - 吸附功能（相邻车道共享边自动吸附）
   - 复制车道（快速生成等宽平行车道）
5. **导入 CAD**：支持从 DXF/SVG 文件导入车道线（P2 阶段实现）

**BEV 画布参数**：

```javascript
// static/js/lane-editor.js
const CANVAS_CONFIG = {
    width: 800,           // Canvas 像素宽度
    height: 600,          // Canvas 像素高度
    worldScale: 10,       // 像素/米（1 米 = 10 像素）
    gridSpacing: 5,       // 网格间距（像素）= 0.5m
    snapEnabled: true,    // 吸附功能
    snapThreshold: 5,     // 吸附阈值（像素）
    laneColors: ['#f56565', '#ecc94b', '#48bb78', '#4299e1', '#9f7aea', '#ed8936'],
    strokeWidth: 2,
    vertexRadius: 4,
    fillOpacity: 0.15
};
```

**输出格式**（与管道 `calibration_db.json` 一致）：

```json
{
    "lane_polygons_bev": {
        "1": [[0.0, 0.0], [3.5, 0.0], [3.5, 50.0], [0.0, 50.0]],
        "2": [[3.5, 0.0], [7.0, 0.0], [7.0, 50.0], [3.5, 50.0]],
        "3": [[7.0, 0.0], [10.5, 0.0], [10.5, 50.0], [7.0, 50.0]],
        "4": [[10.5, 0.0], [14.0, 0.0], [14.0, 50.0], [10.5, 50.0]]
    }
}
```

### 3.4 Step 4：验证与保存

**自动质量评分**（三项指标）：

```python
# core/quality_scorer.py
def score_calibration(H_mat, pixel_points, world_points, lane_polygons_bev) -> dict:
    """计算标定质量评分"""
    
    # 1. 重投影误差（像素）
    projected = cv2.perspectiveTransform(
        np.array(pixel_points, dtype=np.float32).reshape(1, -1, 2), 
        H_mat
    ).reshape(-1, 2)
    reprojection_error = float(np.mean(
        np.sqrt(np.sum((projected - np.array(world_points)) ** 2, axis=1))
    ))
    
    # 2. 车道宽度一致性（标准差 / 均值）
    widths = []
    for lane_id, coords in lane_polygons_bev.items():
        # 假设四边形：左右两边平行，取上下两对点的距离
        w_top = np.sqrt((coords[1][0] - coords[0][0])**2 + (coords[1][1] - coords[0][1])**2)
        w_bot = np.sqrt((coords[2][0] - coords[3][0])**2 + (coords[2][1] - coords[3][1])**2)
        widths.extend([w_top, w_bot])
    width_std = float(np.std(widths))
    width_mean = float(np.mean(widths))
    width_consistency = 1.0 - (width_std / width_mean) if width_mean > 0 else 0
    
    # 3. 车道平行度（相邻车道共享边的角度差）
    # 检查所有车道左右边线方向向量的角度偏差
    # 取每条车道左右边线的方向向量，计算相邻车道间角度差
    # parallelism = 1 - mean(angle_diff) / 90，完美平行时为 1.0
    parallelism = compute_parallelism(lane_polygons_bev)
    
    # 综合评分
    if reprojection_error < 5 and width_consistency > 0.9 and parallelism > 0.95:
        score = "excellent"
    elif reprojection_error < 10 and width_consistency > 0.8 and parallelism > 0.9:
        score = "good"
    elif reprojection_error < 20 and width_consistency > 0.7:
        score = "acceptable"
    else:
        score = "poor"
    
    return {
        "reprojection_error": reprojection_error,
        "lane_width_std": width_std,
        "lane_width_consistency": width_consistency,
        "parallelism": parallelism,
        "score": score
    }
```

**视频回放验证**（可选）：

- 用户点击"运行回放验证"
- 系统提取后续 30 帧，使用 OpenCV 背景减除 + 轮廓检测做轻量车辆检测（不依赖 YOLO，避免引入 GPU 依赖）
- 对检测到的车辆 bbox 底边中心，用 H_mat 变换到 BEV 坐标，检查是否落在任一车道多边形内
- 输出车道匹配率（目标 > 80%），低于 80% 提示"建议微调标定"

**保存流程**：

1. 检查锁定状态（如果覆盖已有标定，需要先获取锁）
2. 生成版本号（当前版本 +1）
3. 写入 `calibration_db.json`（通过 `calib_store.py` 原子写入）
4. 更新版本历史（`version_manager.py` 记录变更）
5. 自动解锁

---

## 4. 管理面板

### 4.1 标定列表

**功能**：

- 表格展示所有标定记录：标定键、高度、俯仰角、质量评分、版本号、锁定状态
- 过滤：按质量状态（ok / interpolated / degraded）、路口 ID 搜索
- 操作：查看详情、锁定/解锁、删除（需确认）、回滚版本
- 导出：导出为 JSON/CSV

**标定键格式**：`{intersection_id}__H{altitude_bucket}__P{pitch_bucket}`

### 4.2 覆盖率热图

**功能**：

- 高度（Y 轴）× 俯仰角（X 轴）矩阵，每格 2m × 2°
- 颜色编码：
  - 绿色：有精确标定记录
  - 黄色：在插值范围内（距最近标定点 ≤4m / ≤4°）
  - 红色：未覆盖
  - 灰色：超出飞行包线（不可达）
- 点击格子显示该参数组合的标定详情或"未标定"
- 右侧统计面板：精确标定数、可插值数、未覆盖数、总覆盖率

### 4.3 版本历史

**功能**：

- 每条标定记录的版本时间线
- 每个版本显示：版本号、时间、操作人、变更摘要（如"调整 P3 坐标"、"新增车道 5"）
- 点击版本可查看详情（H_mat diff、车道多边形 diff）
- 支持回滚到任意历史版本

---

## 5. 核心模块设计

### 5.1 SRT 解析器（`core/srt_parser.py`）

```python
@dataclass
class SRTFrame:
    """SRT 文件中单帧遥测数据"""
    frame_index: int
    timestamp: float
    lat: float
    lon: float
    alt_agl: float
    gimbal_pitch: float
    gimbal_roll: float
    gimbal_yaw: float
    drone_pitch: float
    drone_roll: float
    drone_yaw: float
    gps_type: str  # RTK_FIXED / RTK_FLOAT / SINGLE
    satellite_count: int
    wind_speed: float
    battery_pct: int

def parse_srt_file(srt_path: str) -> list[SRTFrame]:
    """解析 DJI SRT 文件，返回逐帧遥测数据列表"""
    ...

def extract_frame_telemetry(srt_frames: list[SRTFrame], frame_index: int, 
                             intersection_id: str) -> dict:
    """提取指定帧的遥测数据，格式化为 DroneTelemetry 兼容格式"""
    ...
```

### 5.2 标定存储（`storage/calib_store.py`）

```python
class CalibStore:
    """calibration_db.json 的 CRUD 操作层"""
    
    def __init__(self, db_path: str = "configs/calibration_db.json"):
        self.db_path = db_path
        self._lock = threading.Lock()  # 文件级写锁
    
    def get(self, intersection_id: str, calib_key: str) -> dict | None:
        """获取单条标定记录"""
        ...
    
    def list_all(self, intersection_id: str | None = None, 
                 quality: str | None = None) -> list[dict]:
        """查询标定列表，支持过滤"""
        ...
    
    def save(self, intersection_id: str, calib_key: str, data: dict, 
             user: str) -> dict:
        """保存标定记录（原子写入），自动管理版本"""
        ...
    
    def delete(self, intersection_id: str, calib_key: str) -> bool:
        """删除标定记录"""
        ...
    
    def get_coverage(self, intersection_id: str) -> dict:
        """计算覆盖率热图数据"""
        ...
    
    def _atomic_write(self, data: dict):
        """原子写入：先写临时文件，再 rename"""
        ...
```

### 5.3 版本管理（`storage/version_manager.py`）

```python
class VersionManager:
    """标定记录版本管理"""
    
    MAX_VERSIONS = 10  # 保留最近 10 个版本
    
    def create_version(self, calib_data: dict, user: str, 
                       change_summary: str) -> dict:
        """创建新版本，返回版本信息"""
        ...
    
    def list_versions(self, calib_data: dict) -> list[dict]:
        """获取版本历史列表"""
        ...
    
    def get_version(self, calib_data: dict, version: int) -> dict | None:
        """获取指定版本的完整数据"""
        ...
    
    def rollback(self, calib_data: dict, target_version: int, 
                 user: str) -> dict:
        """回滚到指定版本，生成新版本"""
        ...
    
    def _prune_old_versions(self, versions: list) -> list:
        """修剪超出 MAX_VERSIONS 的旧版本"""
        ...
```

### 5.4 编辑锁（`storage/lock_manager.py`）

```python
class LockManager:
    """标定记录编辑锁管理"""
    
    LOCK_TTL_SECONDS = 1800  # 30 分钟自动释放
    
    def __init__(self):
        self._locks: dict[str, dict] = {}  # calib_key → lock_info
        self._lock = threading.Lock()
    
    def acquire(self, calib_key: str, user: str) -> dict:
        """
        获取编辑锁。
        返回 {"success": bool, "lock_info": {...}, "error": str | None}
        """
        ...
    
    def release(self, calib_key: str, user: str) -> bool:
        """释放编辑锁（只有锁持有者可以释放）"""
        ...
    
    def check(self, calib_key: str) -> dict | None:
        """检查锁定状态，返回锁信息或 None"""
        ...
    
    def cleanup_expired(self):
        """清理过期锁（定时调用或惰性清理）"""
        ...
```

### 5.5 先验模板引擎（`core/template_engine.py`）

```python
class TemplateEngine:
    """先验模板管理：标准车道配置"""
    
    DEFAULT_TEMPLATE = "standard_4lane"
    
    def __init__(self, templates_path: str = "annotation/configs/templates.json"):
        self.templates = self._load_templates(templates_path)
    
    def match_template(self, intersection_id: str, 
                       calib_store: "CalibStore") -> str:
        """
        匹配最佳模板。
        优先沿用同路口历史标定使用的模板，无历史则返回 DEFAULT_TEMPLATE。
        """
        ...
    
    def get_world_points(self, template_id: str) -> list[list[float]]:
        """获取模板的 4 个基准点世界坐标"""
        ...
    
    def get_lane_polygons(self, template_id: str) -> dict:
        """获取模板的车道多边形初始值"""
        ...
    
    def list_templates(self) -> list[dict]:
        """列出所有可用模板"""
        ...
```

---

## 6. 前端设计

### 6.1 全局样式

```css
/* static/css/main.css */
:root {
    --bg-primary: #1a202c;
    --bg-secondary: #2d3748;
    --bg-tertiary: #4a5568;
    --text-primary: #e2e8f0;
    --text-secondary: #a0aec0;
    --text-muted: #718096;
    --accent: #4fd1c5;
    --success: #48bb78;
    --warning: #ecc94b;
    --danger: #f56565;
    --info: #63b3ed;
    --border: #4a5568;
    --radius: 4px;
}
```

### 6.2 页面结构

**仪表盘首页** (`/`)：

- 顶部标题栏："无人机标定系统"
- 系统状态卡片：已标定路口数、覆盖率、最近操作时间
- 两个入口卡片：
  - "新路口标定"：大按钮，点击进入标定工作流
  - "标定管理"：大按钮，点击进入管理面板

**标定工作流** (`/calibrate`)：

- 顶部进度条：4 个步骤，当前步骤高亮
- 主体区域：根据当前步骤切换内容
- 底部按钮：上一步 / 下一步

**管理面板** (`/manage`)：

- Tab 栏：标定列表 / 覆盖率热图 / 版本历史
- 过滤栏：搜索框 + 状态过滤 + 导出按钮
- 主体区域：根据 Tab 切换内容

### 6.3 Konva.js 车道编辑器

```javascript
// static/js/lane-editor.js
class LaneEditor {
    constructor(containerId, worldScale = 10) {
        this.stage = new Konva.Stage({
            container: containerId,
            width: 800,
            height: 600
        });
        this.gridLayer = new Konva.Layer();  // 网格层
        this.laneLayer = new Konva.Layer();  // 车道多边形层
        this.handleLayer = new Konva.Layer(); // 顶点手柄层
        
        this.stage.add(this.gridLayer);
        this.stage.add(this.laneLayer);
        this.stage.add(this.handleLayer);
        
        this.lanes = {};       // lane_id → Konva.Line
        this.selectedLane = null;
        this.isDrawing = false;
        this.currentPoints = [];
        
        this._setupGrid();
        this._setupEvents();
    }
    
    // 开始绘制新车道
    startDrawing() { ... }
    
    // 添加顶点
    addVertex(x, y) { ... }
    
    // 闭合多边形
    closePolygon() { ... }
    
    // 选中车道
    selectLane(laneId) { ... }
    
    // 删除选中车道
    deleteSelected() { ... }
    
    // 导出车道数据
    exportLanes() {
        // 返回 {lane_id: [[x1,y1], [x2,y2], ...]} 格式
        ...
    }
    
    // 导入车道数据
    importLanes(laneData) { ... }
    
    // 世界坐标 → 画布坐标
    worldToCanvas(wx, wy) { ... }
    
    // 画布坐标 → 世界坐标
    canvasToWorld(cx, cy) { ... }
    
    // 网格对齐
    snapToGrid(x, y) { ... }
}
```

---

## 7. 部署方案

### 7.1 独立启动（开发/演示）

```bash
# 在项目根目录
cd annotation
python app.py --port 5000 --db ../configs/calibration_db.json
```

### 7.2 Docker 集成（生产）

```yaml
# docker-compose.drone.yml 新增
services:
  annotation_tool:
    build:
      context: ./annotation
      dockerfile: Dockerfile
    ports:
      - "5001:5000"
    volumes:
      - ./configs:/app/configs          # 共享标定数据库
      - ./flights:/app/flights:ro       # 飞行数据只读挂载
    environment:
      - CALIB_DB_PATH=/app/configs/calibration_db.json
      - FLIGHTS_DIR=/app/flights
```

### 7.3 Nginx 反代（可选）

```nginx
# 在现有 nginx.conf 中添加
location /annotation/ {
    proxy_pass http://annotation_tool:5000/;
    proxy_set_header Host $host;
}
```

---

## 8. 与管道的集成

### 8.1 数据流

```
标注工具 → 写入 configs/calibration_db.json
                ↓
管道启动时 → CalibrationEngine 加载 calibration_db.json
                ↓
每帧 → SRT 遥测 → calib_key → 查表 → H_mat + lane_polygons_bev
```

### 8.2 热更新

- 标注工具保存标定后，写入 `calibration_db.json`
- 管道的 `CalibrationEngine` 通过文件 mtime 检测变更，自动重新加载
- 无需重启管道进程

### 8.3 格式兼容

标注工具输出的 `calibration_db.json` 格式必须与 `docs/无人机交通态势监测_POC规划_v1.0.md` §5.1.1 定义的结构完全一致：

```json
{
    "calibration_db": {
        "{intersection_id}": {
            "{calib_key}": {
                "H_mat": [[h11,h12,h13],[h21,h22,h23],[h31,h32,h33]],
                "altitude_agl": 163.4,
                "gimbal_pitch": -90.0,
                "output_size": [1280, 720],
                "pixel_scale": 0.05,
                "lane_polygons_bev": {
                    "1": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                },
                "quality": {
                    "reprojection_error": 2.3,
                    "lane_width_std": 0.12,
                    "parallelism": 0.98,
                    "score": "excellent"
                },
                "source_points": {
                    "pixel": [[u1,v1],[u2,v2],[u3,v3],[u4,v4]],
                    "world": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                },
                "template": "standard_4lane",
                "versions": [...],
                "lock": null,
                "calibrated_at": "2026-04-03T14:29:00Z",
                "calibrated_by": "admin",
                "source_flight": "..."
            }
        }
    }
}
```

---

## 9. 验证方案

### 9.1 单元测试

| 模块 | 测试内容 |
|---|---|
| `srt_parser.py` | 解析已知 SRT 文件，验证字段提取正确性 |
| `homography.py` | 已知 4 组对应点，验证 H_mat 计算 + 重投影误差 |
| `quality_scorer.py` | 构造不同质量的标定数据，验证评分逻辑 |
| `calib_store.py` | CRUD 操作、并发写入、原子性 |
| `lock_manager.py` | 锁定/解锁/过期/冲突检测 |
| `version_manager.py` | 版本创建/回滚/修剪 |

### 9.2 集成测试

1. 启动标注工具，打开浏览器
2. 上传小清河路口视频帧 + SRT 文件
3. 完成 4 步标定工作流
4. 验证 `calibration_db.json` 文件内容正确
5. 在管理面板查看新标定记录
6. 锁定记录，尝试编辑（应被拒绝）
7. 回滚版本，验证数据恢复

### 9.3 CTO 演示验证

1. 打开标注工具首页，展示系统状态
2. 点击"新路口标定"，进入工作流
3. 上传小清河视频帧，SRT 数据自动填充
4. 现场点击 4 个基准点，BEV 预览实时更新
5. 绘制 5 条车道多边形
6. 展示质量评分：重投影误差 2.3px，综合评分"优秀"
7. 保存，切换到管理面板展示覆盖率热图
8. 全程计时 < 5 分钟

---

## 附录 A：templates.json 完整内容

```json
{
    "templates": {
        "standard_4lane": {
            "description": "标准四车道（3.5m/车道）",
            "lane_count": 4,
            "lane_width_m": 3.5,
            "road_length_m": 50.0,
            "world_points": [[0.0, 0.0], [14.0, 0.0], [0.0, 50.0], [14.0, 50.0]],
            "lane_polygons_bev": {
                "1": [[0.0, 0.0], [3.5, 0.0], [3.5, 50.0], [0.0, 50.0]],
                "2": [[3.5, 0.0], [7.0, 0.0], [7.0, 50.0], [3.5, 50.0]],
                "3": [[7.0, 0.0], [10.5, 0.0], [10.5, 50.0], [7.0, 50.0]],
                "4": [[10.5, 0.0], [14.0, 0.0], [14.0, 50.0], [10.5, 50.0]]
            }
        },
        "standard_5lane": {
            "description": "标准五车道（3.5m/车道）",
            "lane_count": 5,
            "lane_width_m": 3.5,
            "road_length_m": 50.0,
            "world_points": [[0.0, 0.0], [17.5, 0.0], [0.0, 50.0], [17.5, 50.0]],
            "lane_polygons_bev": {
                "1": [[0.0, 0.0], [3.5, 0.0], [3.5, 50.0], [0.0, 50.0]],
                "2": [[3.5, 0.0], [7.0, 0.0], [7.0, 50.0], [3.5, 50.0]],
                "3": [[7.0, 0.0], [10.5, 0.0], [10.5, 50.0], [7.0, 50.0]],
                "4": [[10.5, 0.0], [14.0, 0.0], [14.0, 50.0], [10.5, 50.0]],
                "5": [[14.0, 0.0], [17.5, 0.0], [17.5, 50.0], [14.0, 50.0]]
            }
        },
        "wide_4lane": {
            "description": "宽幅四车道（3.75m/车道）",
            "lane_count": 4,
            "lane_width_m": 3.75,
            "road_length_m": 50.0,
            "world_points": [[0.0, 0.0], [15.0, 0.0], [0.0, 50.0], [15.0, 50.0]],
            "lane_polygons_bev": {
                "1": [[0.0, 0.0], [3.75, 0.0], [3.75, 50.0], [0.0, 50.0]],
                "2": [[3.75, 0.0], [7.5, 0.0], [7.5, 50.0], [3.75, 50.0]],
                "3": [[7.5, 0.0], [11.25, 0.0], [11.25, 50.0], [7.5, 50.0]],
                "4": [[11.25, 0.0], [15.0, 0.0], [15.0, 50.0], [11.25, 50.0]]
            }
        }
    }
}
```

## 附录 B：SRT 文件格式参考

DJI SRT 文件是字幕格式，每帧数据如下：

```
1
00:00:00,000 --> 00:00:00,033
F/2.8, SS 129.81, ISO 100, EV 0, GPS (36.7029, 117.0223, 163), BARO 163.4, H-S: 9.3, H: 163.4, D 45.00, H.S [0.0, 0.0, 0.0], G.P [67.00, 32.00, 0.00], E.P [0.00, 0.00, -90.00], A [4.10, 0.30, -19.30], F.PRY [0.5°, 0.3°, -44.7°], S.PRY [0.0°, 0.0°, -44.8°]
```

**关键字段解析**：

| 字段 | 含义 | 示例值 |
|---|---|---|
| GPS (lat, lon, alt) | WGS84 坐标 + 海拔 | (36.7029, 117.0223, 163) |
| BARO | 气压计高度（≈AGL） | 163.4 |
| H-S | 水平速度 m/s | 9.3 |
| G.PRY | 云台 Pitch/Roll/Yaw | [67.00, 32.00, 0.00] |
| E.PRY | 云台相对机体角 | [0.00, 0.00, -90.00] |
| A | 机体加速度 | [4.10, 0.30, -19.30] |
| F.PRY | 机体姿态角 | [0.5°, 0.3°, -44.7°] |
