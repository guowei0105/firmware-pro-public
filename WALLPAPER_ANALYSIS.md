# 壁纸、滑动、自定义模块代码分析报告

## 一、目录结构概览

### 1. 主要源文件位置
- **壁纸页面实现**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/lvglui/scrs/homescreen.py`
- **NFT及自定义模块**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/lvglui/scrs/nftmanager.py`
- **列表项组件**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/lvglui/scrs/components/listitem.py`
- **图片上传处理**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/apps/management/upload_res.py`
- **滑动组件**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/ui/components/tt/scroll.py`

### 2. 资源目录
- **内置壁纸**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/lvglui/res/`
- **自定义壁纸**: `/home/zhou/Desktop/format_pro_0828/firmware-pro/core/src/trezor/lvglui/assets/sys/wallpaper/`

---

## 二、壁纸页面实现详解

### 2.1 核心类结构

#### WallpaperScreen (第6010行)
**职责**: 壁纸功能的主入口屏幕

```python
class WallpaperScreen(AnimScreen):
    def __init__(self, prev_scr=None):
        # 创建两个主要选项:
        # 1. 锁屏壁纸设置
        # 2. 首页壁纸设置
        self.lock_screen = ListItemBtn(...)
        self.home_screen = ListItemBtn(...)
```

**关键特性**:
- 继承自`AnimScreen`
- 提供锁屏壁纸和首页壁纸两个入口
- 事件处理在`on_click_event`方法

#### HomeScreenSetting (第6101行)
**职责**: 首页壁纸预览和配置

```python
class HomeScreenSetting(AnimScreen):
    def __init__(self, prev_scr=None, selected_wallpaper=None, preserve_blur_state=None):
        # 创建预览容器 (344x572)
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 572)
        
        # 创建预览图像
        self.homescreen_preview = lv.img(self.preview_container)
        
        # 计算缩放比例
        base_width, base_height = 480, 800
        zoom_x = math.ceil((344 / base_width) * 256)  # 344/480 * 256
        zoom_y = math.ceil((572 / base_height) * 256) # 572/800 * 256
        zoom = max(int(zoom_x), int(zoom_y))
        self.homescreen_preview.set_zoom(zoom)
```

**关键特性**:
- 预览容器固定为344x572像素
- 使用缩放(zoom)而非直接调整大小以避免像素变形
- 支持模糊(blur)状态保存和恢复
- 有4个应用图标覆盖层显示

#### WallperChange (第3820行)
**职责**: 壁纸选择和管理

```python
class WallperChange(AnimScreen):
    def __init__(self, prev_scr=None):
        # 内置壁纸 (7个)
        for i in range(7):
            file_name = f"zoom-wallpaper-{i+1}.jpg"
            current_wp = ImgGridItem(...)
        
        # 自定义壁纸 (最多5个)
        for file_name in custom_file_names[:5]:
            zoom_file_name = f"zoom-{file_name}"
            current_wp = ImgGridItem(...)
```

**网格布局**:
- 3列网格布局
- 自定义壁纸在上方(可选)
- 内置壁纸集合在下方
- 支持编辑模式(删除、选择)

---

## 三、图片加载和缩放逻辑

### 3.1 ImgGridItem 类 (listitem.py 第273行)

**核心概念**: 使用"zoom-"前缀的缩小版本作为缩略图显示

```python
class ImgGridItem(lv.img):
    def __init__(self, parent, col_num, row_num, file_name: str, path_dir: str,
                 img_path_selected=None, is_internal=False, style_type="wallpaper"):
        
        # 路径处理
        self.zoom_path = path_dir + file_name  # e.g., "A:/res/zoom-wallpaper-1.jpg"
        self.img_path = self.zoom_path.replace("zoom-", "")  # e.g., "A:/res/wallpaper-1.jpg"
        
        # 设置图像源
        self.set_src(self.zoom_path)
        
        # 缩放设置 (256 = 100%)
        self.set_zoom(256)  # 默认100%缩放
        self.set_antialias(True)  # 启用抗锯齿
```

### 3.2 缩放比例计算

#### 对于WallpaperPreviewBase (nftmanager.py 第125-130行)
```python
def _create_preview_image(self, image_path):
    base_width, base_height = 480, 800
    zoom_x = int((344 / base_width) * 256)  # int(0.71458 * 256) = 182
    zoom_y = int((574 / base_height) * 256) # int(0.715 * 256) = 182
    zoom = min(zoom_x, zoom_y)  # 取较小值以实现"fit"策略
    self.preview_image.set_zoom(zoom)
```

