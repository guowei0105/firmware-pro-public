"""
AppDrawer 预渲染优化模块
提供双缓冲、页面缓存和预渲染功能，提升滑动动画流畅度
"""

import gc
import lv
from micropython import const

try:
    import utime
    get_time_ms = lambda: utime.ticks_ms()
except:
    get_time_ms = lambda: 0

# 预渲染配置
PRERENDER_ENABLED = const(1)  # 启用预渲染
CACHE_SIZE = const(2)  # 缓存页面数量
CACHE_EXPIRY_MS = const(30000)  # 缓存过期时间 30秒
PRERENDER_DELAY_MS = const(50)  # 预渲染延迟，避免影响当前动画

class PageCache:
    """页面缓存管理器"""
    def __init__(self, max_size=CACHE_SIZE):
        self.max_size = max_size
        self.cache = {}  # {page_index: {'buffer': lv.obj, 'timestamp': ms, 'hit_count': int}}
        self.render_queue = []  # 待渲染队列
        
    def get(self, page_index):
        """获取缓存的页面"""
        if page_index in self.cache:
            entry = self.cache[page_index]
            current_time = get_time_ms()
            
            # 检查缓存是否过期
            if current_time - entry['timestamp'] < CACHE_EXPIRY_MS:
                entry['hit_count'] += 1
                if __debug__:
                    print(f"PageCache: Hit for page {page_index}, hit_count={entry['hit_count']}")
                return entry['buffer']
            else:
                # 缓存过期，清理
                if __debug__:
                    print(f"PageCache: Expired cache for page {page_index}")
                self._evict(page_index)
        return None
        
    def put(self, page_index, buffer):
        """存储页面到缓存"""
        # 如果缓存满了，淘汰最少使用的
        if len(self.cache) >= self.max_size and page_index not in self.cache:
            self._evict_lru()
            
        self.cache[page_index] = {
            'buffer': buffer,
            'timestamp': get_time_ms(),
            'hit_count': 0
        }
        if __debug__:
            print(f"PageCache: Cached page {page_index}")
            
    def _evict(self, page_index):
        """移除指定页面缓存"""
        if page_index in self.cache:
            entry = self.cache[page_index]
            # 清理 LVGL 对象
            if entry['buffer'] and hasattr(entry['buffer'], 'del_'):
                try:
                    entry['buffer'].del_()
                except:
                    pass
            del self.cache[page_index]
            gc.collect()
            
    def _evict_lru(self):
        """淘汰最少使用的缓存"""
        if not self.cache:
            return
            
        # 找到 hit_count 最小的
        min_page = min(self.cache.keys(), 
                      key=lambda k: self.cache[k]['hit_count'])
        if __debug__:
            print(f"PageCache: Evicting LRU page {min_page}")
        self._evict(min_page)
        
    def clear(self):
        """清空所有缓存"""
        for page_index in list(self.cache.keys()):
            self._evict(page_index)
        self.render_queue.clear()


class DoubleBuffer:
    """双缓冲管理器"""
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.front_buffer = None
        self.back_buffer = None
        self.is_swapped = False
        
    def init_buffers(self, parent):
        """初始化前后缓冲区"""
        # 创建前缓冲区（当前显示）
        self.front_buffer = lv.obj(parent)
        self.front_buffer.set_size(self.width, self.height)
        self.front_buffer.set_pos(0, 0)
        self.front_buffer.add_style(
            self._create_transparent_style(), 0
        )
        self.front_buffer.clear_flag(lv.obj.FLAG.SCROLLABLE)
        
        # 创建后缓冲区（预渲染）
        self.back_buffer = lv.obj(parent)
        self.back_buffer.set_size(self.width, self.height)
        self.back_buffer.set_pos(0, 0)
        self.back_buffer.add_style(
            self._create_transparent_style(), 0
        )
        self.back_buffer.add_flag(lv.obj.FLAG.HIDDEN)
        self.back_buffer.clear_flag(lv.obj.FLAG.SCROLLABLE)
        
    def _create_transparent_style(self):
        """创建透明样式"""
        from ..scrs.widgets.style import StyleWrapper
        return StyleWrapper().bg_opa(lv.OPA.TRANSP).border_width(0).pad_all(0)
        
    def swap(self):
        """交换前后缓冲区"""
        # 快速交换引用
        self.front_buffer, self.back_buffer = self.back_buffer, self.front_buffer
        
        # 更新可见性
        self.front_buffer.clear_flag(lv.obj.FLAG.HIDDEN)
        self.back_buffer.add_flag(lv.obj.FLAG.HIDDEN)
        
        self.is_swapped = not self.is_swapped
        if __debug__:
            print(f"DoubleBuffer: Swapped buffers")
            
    def get_render_buffer(self):
        """获取用于渲染的缓冲区（后缓冲）"""
        return self.back_buffer
        
    def get_display_buffer(self):
        """获取用于显示的缓冲区（前缓冲）"""
        return self.front_buffer
        
    def prepare_back_buffer(self):
        """准备后缓冲区用于新内容渲染"""
        # 清理后缓冲区的子对象
        if self.back_buffer:
            child_cnt = self.back_buffer.get_child_cnt()
            for i in range(child_cnt - 1, -1, -1):
                child = self.back_buffer.get_child(i)
                if child:
                    child.del_()
                    
    def destroy(self):
        """销毁缓冲区"""
        if self.front_buffer:
            self.front_buffer.del_()
            self.front_buffer = None
        if self.back_buffer:
            self.back_buffer.del_()
            self.back_buffer = None


