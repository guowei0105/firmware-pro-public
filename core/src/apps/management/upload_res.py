from micropython import const
from typing import TYPE_CHECKING

from storage import device
from trezor import io, wire
from trezor.crypto.hashlib import blake2s
from trezor.enums import ResourceType
from trezor.messages import (
    BlurRequest,
    ResourceAck,
    ResourceRequest,
    Success,
    ZoomRequest,
)

import ujson as json
import ure as re  # type: ignore[Import "ure" could not be resolved]

if TYPE_CHECKING:
    from trezor.messages import ResourceUpload
# Error code - 255
# FR_OK: int                   # (0) Succeeded
# FR_DISK_ERR: int             # (1) A hard error occurred in the low level disk I/O layer
# FR_INT_ERR: int              # (2) Assertion failed
# FR_NOT_READY: int            # (3) The physical drive cannot work
# FR_NO_FILE: int              # (4) Could not find the file
# FR_NO_PATH: int              # (5) Could not find the path
# FR_INVALID_NAME: int         # (6) The path name format is invalid
# FR_DENIED: int               # (7) Access denied due to prohibited access or directory full
# FR_EXIST: int                # (8) Access denied due to prohibited access
# FR_INVALID_OBJECT: int       # (9) The file/directory object is invalid
# FR_WRITE_PROTECTED: int      # (10) The physical drive is write protected
# FR_INVALID_DRIVE: int        # (11) The logical drive number is invalid
# FR_NOT_ENABLED: int          # (12) The volume has no work area
# FR_NO_FILESYSTEM: int        # (13) There is no valid FAT volume
# FR_MKFS_ABORTED: int         # (14) The f_mkfs() aborted due to any problem
# FR_TIMEOUT: int              # (15) Could not get a grant to access the volume within defined period
# FR_LOCKED: int               # (16) The operation is rejected according to the file sharing policy
# FR_NOT_ENOUGH_CORE: int      # (17) LFN working buffer could not be allocated
# FR_TOO_MANY_OPEN_FILES: int  # (18) Number of open files > FF_FS_LOCK
# FR_INVALID_PARAMETER: int    # (19) Given parameter is invalid

SUPPORTED_EXTS = (("jpg", "png", "jpeg"), ("jpg", "jpeg", "png", "mp4"))

SUPPORTED_MAX_RESOURCE_SIZE = {
    "jpg": const(1024 * 1024),
    "jpeg": const(1024 * 1024),
    "png": const(1024 * 1024),
    "mp4": const(10 * 1024 * 1024),
}
# FILE_PATH_COMPONENTS = (("wallpapers", "wp"), ("nfts", "nft"))
NFT_METADATA_ALLOWED_KEYS = ("header", "subheader", "network", "owner")
# CRITICAL: Chunk size must be <= wire buffer size (8KB) to avoid memory allocation
# If chunk size > wire buffer, codec_v1.py will try to allocate new buffer, causing MemoryError in fragmented memory
REQUEST_CHUNK_SIZE = const(8 * 1024)  # Was 16KB, reduced to 8KB to fit wire buffer

MAX_WP_COUNTER = const(5)
MAX_NFT_COUNTER = const(24)

# a more precise version should be ^(nft|wp)-[0-9,a-f]{8}-\\d{13,}$, but micropython not support limit range {}
PATTERN = re.compile(r"^(nft|wp)-[0-9a-f]+-\d+$")