#### 对于HomeScreenSetting (homescreen.py 第6240-6244行)
```python
# 使用"cover"策略覆盖整个容器
base_width, base_height = 480, 800
zoom_x = math.ceil((344 / base_width) * 256)  # math.ceil(182) = 182
zoom_y = math.ceil((572 / base_height) * 256) # math.ceil(182) = 182
zoom = max(int(zoom_x), int(zoom_y))  # 取较大值以覆盖整个容器
self.homescreen_preview.set_zoom(zoom)
```

### 3.3 样式应用

#### 壁纸缩略图样式 (listitem.py 第353-372行)
```python
def _setup_styles(self):
    if self.style_type == "nft":
        # NFT风格: 正方形238x238，圆角8
        self.set_size(238, 238)
        self.set_style_radius(8, 0)
        self.set_style_clip_corner(False, 0)
    else:
        # 壁纸风格: 不强制大小，只设置圆角40
        self.set_style_radius(40, 0)
        self.set_style_clip_corner(False, 0)
    
    # 公共样式
    self.set_style_bg_opa(lv.OPA.TRANSP, 0)  # 透明背景
    self.set_style_img_opa(lv.OPA.COVER, 0)  # 完全不透明的图像
    self.set_style_img_recolor_opa(lv.OPA.TRANSP, 0)  # 无颜色覆盖
```

---

## 四、滑动事件处理

### 4.1 LVGL滑动事件类型
```python
# 在homescreen.py中识别的滑动事件:
lv.EVENT.SCROLL_BEGIN    # 滑动开始
lv.EVENT.SCROLL         # 滑动进行中
lv.EVENT.SCROLL_END     # 滑动结束
lv.EVENT.CLICKED        # 点击事件 (在滑动后不触发)
```

### 4.2 容器滑动配置

#### WallperChange中的容器设置 (第3914-3923行)
```python
self.container = ContainerGrid(
    self.content_area,
    row_dsc=row_dsc,      # 行描述 (自动计算)
    col_dsc=col_dsc,      # 3列固定宽度
    pad_gap=12,           # 12px间距
)

# 启用事件冒泡
self.container.add_flag(lv.obj.FLAG.EVENT_BUBBLE)

# 添加点击事件处理器
self.container.add_event_cb(self.on_click, lv.EVENT.CLICKED, None)
```

### 4.3 滑动禁用示例

#### HomeScreenSetting预览容器 (第6200-6202行)
```python
self.preview_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
self.preview_container.clear_flag(lv.obj.FLAG.SCROLLABLE)
```

这防止了预览区域的滑动，只允许用户进行点击交互。

---

## 五、自定义模块的图片展示逻辑

### 5.1 自定义壁纸存储结构

**目录**: `1:/res/wallpapers/` (设备存储)

**文件命名规则**:
```
wp-{hash}-{timestamp}.jpeg         # 原始图像
zoom-wp-{hash}-{timestamp}.jpeg    # 缩小版本 (用于缩略图)
wp-{hash}-{timestamp}-blur.jpeg    # 模糊版本
zoom-wp-{hash}-{timestamp}-blur.jpeg # 模糊缩小版本
```

**示例**:
```
wp-abc123-1609459200.jpeg
zoom-wp-abc123-1609459200.jpeg
wp-abc123-1609459200-blur.jpeg
zoom-wp-abc123-1609459200-blur.jpeg
```

### 5.2 自定义壁纸加载流程 (第3845-3880行)

```python
def __init__(self, prev_scr=None):
    # 1. 列出目录
    for size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):
        if (size > 0 and name.startswith("wp-") and 
            not name.endswith("-blur.jpeg") and 
            not name.endswith("-blur.jpg")):
            file_name_list.append(name)
    
    # 2. 按时间戳排序 (最新的优先)
    def extract_timestamp(filename):
        parts = filename.rsplit("-", 1)  # 从右分割: "wp-abc123" 和 "1609459200.jpeg"
        timestamp_str = parts[1].split(".")[0]
        return int(timestamp_str)
    
    file_name_list.sort(key=extract_timestamp, reverse=True)
    
    # 3. 限制到5个最新的
    file_name_list = file_name_list[:5]
    
    # 4. 创建网格项
    for i, file_name in enumerate(file_name_list):
        zoom_file_name = f"zoom-{file_name}"
        current_wp = ImgGridItem(
            self.container,
            i % 3,                              # 列 (0-2)
            current_row + (i // 3),             # 行
            zoom_file_name,                     # 使用缩小版本
            "A:1:/res/wallpapers/",             # 路径
            img_path_unselected=None,
            is_internal=True,
            style_type="wallpaper",
        )
```

### 5.3 自定义壁纸编辑模式