class PreRenderManager:
    """预渲染管理器"""
    def __init__(self, app_drawer):
        self.app_drawer = app_drawer
        self.page_cache = PageCache()
        self.double_buffer = None
        self.prerender_timer = None
        self.is_prerendering = False
        
        # 初始化双缓冲
        if hasattr(app_drawer, 'page_width') and hasattr(app_drawer, 'page_height'):
            self.double_buffer = DoubleBuffer(
                app_drawer.page_width, 
                app_drawer.page_height
            )
            
    def schedule_prerender(self, current_page):
        """调度预渲染邻近页面"""
        if not PRERENDER_ENABLED or self.is_prerendering:
            return
            
        # 取消之前的预渲染任务
        if self.prerender_timer:
            self.prerender_timer.del_()
            self.prerender_timer = None
            
        # 延迟执行预渲染，避免影响当前动画
        self.prerender_timer = lv.timer_create(
            lambda t: self._do_prerender(current_page),
            PRERENDER_DELAY_MS, 
            None
        )
        self.prerender_timer.set_repeat_count(1)
        
    def _do_prerender(self, current_page):
        """执行预渲染"""
        self.is_prerendering = True
        
        try:
            # 计算需要预渲染的页面
            total_pages = self.app_drawer.PAGE_SIZE
            prev_page = (current_page - 1 + total_pages) % total_pages
            next_page = (current_page + 1) % total_pages
            
            # 优先预渲染下一页
            pages_to_render = []
            if next_page != current_page:
                pages_to_render.append(next_page)
            if prev_page != current_page and prev_page != next_page:
                pages_to_render.append(prev_page)
                
            # 执行预渲染
            for page_idx in pages_to_render:
                if not self.page_cache.get(page_idx):
                    self._prerender_page(page_idx)
                    # 每渲染一页后让出CPU
                    gc.collect()
                    
        except Exception as e:
            if __debug__:
                print(f"PreRenderManager: Error in prerender: {e}")
        finally:
            self.is_prerendering = False
            self.prerender_timer = None
            
    def _prerender_page(self, page_index):
        """预渲染指定页面到缓存"""
        if __debug__:
            print(f"PreRenderManager: Prerendering page {page_index}")
            
        # 使用双缓冲的后缓冲区进行渲染
        if self.double_buffer:
            self.double_buffer.prepare_back_buffer()
            render_buffer = self.double_buffer.get_render_buffer()
            
            # 调用 AppDrawer 的渲染逻辑来填充内容
            # 这里需要复制页面内容到渲染缓冲区
            if hasattr(self.app_drawer, '_render_page_content'):
                self.app_drawer._render_page_content(page_index, render_buffer)
                
            # 将渲染好的内容存入缓存
            self.page_cache.put(page_index, render_buffer)
            
    def get_cached_page(self, page_index):
        """获取缓存的页面"""
        return self.page_cache.get(page_index)
        
    def use_double_buffer(self, page_index):
        """检查并使用双缓冲"""
        cached = self.get_cached_page(page_index)
        if cached and self.double_buffer:
            # 将缓存内容复制到双缓冲
            # 实际实现需要根据具体情况调整
            return True
        return False
        
    def clear(self):
        """清理所有资源"""
        if self.prerender_timer:
            self.prerender_timer.del_()
            self.prerender_timer = None
            
        self.page_cache.clear()
        
        if self.double_buffer:
            self.double_buffer.destroy()
            self.double_buffer = None