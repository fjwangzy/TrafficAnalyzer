# 四维图新 MineMap 基本用法

本项目的用法：加载 MineMap SDK → 配置地图服务 → 创建地图 → 添加设备点位 → 点击点位打开详情。

## 1. 加载 SDK 和样式

项目使用 SDK 2.1.0，通过网页加载，不需要安装 npm 地图包。

```html
<link rel="stylesheet" href="http://37.8.188.98:21009/minemapapi/v2.1.0/minemap.css">
<script src="http://37.8.188.98:21009/minemapapi/v2.1.0/minemap.js"></script>
<div id="map" style="width: 100%; height: 500px;"></div>
```

## 2. 配置服务并创建地图

在 SDK 加载完成、地图容器创建之后执行：

```js
const domain = 'http://37.8.188.98:21009';
const solution = '17000';

minemap.domainUrl = domain;
minemap.dataDomainUrl = domain;
minemap.serverDomainUrl = domain;
minemap.spriteUrl = `${domain}/minemapapi/v2.1.0/sprite/sprite`;
minemap.serviceUrl = `${domain}/service`;
minemap.accessToken = '填写你的 MineMap Key';
minemap.solution = solution;

const map = new minemap.Map({
  container: 'map',
  style: `${domain}/service/solu/style/id/${solution}`,
  center: [117.0, 36.65], // 经度、纬度
  zoom: 10,
});
```

服务地址、Key 和方案 ID 要对应；浏览器需要能访问该地图服务。

## 3. 添加点位并响应点击

在地图加载完成后添加 GeoJSON 数据和圆点图层：

```js
map.on('load', () => {
  map.addSource('devices', {
    type: 'geojson',
    data: {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [117.006, 36.65] },
        properties: { id: '001', name: '设备 A', status: 'warning' },
      }],
    },
  });

  map.addLayer({
    id: 'device-points',
    type: 'circle',
    source: 'devices',
    paint: {
      'circle-radius': 7,
      'circle-color': ['match', ['get', 'status'], 'warning', '#ff7043', '#66bb6a'],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  });

  map.on('click', 'device-points', (event) => {
    const device = event.features?.[0]?.properties;
    if (device) console.log('点击设备：', device.id, device.name);
    // 在这里打开设备详情。
  });
});
```

示例点位按 GCJ02 输入。本项目接口原始坐标为 WGS84，会先转换为 GCJ02 再画点；已有 GCJ02 坐标不用重复转换。增加设备时，继续向 `features` 数组添加数据即可。

## 4. 更新和销毁

```js
// newGeoJSON 是与上面结构一致的 FeatureCollection。
map.getSource('devices').setData(newGeoJSON);

// 容器尺寸改变后调用。
map.resize();

// 页面退出时销毁。
map.remove();
```

项目中的 Vue 组件已经封装了这些操作：父页面传入点位数组，组件负责画点，点击后回传设备 ID。