#### 编辑模式界面 (第3951-4034行)

```python
if file_name_list:
    # 编辑按钮 (显示)
    self.edit_button = lv.btn(self.custom_header_container)
    
    # 完成按钮 (隐藏, 编辑模式显示)
    self.done_button = lv.btn(self.custom_header_container)
    self.done_button.add_flag(lv.obj.FLAG.HIDDEN)
    
    # 删除按钮 (隐藏, 编辑模式显示)
    self.delete_button = lv.btn(self.custom_header_container)
    self.delete_button.add_flag(lv.obj.FLAG.HIDDEN)
```

#### 选择和删除逻辑 (第4067-4101行)

```python
# 为每个自定义壁纸创建选择复选框
selection_checkbox = lv.btn(current_wp)
selection_checkbox.set_size(32, 32)
selection_checkbox.add_flag(lv.obj.FLAG.HIDDEN)  # 初始隐藏

selection_checkbox.align(lv.ALIGN.TOP_RIGHT, -12, 12)  # 右上角

# 删除按钮
remove_icon = lv.btn(current_wp)
remove_icon.set_size(44, 44)
remove_icon.add_flag(lv.obj.FLAG.HIDDEN)  # 初始隐藏
```

### 5.4 删除确认流程 (第4528-4550行)

```python
def on_delete_button_clicked(self, event_obj):
    # 收集标记的壁纸
    wallpapers_to_delete = self.selected_wallpapers
    
    if wallpapers_to_delete:
        # 删除前的验证
        for wp in wallpapers_to_delete:
            # 检查是否在使用
            if wp.img_path == current_wallpaper:
                # 返回错误信息
                return
            
            # 删除文件
            try:
                io.fatfs.unlink(f"A:1:/res/wallpapers/{wp._original_file}")
                io.fatfs.unlink(f"A:1:/res/wallpapers/zoom-{wp._original_file}")
            except Exception:
                pass
```

---

## 六、图片上传处理 (upload_res.py)

### 6.1 上传流程概览

```python
async def upload_res(ctx: wire.Context, msg: ResourceUpload) -> Success:
    # 1. 验证资源类型和大小
    # 2. 检查文件冲突
    # 3. 分块上传原始图像
    # 4. 分块上传缩小版本
    # 5. 分块上传模糊版本 (可选)
    # 6. 处理旧文件替换逻辑
```

### 6.2 文件路径和分块配置 (第280-291行)

```python
REQUEST_CHUNK_SIZE = const(8 * 1024)  # 8KB块大小 (必须 <= wire buffer)

if res_type == ResourceType.WallPaper:
    file_full_path = f"1:/res/wallpapers/{file_name}.{res_ext}"
    zoom_path = f"1:/res/wallpapers/zoom-{file_name}.{res_ext}"
    if res_blur_size > 0:
        blur_path = f"1:/res/wallpapers/{file_name}-blur.{res_ext}"
else:  # NFT
    file_full_path = f"1:/res/nfts/imgs/{file_name}.{res_ext}"
    zoom_path = f"1:/res/nfts/zooms/zoom-{file_name}.{res_ext}"
    config_path = f"1:/res/nfts/desc/{file_name}.json"
```

### 6.3 分块上传实现 (第294-324行)

```python
with io.fatfs.open(file_full_path, "w") as f:
    data_left = res_size
    offset = 0
    
    while data_left > 0:
        chunk_size = min(REQUEST_CHUNK_SIZE, data_left)
        request = ResourceRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
        ack: ResourceAck = await ctx.call(request, ResourceAck)
        
        # 验证数据完整性
        digest = blake2s(ack.data_chunk).digest()
        if digest != ack.hash:
            raise wire.DataError("Data digest is inconsistent")
        
        f.write(ack.data_chunk)
        offset += chunk_size
        data_left -= REQUEST_CHUNK_SIZE
    
    f.sync()  # 强制刷新到磁盘
```

### 6.4 内存管理和垃圾回收 (第150-170行)

```python
# LVGL图像缓存清理
try:
    from trezor.lvglui.scrs.common import lv
    lv.img_cache_invalidate_src(None)  # 清空所有缓存
except Exception:
    pass

# 清理Python端缓存
try:
    from trezor.lvglui.scrs import homescreen
    if hasattr(homescreen, '_cached_styles'):
        homescreen._cached_styles.clear()
    if hasattr(homescreen, '_last_jpeg_loaded'):
        homescreen._last_jpeg_loaded = None
except Exception:
    pass

# 积极的垃圾回收
import gc
for i in range(3):
    gc.collect()
```

---

