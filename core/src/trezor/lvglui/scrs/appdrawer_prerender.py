"""
AppDrawer pre-rendering optimization module
Provides double buffering, page caching and pre-rendering functionality to improve animation smoothness
"""

import gc
from micropython import const

import lv

try:
    import utime

    get_time_ms = lambda: utime.ticks_ms()
except:
    get_time_ms = lambda: 0

# Pre-rendering configuration
PRERENDER_ENABLED = const(1)  # Enable pre-rendering
CACHE_SIZE = const(2)  # Number of cached pages
CACHE_EXPIRY_MS = const(30000)  # Cache expiry time 30 seconds
PRERENDER_DELAY_MS = const(50)  # Pre-render delay to avoid affecting current animation


class PageCache:
    """Page cache manager"""

    def __init__(self, max_size=CACHE_SIZE):
        self.max_size = max_size
        self.cache = (
            {}
        )  # {page_index: {'buffer': lv.obj, 'timestamp': ms, 'hit_count': int}}
        self.render_queue = []  # Render queue

    def get(self, page_index):
        """Get cached page"""
        if page_index in self.cache:
            entry = self.cache[page_index]
            current_time = get_time_ms()

            # Check if cache is expired
            if current_time - entry["timestamp"] < CACHE_EXPIRY_MS:
                entry["hit_count"] += 1
                if __debug__:
                    print(
                        f"PageCache: Hit for page {page_index}, hit_count={entry['hit_count']}"
                    )
                return entry["buffer"]
            else:
                # Cache expired, clean up
                if __debug__:
                    print(f"PageCache: Expired cache for page {page_index}")
                self._evict(page_index)
        return None

    def put(self, page_index, buffer):
        """Store page to cache"""
        # If cache is full, evict least recently used
        if len(self.cache) >= self.max_size and page_index not in self.cache:
            self._evict_lru()

        self.cache[page_index] = {
            "buffer": buffer,
            "timestamp": get_time_ms(),
            "hit_count": 0,
        }
        if __debug__:
            print(f"PageCache: Cached page {page_index}")

    def _evict(self, page_index):
        """Remove specified page cache"""
        if page_index in self.cache:
            entry = self.cache[page_index]
            # Clean up LVGL object
            if entry["buffer"] and hasattr(entry["buffer"], "del_"):
                try:
                    entry["buffer"].del_()
                except:
                    pass
            del self.cache[page_index]
            gc.collect()

    def _evict_lru(self):
        """Evict least recently used cache"""
        if not self.cache:
            return

        # Find the one with minimum hit_count
        min_page = min(self.cache.keys(), key=lambda k: self.cache[k]["hit_count"])
        if __debug__:
            print(f"PageCache: Evicting LRU page {min_page}")
        self._evict(min_page)

    def clear(self):
        """Clear all caches"""
        for page_index in list(self.cache.keys()):
            self._evict(page_index)
        self.render_queue.clear()


class DoubleBuffer:
    """Double buffer manager"""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.front_buffer = None
        self.back_buffer = None
        self.is_swapped = False

    def init_buffers(self, parent):
        """Initialize front and back buffers"""
        # Create front buffer (currently displayed)
        self.front_buffer = lv.obj(parent)
        self.front_buffer.set_size(self.width, self.height)
        self.front_buffer.set_pos(0, 0)
        self.front_buffer.add_style(self._create_transparent_style(), 0)
        self.front_buffer.clear_flag(lv.obj.FLAG.SCROLLABLE)

        # Create back buffer (pre-rendered)
        self.back_buffer = lv.obj(parent)
        self.back_buffer.set_size(self.width, self.height)
        self.back_buffer.set_pos(0, 0)
        self.back_buffer.add_style(self._create_transparent_style(), 0)
        self.back_buffer.add_flag(lv.obj.FLAG.HIDDEN)
        self.back_buffer.clear_flag(lv.obj.FLAG.SCROLLABLE)

    def _create_transparent_style(self):
        """Create transparent style"""
        from ..scrs.widgets.style import StyleWrapper

        return StyleWrapper().bg_opa(lv.OPA.TRANSP).border_width(0).pad_all(0)

    def swap(self):
        """Swap front and back buffers"""
        # Quick reference swap
        self.front_buffer, self.back_buffer = self.back_buffer, self.front_buffer

        # Update visibility
        self.front_buffer.clear_flag(lv.obj.FLAG.HIDDEN)
        self.back_buffer.add_flag(lv.obj.FLAG.HIDDEN)

        self.is_swapped = not self.is_swapped
        if __debug__:
            print(f"DoubleBuffer: Swapped buffers")

    def get_render_buffer(self):
        """Get buffer for rendering (back buffer)"""
        return self.back_buffer

    def get_display_buffer(self):
        """Get buffer for display (front buffer)"""
        return self.front_buffer

    def prepare_back_buffer(self):
        """Prepare back buffer for new content rendering"""
        # Clean up child objects in back buffer
        if self.back_buffer:
            child_cnt = self.back_buffer.get_child_cnt()
            for i in range(child_cnt - 1, -1, -1):
                child = self.back_buffer.get_child(i)
                if child:
                    child.del_()

    def destroy(self):
        """Destroy buffers"""
        if self.front_buffer:
            self.front_buffer.del_()
            self.front_buffer = None
        if self.back_buffer:
            self.back_buffer.del_()
            self.back_buffer = None


