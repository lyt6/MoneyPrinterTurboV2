import os
import random
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

requested_count = 0


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global requested_count
    requested_count += 1
    return api_keys[requested_count % len(api_keys)]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    max_results: int = 20,  # 新增：最大结果数
) -> List[MaterialInfo]:
    """
    使用Pexels API搜索视频素材
    
    优化点：
    1. 支持多语言搜索（中英文关键词）
    2. 智能质量筛选（优先选择高质量视频）
    3. 支持相关度排序（Pexels API自动按相关度排序）
    4. 支持精确分辨率匹配和降级匹配
    """
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    
    # 优化搜索参数：增加结果数量，提高命中率
    params = {
        "query": search_term, 
        "per_page": min(max_results, 80),  # Pexels最多支持80个/页
        "orientation": video_orientation,
        "size": "large",  # 优先高质量视频
    }
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=False,
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        
        videos = response["videos"]
        logger.info(f"pexels returned {len(videos)} videos for '{search_term}'")
        
        # 按相关度和质量筛选视频
        for v in videos:
            duration = v["duration"]
            # 检查视频是否满足最小时长要求
            if duration < minimum_duration:
                continue
            
            video_files = v["video_files"]
            # 按质量优先级排序：精确匹配 > 高质量降级 > 普通降级
            matched_video = None
            best_fallback = None
            
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                quality = video.get("quality", "")
                
                # 策略1：精确分辨率匹配（最优）
                if w == video_width and h == video_height:
                    matched_video = video
                    break
                
                # 策略2：宽高比匹配 + HD质量（次优）
                if not best_fallback and quality == "hd":
                    aspect_ratio_target = video_width / video_height
                    aspect_ratio_current = w / h if h > 0 else 0
                    # 宽高比误差在10%以内
                    if abs(aspect_ratio_current - aspect_ratio_target) / aspect_ratio_target < 0.1:
                        if w >= video_width * 0.8:  # 宽度至少是目标的80%
                            best_fallback = video
            
            # 使用匹配的视频
            selected_video = matched_video or best_fallback
            if selected_video:
                item = MaterialInfo()
                item.provider = "pexels"
                item.url = selected_video["link"]
                item.duration = duration
                video_items.append(item)
                logger.debug(f"selected video: {selected_video['width']}x{selected_video['height']} ({selected_video.get('quality', 'unknown')})")
        
        logger.info(f"filtered {len(video_items)} suitable videos from pexels")
        return video_items
        
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    max_results: int = 50,  # 新增：最大结果数
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": min(max_results, 200),  # Pixabay最多200个/页
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=False, timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=False,
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            clip.close()
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[str]:
    """
    下载视频素材
    
    优化点：
    1. 智能去重：避免重复视频
    2. 动态调整搜索策略：如果关键词搜不到足够素材，自动扩大搜索范围
    3. 质量优先：优先下载高相关度和高质量的视频
    4. 进度跟踪：详细记录搜索和下载进度
    """
    valid_video_items = []
    valid_video_urls = set()  # 使用set加速url查找
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay

    # 第一轮：按原始关键词搜索
    logger.info(f"🔍 开始搜索视频素材，关键词: {search_terms}")
    
    for search_term in search_terms:
        if not search_term or not search_term.strip():
            continue
            
        logger.info(f"  - 搜索关键词: '{search_term}'")
        video_items = search_videos(
            search_term=search_term.strip(),
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
            max_results=40,  # 增加搜索结果数
        )
        
        # 去重并添加到候选列表
        new_count = 0
        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.add(item.url)
                found_duration += item.duration
                new_count += 1
        
        logger.info(f"    ✅ 找到 {len(video_items)} 个视频，新增 {new_count} 个（去重后）")

    # 第二轮：如果素材不足，尝试组合关键词搜索
    if found_duration < audio_duration * 0.8 and len(search_terms) > 1:
        logger.warning(f"  ⚠️  素材不足（已找到 {found_duration:.1f}s，需要 {audio_duration:.1f}s）")
        logger.info(f"  🔎 尝试组合关键词搜索...")
        
        # 取前2-3个核心关键词组合
        combined_term = " ".join(search_terms[:min(3, len(search_terms))])
        video_items = search_videos(
            search_term=combined_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
            max_results=30,
        )
        
        new_count = 0
        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.add(item.url)
                found_duration += item.duration
                new_count += 1
        
        if new_count > 0:
            logger.info(f"    ✅ 组合搜索新增 {new_count} 个视频")

    logger.info(
        f"""
┌── 搜索结果统计 ─────────────────────────────┐
│ 找到视频总数: {len(valid_video_items)} 个                             │
│ 需要时长: {audio_duration:.1f} 秒                               │
│ 找到时长: {found_duration:.1f} 秒                               │
│ 覆盖率: {min(100, found_duration/audio_duration*100 if audio_duration > 0 else 0):.1f}%                                      │
└───────────────────────────────────────────────────┘
        """
    )
    
    video_paths = []
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    # 按模式排序：随机或顺序
    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)
        logger.info("🎲 使用随机顺序下载")
    else:
        logger.info("📊 按相关度顺序下载")

    # 下载视频
    logger.info("\n📥 开始下载视频素材...")
    total_duration = 0.0
    downloaded_count = 0
    
    for idx, item in enumerate(valid_video_items, 1):
        try:
            logger.info(f"  [{idx}/{len(valid_video_items)}] 下载: {item.url[:80]}...")
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.success(f"    ✅ 保存: {os.path.basename(saved_video_path)}")
                video_paths.append(saved_video_path)
                downloaded_count += 1
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                
                # 判断是否已经足够
                if total_duration >= audio_duration:
                    logger.success(
                        f"    ✨ 已达到目标时长 ({total_duration:.1f}s >= {audio_duration:.1f}s)，停止下载"
                    )
                    break
        except Exception as e:
            logger.error(f"    ❌ 下载失败: {str(e)}")
    
    logger.success(
        f"""
┌── 下载完成 ──────────────────────────────────┐
│ 成功下载: {downloaded_count} 个视频                              │
│ 总时长: {total_duration:.1f} 秒                                  │
│ 目标时长: {audio_duration:.1f} 秒                                │
└───────────────────────────────────────────────────┘
        """
    )
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