## 七、模糊效果(Blur)实现

### 7.1 模糊状态管理 (homescreen.py 第6500-6550行)

```python
def _get_blur_wallpaper_path(self, original_path):
    """获取对应的模糊版本路径"""
    if "-blur" in original_path:
        return original_path  # 已经是模糊版本
    
    # 添加-blur后缀
    path_parts = original_path.rsplit(".", 1)
    return f"{path_parts[0]}-blur.{path_parts[1]}"

def _blur_wallpaper_exists(self, blur_path):
    """检查模糊版本是否存在"""
    try:
        io.fatfs.stat(blur_path)
        return True
    except:
        return False
```

### 7.2 模糊按钮状态更新 (第6600-6650行)

```python
def _update_blur_button_state(self):
    """更新模糊按钮的视觉状态"""
    blur_available = (
        hasattr(self, "blur_button") and
        self._blur_wallpaper_exists(
            self._get_blur_wallpaper_path(self.original_wallpaper_path)
        )
    )
    
    if blur_available:
        if self.is_blur_active:
            # 显示"已启用"状态
            self.blur_button_icon.set_src("A:/res/blur_selected.png")
        else:
            # 显示"可用"状态
            self.blur_button_icon.set_src("A:/res/blur_no_selected.png")
    else:
        # 显示"不可用"状态
        self.blur_button_icon.set_src("A:/res/blur_not_available.png")
```

---

## 八、NFT管理器集成

### 8.1 WallpaperPreviewBase类 (nftmanager.py 第74-134行)

```python
class WallpaperPreviewBase(AnimScreen):
    """用于NFT和自定义壁纸预览的基类"""
    
    def _create_preview_container(self, top_offset=118):
        # 创建344x574的预览容器
        self.preview_container = lv.obj(self.container)
        self.preview_container.set_size(344, 574)
        self.preview_container.align(lv.ALIGN.TOP_MID, 0, top_offset)
        self.preview_container.set_style_clip_corner(True, 0)  # 启用角裁剪
    
    def _create_preview_image(self, image_path):
        # 计算缩放比例(fit策略)
        zoom = min(zoom_x, zoom_y)
        self.preview_image.set_zoom(zoom)
```

### 8.2 NFT特定配置 (nftmanager.py 第28-40行)

```python
# 路径常量以减少QSTR使用
_P1 = "1:/res/nfts/zooms"
_P2 = "1:/res/nfts/imgs/"
_P3 = "1:/res/nfts/desc/"
_P4 = "A:1:/res/nfts/zooms/"
_P5 = "A:1:/res/nfts/imgs/"

# NFT元数据验证
NFT_METADATA_ALLOWED_KEYS = ("header", "subheader", "network", "owner")
```

---

## 九、关键技术细节

### 9.1 缩放常数
- **256** = 100% (LVGL标准)
- **512** = 200% (放大)
- **128** = 50% (缩小)

### 9.2 容器大小
- **预览容器**: 344x574 (或344x572)
- **NFT网格项**: 238x238
- **按钮大小**: 64x64

### 9.3 性能优化
1. **图像缓存禁用** (custom_wp.set_src_cache_enabled(False))
2. **批量垃圾回收** (多次gc.collect())
3. **块大小限制** (8KB = wire buffer大小)
4. **lazy loading** (异步加载)

### 9.4 内存管理
- JPEG解码器状态保存
- 显示层2隐藏 (cover_background_hide)
- LVGL图像缓存清理
- Python端缓存清理

---

## 十、文件对应关系总结

| 功能模块 | 主要文件 | 关键类 | 行数 |
|---------|--------|--------|------|
| 壁纸主界面 | homescreen.py | WallpaperScreen | 6010 |
| 首页壁纸设置 | homescreen.py | HomeScreenSetting | 6101 |
| 壁纸选择 | homescreen.py | WallperChange | 3820 |
| 网格项组件 | listitem.py | ImgGridItem | 273 |
| NFT管理 | nftmanager.py | WallpaperPreviewBase | 74 |
| 图片上传 | upload_res.py | upload_res | 64 |
| 滑动组件 | scroll.py | Paginated | 64 |

---

## 十一、代码质量观察

### 优点
1. ✓ 清晰的类层次结构
2. ✓ 优异的内存管理策略
3. ✓ 完善的错误处理
4. ✓ 详细的代码注释
5. ✓ 一致的命名约定

### 需要注意的地方
1. ⚠ 复杂的缩放计算逻辑 (ceil vs min/max)
2. ⚠ 大量的条件判断 (edit_mode检查)
3. ⚠ 文件命名规范严格 (wp-, zoom-, -blur后缀)