class PreRenderManager:
    """Pre-render manager"""

    def __init__(self, app_drawer):
        self.app_drawer = app_drawer
        self.page_cache = PageCache()
        self.double_buffer = None
        self.prerender_timer = None
        self.is_prerendering = False

        # Initialize double buffer
        if hasattr(app_drawer, "page_width") and hasattr(app_drawer, "page_height"):
            self.double_buffer = DoubleBuffer(
                app_drawer.page_width, app_drawer.page_height
            )

    def schedule_prerender(self, current_page):
        """Schedule pre-rendering of adjacent pages"""
        if not PRERENDER_ENABLED or self.is_prerendering:
            return

        # Cancel previous pre-render task
        if self.prerender_timer:
            self.prerender_timer.del_()
            self.prerender_timer = None

        # Delay pre-render execution to avoid affecting current animation
        self.prerender_timer = lv.timer_create(
            lambda t: self._do_prerender(current_page), PRERENDER_DELAY_MS, None
        )
        self.prerender_timer.set_repeat_count(1)

    def _do_prerender(self, current_page):
        """Execute pre-rendering"""
        self.is_prerendering = True

        try:
            # Calculate pages that need pre-rendering
            total_pages = self.app_drawer.PAGE_SIZE
            prev_page = (current_page - 1 + total_pages) % total_pages
            next_page = (current_page + 1) % total_pages

            # Prioritize pre-rendering next page
            pages_to_render = []
            if next_page != current_page:
                pages_to_render.append(next_page)
            if prev_page != current_page and prev_page != next_page:
                pages_to_render.append(prev_page)

            # Execute pre-rendering
            for page_idx in pages_to_render:
                if not self.page_cache.get(page_idx):
                    self._prerender_page(page_idx)
                    # Yield CPU after rendering each page
                    gc.collect()

        except Exception as e:
            if __debug__:
                print(f"PreRenderManager: Error in prerender: {e}")
        finally:
            self.is_prerendering = False
            self.prerender_timer = None

    def _prerender_page(self, page_index):
        """Pre-render specified page to cache"""
        if __debug__:
            print(f"PreRenderManager: Prerendering page {page_index}")

        # Use back buffer of double buffer for rendering
        if self.double_buffer:
            self.double_buffer.prepare_back_buffer()
            render_buffer = self.double_buffer.get_render_buffer()

            # Call AppDrawer's rendering logic to fill content
            # Need to copy page content to render buffer here
            if hasattr(self.app_drawer, "_render_page_content"):
                self.app_drawer._render_page_content(page_index, render_buffer)

            # Store rendered content in cache
            self.page_cache.put(page_index, render_buffer)

    def get_cached_page(self, page_index):
        """Get cached page"""
        return self.page_cache.get(page_index)

    def use_double_buffer(self, page_index):
        """Check and use double buffer"""
        cached = self.get_cached_page(page_index)
        if cached and self.double_buffer:
            # Copy cached content to double buffer
            # Actual implementation needs to be adjusted based on specific situation
            return True
        return False

    def clear(self):
        """Clean up all resources"""
        if self.prerender_timer:
            self.prerender_timer.del_()
            self.prerender_timer = None

        self.page_cache.clear()

        if self.double_buffer:
            self.double_buffer.destroy()
            self.double_buffer = None
