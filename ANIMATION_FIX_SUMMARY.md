# CoverBackground 动画错误修复报告

## 🐛 问题描述
```
Gesture direction: 8
Gesture DOWN detected
13072000 trezor.loop ERROR exception:
Traceback (most recent call last):
  File "trezor/loop.py", line 214, in _step
  File "trezor/lvglui/__init__.py", line 17, in lvgl_tick
  File "trezor/lvglui/scrs/homescreen.py", line 381, in <lambda>
AttributeError: 'lv_timer_t' object has no attribute 'delete'
```

## 🔧 错误原因
原代码使用了错误的定时器删除方法：
```python
# 错误的方法
lv.timer_create(lambda timer: (
    self.show_opacity_anim.start(),
    timer.delete()  # ❌ lv_timer_t 没有 delete() 方法
), 30, None)
```

## ✅ 修复方案

### 方案1: 使用正确的API
```python
def delayed_opacity_start(timer):
    self.show_opacity_anim.start()
    lv.timer_del(timer)  # ✅ 正确的LVGL API

delay_timer = lv.timer_create(delayed_opacity_start, 30, None)
lv.timer_set_repeat_count(delay_timer, 1)  # 只执行一次
```

### 方案2: 使用Anim内置延迟 (推荐)
```python
# 使用Anim类的内置delay参数
self.show_opacity_anim = Anim(
    0, 255, self.set_opacity,
    time=250,
    path_cb=lv.anim_t.path_ease_out,
    delay=30  # ✅ 内置延迟，更安全
)

def show_with_animation(self):
    if device.is_animation_enabled():
        self.show_move_anim.start()
        self.show_opacity_anim.start()  # 有30ms内置延迟
```

## 📋 修复内容

1. **移除错误的定时器处理**
2. **使用Anim类的delay参数**
3. **简化动画启动逻辑**
4. **保持分层动画效果**

## 🎯 最终实现

```python
# 优化后的动画定义
self.show_opacity_anim = Anim(
    0, 255, self.set_opacity,
    time=250, path_cb=lv.anim_t.path_ease_out,
    delay=30  # 延迟30ms启动
)

self.show_move_anim = Anim(
    -60, 0, self.set_y_offset,
    time=220, path_cb=lv.anim_t.path_overshoot
)

# 简化的动画启动
def show_with_animation(self):
    if device.is_animation_enabled():
        self.show_move_anim.start()      # 立即启动移动
        self.show_opacity_anim.start()   # 30ms后启动透明度
    else:
        self.set_opacity(255)
        self.set_y_offset(0)
```

## 🔍 验证方法

1. 编译固件：`cd core && poetry run make build_unix`
2. 启动模拟器：`poetry run ./emu.py`
3. 测试手势：向下滑动触发CoverBackground动画
4. 检查控制台：确认无错误输出

## 📊 修复效果

- ✅ 消除 AttributeError 异常
- ✅ 保持分层动画效果
- ✅ 简化代码复杂度
- ✅ 提高稳定性

---
*修复日期: 2025-06-23*
*错误类型: AttributeError - 错误的LVGL API调用*