async def upload_res(ctx: wire.Context, msg: ResourceUpload) -> Success:
    res_type = msg.res_type
    res_ext = msg.extension
    res_size = msg.data_length
    res_zoom_size = msg.zoom_data_length
    res_blur_size = msg.blur_data_length or 0

    # Log initial memory state
    try:
        import gc
        initial_mem_free = gc.mem_free()
        initial_mem_alloc = gc.mem_alloc()
    except Exception:
        pass

    # CRITICAL: Completely stop Layer2 wallpaper display and save decoder state
    # Step 1: Hide Layer2 to stop accessing wallpaper in VRAM
    try:
        from trezorui import Display
        display = Display()
        if hasattr(display, 'cover_background_hide'):
            display.cover_background_hide()
        if hasattr(display, 'cover_background_set_visible'):
            display.cover_background_set_visible(False)
    except Exception as e:
        pass

    # Step 1.5: CRITICAL - Wait for JPEG decoder to finish any pending operations
    try:
        import trezorio
        from trezor import loop

        # Check if decoder status functions are available
        if hasattr(trezorio, 'jpeg_decoder_is_busy'):
            max_wait_iterations = 100  # Wait up to 1000ms (1 second)
            for i in range(max_wait_iterations):
                is_busy = trezorio.jpeg_decoder_is_busy()
                has_error = trezorio.jpeg_decoder_has_error() if hasattr(trezorio, 'jpeg_decoder_has_error') else False

                if has_error:
                    break

                if not is_busy:
                    break

                await loop.sleep(10)  # 10ms per iteration
        else:
            # Fallback: just wait a fixed time
            await loop.sleep(500)  # 500ms fixed delay

    except Exception as e:
        pass

    # Step 2: Save hardware JPEG decoder state (critical for STM32)
    try:
        import trezorio
        if hasattr(trezorio, 'jpeg_save_decoder_state'):
            trezorio.jpeg_save_decoder_state()
    except Exception as e:
        pass

    # Clear LVGL image cache to free up texture memory
    try:
        from trezor.lvglui.scrs.common import lv
        lv.img_cache_invalidate_src(None)  # Clear all cached images
    except Exception as e:
        pass

    try:
        # Clear Python-side wallpaper cache
        from trezor.lvglui.scrs import homescreen
        if hasattr(homescreen, '_cached_styles'):
            homescreen._cached_styles.clear()
        if hasattr(homescreen, '_last_jpeg_loaded'):
            homescreen._last_jpeg_loaded = None
    except Exception as e:
        pass

    # Check memory status at the beginning
    try:
        import gc
        mem_before = gc.mem_free()

        # CRITICAL: Aggressive memory cleanup for continuous uploads
        # The "Message too large" error is actually a MemoryError in codec_v1.py
        # We need to defragment memory as much as possible

        # Multiple GC passes to clean up cycles and defragment
        for i in range(5):  # Increased from 3 to 5 passes
            gc.collect()
            if i % 2 == 0:
                mem_current = gc.mem_free()

        mem_after = gc.mem_free()
        mem_alloc = gc.mem_alloc()

        # Check if we have enough free memory (we need at least 50KB for wire buffers)
        MIN_REQUIRED_MEMORY = 50 * 1024  # 50KB
        if mem_after < MIN_REQUIRED_MEMORY:
            # Try one more aggressive cleanup
            for i in range(3):
                gc.collect()
            mem_after_emergency = gc.mem_free()

    except Exception as e:
        pass

    # Give the system a moment to stabilize after cache clearing
    try:
        from trezor import loop
        import trezorio

        # One more decoder check before starting upload
        if hasattr(trezorio, 'jpeg_decoder_is_busy'):
            for i in range(20):  # Max 200ms wait
                if not trezorio.jpeg_decoder_is_busy():
                    break
                await loop.sleep(10)

        await loop.sleep(50)  # Additional 50ms stabilization delay
    except Exception:
        pass

    if res_ext not in SUPPORTED_EXTS[res_type]:
        raise wire.DataError("Not supported resource extension")
    elif res_size >= SUPPORTED_MAX_RESOURCE_SIZE[res_ext]:
        raise wire.DataError("Data size overflow")
    if msg.file_name_no_ext:
        if PATTERN.match(msg.file_name_no_ext) is None:
            raise wire.DataError(
                "File name should follow the pattern (^(nft|wp)-[0-9a-f]{8}-\\d{13,}$)"
            )
    else:
        raise wire.DataError("File name required")
    if res_type == ResourceType.Nft:
        if msg.nft_meta_data is None:
            raise wire.DataError("NFT metadata required")
        elif len(msg.nft_meta_data) >= 2048:
            raise wire.DataError("NFT metadata must be less than 2K")
        try:
            metadata = json.loads(msg.nft_meta_data.decode("utf-8"))
        except BaseException as e:
            raise wire.DataError(f"Invalid metadata {e}")
        if any(key not in metadata.keys() for key in NFT_METADATA_ALLOWED_KEYS):
            raise wire.DataError("Invalid metadata")
    replace = False
    name_list = []
    try:
        file_counter = 0
        if res_type == ResourceType.WallPaper:
            for size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):
                if size > 0 and name[:4] == "zoom":
                    file_counter += 1
                    name_list.append(name)
                if file_counter >= MAX_WP_COUNTER:
                    replace = True
                    break
        else:
            for size, _attrs, name in io.fatfs.listdir("1:/res/nfts/zooms"):
                if size > 0:
                    file_counter += 1
                    name_list.append(name)
                if file_counter >= MAX_NFT_COUNTER:
                    replace = True
                    break
    except BaseException as e:
        raise wire.FirmwareError(f"File system error {e}")
    file_name = msg.file_name_no_ext
    for name in name_list:
        if file_name[: file_name.rindex("-")] == name[5 : name.rindex("-")]:
            if res_type == ResourceType.WallPaper:
                old_file_name = name[5:]  # Remove 'zoom-' prefix to get original filename
                old_path = "1:/res/wallpapers/" + old_file_name
                old_path_zoom = f"1:/res/wallpapers/{name}"

                # Files exist - skip upload entirely
                return Success(message="Success")
            else:
                raise wire.DataError("File already exists")

    # If wallpaper base-name didn't match (e.g., blur hash changed),
    # try to detect an existing pair by size (normal + zoom) and reuse it.
    if res_type == ResourceType.WallPaper:
        try:
            for size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):
                # Only consider zoom files with matching extension
                if size <= 0 or not name.startswith("zoom-"):
                    continue
                dot_idx = name.rfind(".")
                if dot_idx <= 0:
                    continue
                ext = name[dot_idx + 1 :]
                if ext != res_ext:
                    continue

                # Original counterpart (remove 'zoom-' prefix)
                orig_name = name[5:]
                zoom_path = f"1:/res/wallpapers/{name}"
                orig_path = f"1:/res/wallpapers/{orig_name}"

                try:
                    zoom_size, _, _ = io.fatfs.stat(zoom_path)
                    orig_size, _, _ = io.fatfs.stat(orig_path)
                except BaseException:
                    continue

                if zoom_size == res_zoom_size and orig_size == res_size:
                    # Found an existing pair matching sizes; treat as the same image.
                    # Files exist - skip upload entirely
                    return Success(message="Success")
        except BaseException:
            pass
            # Any filesystem error falls back to normal upload path below.
            pass
    # directly upload without confirmation

    config_path = ""
    blur_path = ""
    if res_type == ResourceType.WallPaper:
        file_full_path = f"1:/res/wallpapers/{file_name}.{res_ext}"
        zoom_path = f"1:/res/wallpapers/zoom-{file_name}.{res_ext}"
        if res_blur_size > 0:
            blur_path = f"1:/res/wallpapers/{file_name}-blur.{res_ext}"
    else:
        file_full_path = f"1:/res/nfts/imgs/{file_name}.{res_ext}"
        zoom_path = f"1:/res/nfts/zooms/zoom-{file_name}.{res_ext}"
        config_path = f"1:/res/nfts/desc/{file_name}.json"


    try:
        with io.fatfs.open(file_full_path, "w") as f:
            data_left = res_size
            offset = 0
            chunk_count = 0
            while data_left > 0:
                chunk_count += 1
                chunk_size = REQUEST_CHUNK_SIZE if data_left > REQUEST_CHUNK_SIZE else data_left
                try:
                    request = ResourceRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                    ack: ResourceAck = await ctx.call(request, ResourceAck)
                except Exception as e:
                    # Try to free memory and retry once
                    import gc
                    mem_before_retry = gc.mem_free()
                    gc.collect()
                    mem_after_retry = gc.mem_free()
                    try:
                        request = ResourceRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                        ack: ResourceAck = await ctx.call(request, ResourceAck)
                    except Exception as retry_e:
                        raise

                data = ack.data_chunk
                digest = blake2s(data).digest()
                if digest != ack.hash:
                    raise wire.DataError("Date digest is inconsistent")
                f.write(data)
                offset += chunk_size
                data_left -= REQUEST_CHUNK_SIZE
            # force refresh to disk
            f.sync()

        with io.fatfs.open(zoom_path, "w") as f:
            data_left = res_zoom_size
            offset = 0
            chunk_count = 0
            while data_left > 0:
                chunk_count += 1
                chunk_size = REQUEST_CHUNK_SIZE if data_left > REQUEST_CHUNK_SIZE else data_left
                try:
                    request = ZoomRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                    ack: ResourceAck = await ctx.call(request, ResourceAck)
                except Exception as e:
                    # Retry once with GC
                    import gc
                    gc.collect()
                    try:
                        request = ZoomRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                        ack: ResourceAck = await ctx.call(request, ResourceAck)
                    except Exception as retry_e:
                        raise

                data = ack.data_chunk
                digest = blake2s(data).digest()
                if digest != ack.hash:
                    raise wire.DataError("Date digest is inconsistent")
                f.write(data)
                offset += chunk_size
                data_left -= REQUEST_CHUNK_SIZE
            # force refresh to disk
            f.sync()

        # Handle blur data for wallpapers
        if res_type == ResourceType.WallPaper and blur_path and res_blur_size > 0:
            # CRITICAL: Free memory before blur upload (largest file, most likely to fail)
            try:
                import gc
                mem_before = gc.mem_free()
                for i in range(5):  # Multiple GC passes
                    gc.collect()
                mem_free = gc.mem_free()
                mem_alloc = gc.mem_alloc()
            except Exception as e:
                pass

            # Wait for system to stabilize
            try:
                from trezor import loop
                await loop.sleep(50)  # 50ms delay before blur
            except Exception as e:
                pass

            with io.fatfs.open(blur_path, "w") as f:
                data_left = res_blur_size
                offset = 0
                chunk_count = 0
                while data_left > 0:
                    chunk_count += 1
                    chunk_size = REQUEST_CHUNK_SIZE if data_left > REQUEST_CHUNK_SIZE else data_left
                    try:
                        request = BlurRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                        ack: ResourceAck = await ctx.call(request, ResourceAck)
                    except Exception as e:
                        # Retry once with aggressive GC
                        import gc
                        for i in range(3):
                            gc.collect()
                        try:
                            request = BlurRequest(data_length=REQUEST_CHUNK_SIZE, offset=offset)
                            ack: ResourceAck = await ctx.call(request, ResourceAck)
                        except Exception as retry_e:
                            raise

                    data = ack.data_chunk
                    digest = blake2s(data).digest()
                    if digest != ack.hash:
                        raise wire.DataError("Date digest is inconsistent")
                    f.write(data)
                    offset += chunk_size
                    data_left -= REQUEST_CHUNK_SIZE
                # force refresh to disk
                f.sync()

        if res_type == ResourceType.Nft and config_path:
            with io.fatfs.open(config_path, "w") as f:
                assert msg.nft_meta_data
                f.write(msg.nft_meta_data)
                f.sync()


        # Check memory status after writing files
        try:
            import gc
            gc.collect()
            mem_free = gc.mem_free()
            mem_alloc = gc.mem_alloc()
        except Exception as e:
            pass

        if replace:
            # Get current wallpapers to protect them
            from storage import device as storage_device

            lockscreen_wallpaper = storage_device.get_homescreen()
            mainscreen_wallpaper = storage_device.get_appdrawer_background()

            wallpapers_in_use = set()

            # Extract lockscreen wallpaper filename
            if lockscreen_wallpaper:
                if "/" in lockscreen_wallpaper:
                    lockscreen_name = lockscreen_wallpaper.split("/")[-1]
                else:
                    lockscreen_name = lockscreen_wallpaper

                if lockscreen_name.startswith("wp-"):
                    if "-blur." in lockscreen_name:
                        lockscreen_name = lockscreen_name.replace("-blur.", ".")
                    wallpapers_in_use.add(lockscreen_name)

            # Extract mainscreen wallpaper filename
            if mainscreen_wallpaper:
                if "/" in mainscreen_wallpaper:
                    mainscreen_name = mainscreen_wallpaper.split("/")[-1]
                else:
                    mainscreen_name = mainscreen_wallpaper

                if mainscreen_name.startswith("wp-"):
                    if "-blur." in mainscreen_name:
                        mainscreen_name = mainscreen_name.replace("-blur.", ".")
                    wallpapers_in_use.add(mainscreen_name)

            def safe_extract_timestamp(name):
                try:
                    parts = name[5:].split("-")  # Remove "zoom-" prefix
                    if len(parts) >= 2:
                        # Get the timestamp part (second to last part for regular files)
                        timestamp_part = parts[-2] if "-blur" in name else parts[-1]
                        # Remove file extension
                        if "." in timestamp_part:
                            timestamp_part = timestamp_part.split(".")[0]
                        return int(timestamp_part)
                    return 0
                except (ValueError, IndexError):
                    return 0

            name_list.sort(key=safe_extract_timestamp)

            # Find oldest wallpaper that is NOT in use
            zoom_file = None
            file_name = None
            for zoom_candidate in name_list:
                orig_candidate = zoom_candidate[5:]  # Remove "zoom-" prefix
                if orig_candidate not in wallpapers_in_use:
                    zoom_file = zoom_candidate
                    file_name = orig_candidate
                    break

            # If all wallpapers are in use, don't delete anything
            if zoom_file is None:
                replace = False

            if replace and zoom_file and res_type == ResourceType.WallPaper:
                zoom_to_delete = f"1:/res/wallpapers/{zoom_file}"
                orig_to_delete = f"1:/res/wallpapers/{file_name}"

                try:
                    io.fatfs.unlink(zoom_to_delete)
                except BaseException as e:
                    raise

                try:
                    io.fatfs.unlink(orig_to_delete)
                except BaseException as e:
                    raise

                # Also remove blur file if it exists
                blur_file_name = file_name[: -(len(res_ext) + 1)] + f"-blur.{res_ext}"
                blur_to_delete = f"1:/res/wallpapers/{blur_file_name}"
                try:
                    io.fatfs.unlink(blur_to_delete)
                except BaseException as e:
                    pass  # blur file might not exist
            elif replace and zoom_file and res_type == ResourceType.Nft:
                zoom_to_delete = f"1:/res/nfts/zooms/{zoom_file}"
                img_to_delete = f"1:/res/nfts/imgs/{file_name}"
                config_name = file_name[: -(len(res_ext) + 1)]
                config_to_delete = f"1:/res/nfts/desc/{config_name}.json"

                try:
                    io.fatfs.unlink(zoom_to_delete)
                    io.fatfs.unlink(img_to_delete)
                    io.fatfs.unlink(config_to_delete)
                except BaseException as e:
                    raise
        elif res_type == ResourceType.WallPaper:
            device.increase_wp_cnts()

    except BaseException as e:
        import sys

        # Log memory state at failure
        try:
            import gc
            fail_mem_free = gc.mem_free()
            fail_mem_alloc = gc.mem_alloc()
        except Exception:
            pass

        # Restore system state even on failure

        # Clean up memory first (CRITICAL for next upload)
        try:
            import gc
            for i in range(5):
                gc.collect()
            cleanup_mem_free = gc.mem_free()
        except Exception as gc_e:
            pass

        # Restore JPEG decoder state
        try:
            import trezorio
            if hasattr(trezorio, 'jpeg_restore_decoder_state'):
                trezorio.jpeg_restore_decoder_state()
        except Exception as restore_e:
            pass

        # Restore Layer2 visibility
        try:
            from trezorui import Display
            display = Display()
        except Exception as layer_e:
            pass

        raise wire.FirmwareError(f"Failed to write file with error code {e}")

    # Restore JPEG decoder state and Layer2 display after successful upload

    # Step 0: CRITICAL - Clean up memory for next upload (prevent "Message too large" error)
    try:
        import gc
        mem_before_cleanup = gc.mem_free()

        # Aggressive GC to free memory for next upload
        for i in range(5):
            gc.collect()

        mem_after_cleanup = gc.mem_free()
    except Exception as e:
        pass

    # Step 1: Restore JPEG decoder state
    try:
        import trezorio
        if hasattr(trezorio, 'jpeg_restore_decoder_state'):
            trezorio.jpeg_restore_decoder_state()
    except Exception as e:
        pass

    # Step 2: Restore Layer2 visibility (if it was visible before)
    try:
        from trezorui import Display
        display = Display()
        # Check if Layer2 was previously visible and restore it
        if hasattr(display, 'cover_background_is_visible'):
            # Note: We don't know if it was visible before, so we'll just ensure it's in correct state
            # The MainScreen/LockScreen will manage the visibility
            pass
    except Exception as e:
        pass

    # Step 3: Auto-delete old wallpapers (keep only 5 newest, preserve current wallpaper)
    if res_type == ResourceType.WallPaper:
        try:
            # Scan all wallpapers (original files only, not blur/zoom)
            wallpaper_files = []
            for size, _attrs, name in io.fatfs.listdir("1:/res/wallpapers"):
                if (
                    size > 0
                    and name.startswith("wp-")
                    and not name.endswith("-blur.jpeg")
                    and not name.endswith("-blur.jpg")
                ):
                    wallpaper_files.append(name)

            if len(wallpaper_files) > 5:
                # Sort by timestamp in filename descending (newest first)
                # Filename format: wp-{hash}-{timestamp}.jpeg
                def extract_timestamp(filename):
                    try:
                        # Extract timestamp from "wp-xxx-123456789.jpeg"
                        parts = filename.rsplit("-", 1)  # Split from right, get last part
                        if len(parts) == 2:
                            timestamp_str = parts[1].split(".")[0]  # Remove extension
                            return int(timestamp_str)
                    except (ValueError, IndexError):
                        pass
                    return 0  # Fallback for malformed filenames

                wallpaper_files.sort(key=extract_timestamp, reverse=True)

                # Get current wallpapers (lockscreen and main screen)
                from storage import device as storage_device

                # 1. Get lockscreen wallpaper
                lockscreen_wallpaper = storage_device.get_homescreen()
                lockscreen_wallpaper_name = None
                if lockscreen_wallpaper:
                    # Extract filename from path
                    if "/" in lockscreen_wallpaper:
                        lockscreen_wallpaper_name = lockscreen_wallpaper.split("/")[-1]
                    else:
                        # Path doesn't contain /, might be just a filename
                        lockscreen_wallpaper_name = lockscreen_wallpaper

                    # Only process custom wallpapers (starting with "wp-")
                    if lockscreen_wallpaper_name.startswith("wp-"):
                        # If it's a blur file, extract original filename
                        if "-blur." in lockscreen_wallpaper_name:
                            # wp-xxx-timestamp-blur.jpeg -> wp-xxx-timestamp.jpeg
                            lockscreen_wallpaper_name = lockscreen_wallpaper_name.replace("-blur.", ".")
                    else:
                        # Not a custom wallpaper, ignore
                        lockscreen_wallpaper_name = None

                # 2. Get main screen (appdrawer) wallpaper
                mainscreen_wallpaper = storage_device.get_appdrawer_background()
                mainscreen_wallpaper_name = None
                if mainscreen_wallpaper:
                    # Extract filename from path
                    if "/" in mainscreen_wallpaper:
                        mainscreen_wallpaper_name = mainscreen_wallpaper.split("/")[-1]
                    else:
                        # Path doesn't contain /, might be just a filename
                        mainscreen_wallpaper_name = mainscreen_wallpaper

                    # Only process custom wallpapers (starting with "wp-")
                    if mainscreen_wallpaper_name.startswith("wp-"):
                        # If it's a blur file, extract original filename
                        if "-blur." in mainscreen_wallpaper_name:
                            # wp-xxx-timestamp-blur.jpeg -> wp-xxx-timestamp.jpeg
                            mainscreen_wallpaper_name = mainscreen_wallpaper_name.replace("-blur.", ".")
                    else:
                        # Not a custom wallpaper, ignore
                        mainscreen_wallpaper_name = None

                # Collect wallpapers currently in use (only custom wallpapers)
                wallpapers_in_use = set()
                if lockscreen_wallpaper_name:
                    wallpapers_in_use.add(lockscreen_wallpaper_name)
                if mainscreen_wallpaper_name:
                    wallpapers_in_use.add(mainscreen_wallpaper_name)

                # Calculate how many more wallpapers we can keep (total 5 - already in use)
                slots_available = max(5 - len(wallpapers_in_use), 0)

                # Keep: wallpapers in use + newest N from the rest
                files_to_keep = wallpapers_in_use.copy()
                for wallpaper_name in wallpaper_files:
                    if wallpaper_name not in wallpapers_in_use:
                        if slots_available > 0:
                            files_to_keep.add(wallpaper_name)
                            slots_available -= 1
                        else:
                            break  # Already have 5 wallpapers total

                # Delete old wallpapers
                deleted_count = 0
                for wallpaper_name in wallpaper_files:
                    if wallpaper_name not in files_to_keep:
                        try:
                            # Delete original file
                            orig_path = f"1:/res/wallpapers/{wallpaper_name}"
                            io.fatfs.unlink(orig_path)

                            # Delete zoom file
                            zoom_path = f"1:/res/wallpapers/zoom-{wallpaper_name}"
                            try:
                                io.fatfs.unlink(zoom_path)
                            except BaseException:
                                pass  # Zoom file may not exist

                            # Delete blur file
                            dot_idx = wallpaper_name.rfind(".")
                            if dot_idx > 0:
                                base_name = wallpaper_name[:dot_idx]
                                # Extract extension from the wallpaper being deleted, not from msg
                                wallpaper_ext = wallpaper_name[dot_idx+1:]
                                blur_path = f"1:/res/wallpapers/{base_name}-blur.{wallpaper_ext}"
                                try:
                                    io.fatfs.unlink(blur_path)
                                except BaseException:
                                    pass  # Blur file may not exist

                            deleted_count += 1
                        except BaseException as del_e:
                            pass

        except Exception as cleanup_e:
            pass

    return Success(message="Success")
