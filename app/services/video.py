import glob
import itertools
import os
import random
import gc
import shutil
from typing import List
from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
    VideoTheme,
)
from app.services.utils import video_effects
from app.utils import utils

# GPU编码器缓存（避免重复检测）
_gpu_encoder_cache = None

def detect_gpu_encoder():
    """
    自动检测GPU编码器，优先使用硬件加速
    返回: (video_codec, extra_ffmpeg_params)
    """
    global _gpu_encoder_cache
    
    # 使用缓存结果
    if _gpu_encoder_cache is not None:
        return _gpu_encoder_cache
    
    import subprocess
    import platform
    import shutil
    
    # 首先检查ffmpeg是否可用
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        logger.warning("⚠️ 未找到ffmpeg命令，请确保已安装ffmpeg并添加到系统PATH")
        logger.info("提示：macOS可使用 'brew install ffmpeg' 安装")
        # 默认使用CPU编码
        _gpu_encoder_cache = ('libx264', ['-preset', 'ultrafast', '-crf', '23'])
        return _gpu_encoder_cache
    
    try:
        # 检查ffmpeg支持的编码器
        result = subprocess.run(
            [ffmpeg_path, '-hide_banner', '-encoders'],
            capture_output=True,
            text=True,
            timeout=5
        )
        encoders = result.stdout.lower()
        
        system = platform.system()
        
        # macOS - VideoToolbox (苹果芯片原生支持)
        if system == 'Darwin' and 'h264_videotoolbox' in encoders:
            logger.info("⚡ GPU加速：检测到 VideoToolbox 编码器 (macOS)")
            _gpu_encoder_cache = ('h264_videotoolbox', [
                '-allow_sw', '1',  # 如果硬件不可用，允许回退到软件编码
                '-b:v', '5M',
            ])
            return _gpu_encoder_cache
        
        # NVIDIA NVENC
        if 'h264_nvenc' in encoders or 'nvenc' in encoders:
            logger.info("⚡ GPU加速：检测到 NVIDIA NVENC 编码器")
            _gpu_encoder_cache = ('h264_nvenc', [
                '-preset', 'p4',  # p1-p7，p4平衡速度和质量
                '-b:v', '5M',
            ])
            return _gpu_encoder_cache
        
        # AMD AMF
        if 'h264_amf' in encoders or 'amf' in encoders:
            logger.info("⚡ GPU加速：检测到 AMD AMF 编码器")
            _gpu_encoder_cache = ('h264_amf', [
                '-quality', 'speed',
                '-b:v', '5M',
            ])
            return _gpu_encoder_cache
        
        # Intel QSV
        if 'h264_qsv' in encoders or 'qsv' in encoders:
            logger.info("⚡ GPU加速：检测到 Intel QSV 编码器")
            _gpu_encoder_cache = ('h264_qsv', [
                '-preset', 'veryfast',
                '-b:v', '5M',
            ])
            return _gpu_encoder_cache
        
        logger.info("ℹ️ 未检测到GPU编码器，使用CPU软编码（性能较慢但兼容性好）")
        
    except subprocess.TimeoutExpired:
        logger.warning("检测GPU编码器超时，使用CPU软编码")
    except Exception as e:
        logger.warning(f"检测GPU编码器时出错: {e}，使用CPU软编码")
    
    # 默认使用CPU编码
    _gpu_encoder_cache = ('libx264', ['-preset', 'ultrafast', '-crf', '23'])
    return _gpu_encoder_cache


def get_optimal_threads():
    """
    获取最优线程数：CPU核心数 - 1，留一个核心给系统
    """
    import multiprocessing
    cpu_count = multiprocessing.cpu_count()
    optimal = max(2, cpu_count - 1)
    logger.info(f"💻 CPU核心数: {cpu_count}，使用线程数: {optimal}")
    return optimal


class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
video_codec = "libx264"
fps = 30

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
        
    for file in files:
        try:
            os.remove(file)
        except:
            pass


def _generate_video_from_single_image(
    image_path: str,
    audio_duration: float,
    output_path: str,
    video_width: int,
    video_height: int,
    threads: int = 2,
    enable_animation: bool = False
) -> str:
    """
    从单一图片直接生成视频，可选缩放动画效果
    使用优化的编码参数以提升速度
    """
    logger.info(f"generating video from single image: {image_path}")
    logger.info(f"  - target resolution: {video_width}x{video_height}")
    logger.info(f"  - duration: {audio_duration:.2f}s")
    logger.info(f"  - animation: {'enabled' if enable_animation else 'disabled'}")
    
    try:
        # 创建图片剪辑，设置时长为音频时长
        clip = ImageClip(image_path).with_duration(audio_duration).with_position("center")
        
        # 检查图片尺寸
        img_width, img_height = clip.size
        logger.info(f"  - source image size: {img_width}x{img_height}")
        
        # 计算缩放比例
        img_ratio = img_width / img_height
        video_ratio = video_width / video_height
        
        # 根据开关决定是否应用缩放效果
        if enable_animation:
            # 应用缩放效果：从100%缓慢放大到120%
            zoom_factor = 1.2
            zoom_clip = clip.resized(lambda t: 1 + (zoom_factor - 1) * (t / audio_duration))
            logger.info(f"  - zoom animation enabled (100% -> 120%)")
        else:
            # 不应用缩放效果，直接使用静态图片（更快）
            zoom_clip = clip
            logger.info(f"  - static image (no animation, faster)")
        
        # 处理尺寸不匹配的情况
        if abs(img_ratio - video_ratio) > 0.01:  # 比例不同
            logger.info(f"  - image ratio ({img_ratio:.2f}) != video ratio ({video_ratio:.2f}), adding black bars")
            # 计算缩放后的尺寸
            if img_ratio > video_ratio:
                # 图片更宽，以宽度为准
                scale_factor = video_width / img_width
                if enable_animation:
                    scale_factor *= 1.2  # 留出缩放空间
            else:
                # 图片更高，以高度为准
                scale_factor = video_height / img_height
                if enable_animation:
                    scale_factor *= 1.2  # 留出缩放空间
            
            # 创建黑色背景
            background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(audio_duration)
            # 将缩放后的图片居中放置
            final_clip = CompositeVideoClip([background, zoom_clip.with_position("center")])
        else:
            # 比例匹配，直接缩放到目标尺寸
            logger.info(f"  - image ratio matches video ratio, direct resize")
            final_clip = CompositeVideoClip([zoom_clip.resized((video_width, video_height))])
        
        # 优化编码参数以提升速度
        logger.info(f"  - writing video file (optimized encoding)...")
        
        # 检测GPU编码器
        gpu_codec, gpu_params = detect_gpu_encoder()
        
        # 使用更快的编码预设
        output_dir = os.path.dirname(output_path)
        
        # 构建完整的ffmpeg参数
        ffmpeg_params = gpu_params + [
            '-movflags', '+faststart',  # 优化web播放
        ]
        
        final_clip.write_videofile(
            output_path,
            fps=fps,
            codec=gpu_codec,  # 使用GPU编码器
            threads=threads,
            logger=None,
            audio=False,  # 不包含音频
            temp_audiofile_path=output_dir,
            ffmpeg_params=ffmpeg_params
        )
        
        close_clip(clip)
        close_clip(final_clip)
        
        logger.success(f"  ✓ single image video generated: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"failed to generate video from single image: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)
    
    if bgm_type == "white_noise":
        # 生成白噪音文件
        return _generate_white_noise()

    return ""


def _generate_white_noise(duration=60, sample_rate=44100):
    """
    生成白噪音音频文件
    使用FFmpeg生成白噪音，避免额外依赖
    
    Args:
        duration: 白噪音时长（秒），默认60秒，足够循环使用
        sample_rate: 采样率
    
    Returns:
        str: 白噪音文件路径
    """
    output_dir = utils.storage_dir("bgm", create=True)
    white_noise_file = os.path.join(output_dir, "white_noise.mp3")
    
    # 如果白噪音文件已存在，直接返回
    if os.path.exists(white_noise_file):
        logger.info(f"🎵 using existing white noise file: {white_noise_file}")
        return white_noise_file
    
    try:
        import subprocess
        logger.info(f"🎵 generating white noise ({duration}s)...")
        
        # 使用FFmpeg生成白噪音
        # anoisesrc 滤镜生成白噪音
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", f"anoisesrc=duration={duration}:sample_rate={sample_rate}:amplitude=0.1",
            "-ac", "2",  # 立体声
            "-y",
            white_noise_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.success(f"✅ white noise generated: {white_noise_file}")
            return white_noise_file
        else:
            logger.error(f"❌ failed to generate white noise: {result.stderr}")
            return ""
    except Exception as e:
        logger.error(f"❌ white noise generation failed: {str(e)}")
        return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    enable_animation: bool = False,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"audio duration: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"maximum clip duration: {req_dur} seconds")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    
    # 优化：检测到单一静态图片资源时，直接生成视频而不走复杂拼接流程
    if len(video_paths) == 1:
        single_path = video_paths[0]
        ext = utils.parse_extension(single_path)
        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"detected single image material, using fast generation path")
            close_clip(audio_clip)
            return _generate_video_from_single_image(
                image_path=single_path,
                audio_duration=audio_duration,
                output_path=combined_video_path,
                video_width=video_width,
                video_height=video_height,
                threads=threads,
                enable_animation=enable_animation
            )

    processed_clips = []
    subclipped_items = []
    video_duration = 0
    for video_path in video_paths:
        clip = VideoFileClip(video_path)
        clip_duration = clip.duration
        clip_w, clip_h = clip.size
        close_clip(clip)
        
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)            
            if clip_duration - start_time >= max_clip_duration:
                subclipped_items.append(SubClippedVideoClip(file_path= video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h))
            start_time = end_time    
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random subclipped_items order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")
    
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    for i, subclipped_item in enumerate(subclipped_items):
        if video_duration > audio_duration:
            break
        
        logger.debug(f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, current duration: {video_duration:.2f}s, remaining: {audio_duration - video_duration:.2f}s")
        
        try:
            clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
            clip_duration = clip.duration
            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")
                
                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)
                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([background, clip_resized])
                    
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip, 1)
            elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip, 1)
            elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip, 1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip, 1, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c, 1),
                    lambda c: video_effects.fadeout_transition(c, 1),
                    lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
                
            # wirte clip to temp file
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            
            # 检测GPU编码器
            gpu_codec, gpu_params = detect_gpu_encoder()
            
            clip.write_videofile(
                clip_file, 
                logger=None, 
                fps=fps, 
                codec=gpu_codec,
                ffmpeg_params=gpu_params
            )
            
            close_clip(clip)
        
            processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip.duration, width=clip_w, height=clip_h))
            video_duration += clip.duration
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until the video duration matches or exceeds the audio duration.
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
     
    # merge video clips progressively, avoid loading all videos at once to avoid memory overflow
    logger.info("starting clip merging process")
    if not processed_clips:
        logger.warning("no clips available for merging")
        return combined_video_path
    
    # if there is only one clip, use it directly
    if len(processed_clips) == 1:
        logger.info("using single clip directly")
        shutil.copy(processed_clips[0].file_path, combined_video_path)
        delete_files(processed_clips)
        logger.info("video combining completed")
        return combined_video_path
    
    # create initial video file as base
    base_clip_path = processed_clips[0].file_path
    temp_merged_video = f"{output_dir}/temp-merged-video.mp4"
    temp_merged_next = f"{output_dir}/temp-merged-next.mp4"
    
    # copy first clip as initial merged video
    shutil.copy(base_clip_path, temp_merged_video)
    
    # merge remaining video clips one by one
    for i, clip in enumerate(processed_clips[1:], 1):
        logger.info(f"merging clip {i}/{len(processed_clips)-1}, duration: {clip.duration:.2f}s")
        
        try:
            # load current base video and next clip to merge
            base_clip = VideoFileClip(temp_merged_video)
            next_clip = VideoFileClip(clip.file_path)
            
            # merge these two clips
            merged_clip = concatenate_videoclips([base_clip, next_clip])

            # 检测GPU编码器
            gpu_codec, gpu_params = detect_gpu_encoder()
            
            # save merged result to temp file
            merged_clip.write_videofile(
                filename=temp_merged_next,
                threads=threads,
                logger=None,
                temp_audiofile_path=output_dir,
                audio_codec=audio_codec,
                fps=fps,
                codec=gpu_codec,
                ffmpeg_params=gpu_params
            )
            close_clip(base_clip)
            close_clip(next_clip)
            close_clip(merged_clip)
            
            # replace base file with new merged file
            delete_files(temp_merged_video)
            os.rename(temp_merged_next, temp_merged_video)
            
        except Exception as e:
            logger.error(f"failed to merge clip: {str(e)}")
            continue
    
    # after merging, rename final result to target file name
    os.rename(temp_merged_video, combined_video_path)
    
    # clean temp files
    clip_files = [clip.file_path for clip in processed_clips]
    delete_files(clip_files)
            
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    return result, height


def create_bamboo_scroll_subtitles(
    subtitle_items,
    font_path,
    font_size,
    video_width,
    video_height,
    text_color="#FFD700",
    stroke_color="#8B4513",
    stroke_width=2,
    video_duration=None,
    x_offset=0,
    y_offset=0
):
    """
    创建竖简式多列字幕布局（古书卷轴模式）
    
    特点：
    1. 从右向左排列多列
    2. 每列从上到下填充
    3. 根据屏幕高度和字体大小计算每列最大字数
    4. 自动计算可容纳列数
    5. 三色高亮：未读（灰色）、正在读（金色）、已读（棕色）
    
    参数:
        x_offset: 水平偏移量（百分比）
        y_offset: 垂直偏移量（百分比）
    """
    font_size = int(font_size)
    stroke_width = int(stroke_width)
    
    if video_duration is None:
        video_duration = subtitle_items[-1][0][1] if subtitle_items else 10
    
    # 判断视频方向（根据快速模式优化）
    is_portrait = video_height > video_width  # 竖屏
    
    if is_portrait:
        # 竖屏（9:16）：字体更大，列数更少，列间距适中
        base_left = 0.10 + (x_offset / 100.0)
        base_right = 0.70 + (x_offset / 100.0)
        base_y = 0.12 + (y_offset / 100.0)
        column_spacing_multiplier = 1.5  # 列间距倍数：1.5倍字体大小
        max_columns = 6  # 6列
    else:
        # 横屏（16:9）：字体适中，更多列，列间距更小
        base_left = 0.18 + (x_offset / 100.0)
        base_right = 0.80 + (x_offset / 100.0)  # 80%（水平离标题更近）
        base_y = 0.12 + (y_offset / 100.0)
        column_spacing_multiplier = 0.75  # 列间距倍数：0.75倍字体大小（减半）
        max_columns = 15  # 15列（列间距减半后可放更多列）
    
    left_boundary = int(video_width * base_left)   # 左边界
    right_boundary = int(video_width * base_right)  # 右边界
    y_start = int(video_height * base_y)            # 上边界
    
    # 计算每列可容纳的最大字数（使用1.4倍字符间距）
    char_spacing = int(font_size * 1.4)
    available_height = video_height * 0.76  # 12%-88%区域
    max_chars_per_column = int(available_height / char_spacing)
    
    # 计算列间距（根据视频比例使用不同的倍数）
    column_spacing = int(font_size * column_spacing_multiplier)
    
    logger.info(f"🎋 竖简布局: {'9:16 竖屏' if is_portrait else '16:9 横屏'}, 每列{max_chars_per_column}字, {max_columns}列, 区域{left_boundary}-{right_boundary}px")
    
    all_clips = []
    
    # 将所有字幕文本连接起来，在每句之间添加空格分隔
    text_parts = []
    for item in subtitle_items:
        text_parts.append(item[1].strip())
    all_text = " ".join(text_parts)  # 使用空格连接每句，作为分隔符
    total_chars = len(all_text)
    
    # 计算字符到时间的映射
    char_to_time = {}
    char_index = 0
    for item in subtitle_items:
        start_time, end_time = item[0]
        text = item[1].strip()
        duration = end_time - start_time
        char_duration = duration / len(text) if len(text) > 0 else duration
        
        for i, char in enumerate(text):
            char_start = start_time + i * char_duration
            char_end = char_start + char_duration
            char_to_time[char_index] = (char_start, char_end)
            char_index += 1
        
        # 为空格分隔符分配时间（使用当前句子的结束时间）
        if char_index < total_chars:  # 如果还有空格分隔符
            char_to_time[char_index] = (end_time, end_time)  # 空格不显示，时间为0
            char_index += 1
    
    # 从右向左排列字符（使用线性插值确保精确覆盖整个区域）
    char_index = 0
    for col in range(max_columns):
        if char_index >= total_chars:
            break
        
        # 计算当前列的 x 位置（从右到左，使用线性插值）
        if max_columns > 1:
            # 线性插值：从右(right_boundary)到左(left_boundary)
            x_position = right_boundary - int((right_boundary - left_boundary) * col / (max_columns - 1))
        else:
            x_position = right_boundary
        
        # 填充当前列
        for row in range(max_chars_per_column):
            if char_index >= total_chars:
                break
            
            char = all_text[char_index]
            char_start, char_end = char_to_time[char_index]
            
            # 计算 y 位置
            y_position = y_start + row * char_spacing
            
            # 确定字符状态：未读（灰色）、正在读（金色）、已读（棕色）
            # 未读状态：从视频开始到当前字开始
            unread_clip = TextClip(
                text=char,
                font=font_path,
                font_size=font_size,
                color="#000000",  # 黑色
                stroke_color=stroke_color,
                stroke_width=stroke_width,
            )
            unread_clip = unread_clip.with_start(0).with_duration(char_start)
            unread_clip = unread_clip.with_position((x_position, y_position))
            if char_start > 0:
                all_clips.append(unread_clip)
            
            # 正在读状态：当前字正在朗读时
            reading_clip = TextClip(
                text=char,
                font=font_path,
                font_size=int(font_size * 1.1),  # 略微放大
                color="#FFD700",  # 金色高亮
                stroke_color="#8B4513",  # 棕色描边
                stroke_width=stroke_width,
            )
            reading_clip = reading_clip.with_start(char_start).with_duration(char_end - char_start)
            reading_clip = reading_clip.with_position((x_position, y_position))
            all_clips.append(reading_clip)
            
            # 已读状态：当前字读完到视频结束
            read_clip = TextClip(
                text=char,
                font=font_path,
                font_size=font_size,
                color="#8B4513",  # 棕色
                stroke_color="#FFD700",  # 金色描边
                stroke_width=stroke_width,
            )
            read_clip = read_clip.with_start(char_end).with_duration(video_duration - char_end)
            read_clip = read_clip.with_position((x_position, y_position))
            if char_end < video_duration:
                all_clips.append(read_clip)
            
            char_index += 1
    
    logger.success(f"✅ 竖简字幕生成完成: {len(all_clips)} 个clip, {char_index} 个字符")
    return all_clips


def create_accumulated_subtitles_for_book_theme(subtitle_items, font_path, font_size, 
                                                 video_width, video_height, theme,
                                                 text_color="#000000", stroke_color="#FFFFFF", 
                                                 stroke_width=2, video_duration=None,
                                                 subtitle_x_offset=0, subtitle_y_offset=0):
    """
    为书籍主题创建追加显示的字幕，当满屏后清空继续显示
    
    Args:
        subtitle_x_offset: 字幕水平偏移量（百分比）
        subtitle_y_offset: 字幕垂直偏移量（百分比）
    """
    font_size = int(font_size)
    stroke_width = int(stroke_width)
    
    # 计算视频总时长（如果没有提供，使用最后一个字幕的结束时间）
    if video_duration is None:
        video_duration = subtitle_items[-1][0][1] if subtitle_items else 10
    
    all_clips = []
    
    if theme == VideoTheme.ancient_scroll.value:
        # 古书卷轴：使用竖简式多列布局
        # 使用传入的偏移量参数
        return create_bamboo_scroll_subtitles(
            subtitle_items=subtitle_items,
            font_path=font_path,
            font_size=font_size,
            video_width=video_width,
            video_height=video_height,
            text_color=text_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            video_duration=video_duration,
            x_offset=subtitle_x_offset,
            y_offset=subtitle_y_offset
        )
    else:  # modern_book
        # 现代图书：横排追加
        x_start = int(video_width * 0.1)
        y_start = int(video_height * 0.3)  # 从30%开始，留出标题空间
        line_height = int(font_size * 1.5)
        max_lines_per_screen = int((video_height * 0.6) / line_height)  # 每屏最多行数
        max_width = int(video_width * 0.8)
        
        accumulated_lines = []
        page_start_time = 0
        
        for idx, item in enumerate(subtitle_items):
            start_time, end_time = item[0]
            text = item[1].strip()
            
            # 计算下一个字幕的开始时间（用于设置当前clip的结束时间）
            next_start_time = subtitle_items[idx + 1][0][0] if idx + 1 < len(subtitle_items) else video_duration
            
            # 添加当前文本到累积行
            accumulated_lines.append((text, start_time, end_time, next_start_time))
            
            # 检查是否需要翻页
            if len(accumulated_lines) > max_lines_per_screen:
                # 清空当前页，开始新页
                accumulated_lines = [(text, start_time, end_time, next_start_time)]
                page_start_time = start_time
            
            # 创建当前页面所有行的clips
            for line_idx, (line_text, line_start, line_end, line_next_start) in enumerate(accumulated_lines):
                y_position = int(y_start + line_idx * line_height)
                
                # 当前正在显示的行使用黑色，已显示的行使用灰色
                if line_start == start_time:
                    # 当前行：黑色
                    line_color = "#000000"
                else:
                    # 之前的行：深灰色
                    line_color = "#404040"
                
                # 自动换行
                wrapped_text, _ = wrap_text(
                    line_text,
                    max_width=max_width,
                    font=font_path,
                    fontsize=font_size
                )
                
                line_clip = TextClip(
                    text=wrapped_text,
                    font=font_path,
                    font_size=font_size,
                    color=line_color,
                    stroke_color=stroke_color,
                    stroke_width=stroke_width,
                )
                
                # 从该行开始显示到下一段落开始
                line_clip = line_clip.with_start(line_start)
                line_clip = line_clip.with_duration(line_next_start - line_start)
                line_clip = line_clip.with_position((x_start, y_position))
                all_clips.append(line_clip)
    
    return all_clips


def create_vertical_text_clips(text, font_path, font_size, video_width, video_height, 
                               start_time, end_time, text_color="#FFFFFF", 
                               stroke_color="#000000", stroke_width=2):
    """
    创建竖排字幕，用于古书卷轴模式
    字符逐个竖排显示，并在读到时高亮
    """
    chars = list(text.strip())
    char_clips = []
    
    # 确保参数为整数
    font_size = int(font_size)
    stroke_width = int(stroke_width)
    
    # 计算总时长和每个字的显示时间
    total_duration = end_time - start_time
    char_duration = total_duration / len(chars) if len(chars) > 0 else total_duration
    
    # 计算竖排字幕的位置（右侧，留出空间给标题）
    x_position = int(video_width * 0.75)  # 在右侧四分之三处
    y_start = int(video_height * 0.15)  # 从顶部15%开始
    
    for i, char in enumerate(chars):
        char_start = start_time + i * char_duration
        char_end = char_start + char_duration
        
        # 为每个字创建两个状态：普通和高亮
        # 普通状态：白色
        normal_clip = TextClip(
            text=char,
            font=font_path,
            font_size=font_size,
            color=text_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
        )
        
        # 高亮状态：金色
        highlight_clip = TextClip(
            text=char,
            font=font_path,
            font_size=int(font_size * 1.1),  # 略微放大
            color="#FFD700",  # 金色
            stroke_color="#8B4513",  # 棕色描边
            stroke_width=stroke_width,
        )
        
        # 计算y位置
        y_position = int(y_start + i * (font_size + 10))
        
        # 普通状态显示在整个字幕期间
        normal_clip = normal_clip.with_start(start_time).with_duration(total_duration)
        normal_clip = normal_clip.with_position((x_position, y_position))
        
        # 高亮状态只在读到这个字时显示
        highlight_clip = highlight_clip.with_start(char_start).with_duration(char_duration)
        highlight_clip = highlight_clip.with_position((x_position, y_position))
        
        char_clips.append(normal_clip)
        char_clips.append(highlight_clip)
    
    return char_clips


def create_title_clips_for_theme(theme, title_text, font_path, video_width, video_height, 
                                  video_duration, base_font_size=60, stroke_width=2, 
                                  title_x_offset=0, title_y_offset=0):
    """
    根据主题创建标题文本块
    
    参数:
        title_x_offset: 标题水平偏移量（百分比）
        title_y_offset: 标题垂直偏移量（百分比）
    """
    # 确保参数为整数
    base_font_size = int(base_font_size)
    stroke_width = int(stroke_width)
    
    if theme == VideoTheme.cinema.value:
        # 电影模式：开头全屏显示3秒，居中，大字体
        title_font_size = int(base_font_size * 2.5)
        title_stroke_width = int(stroke_width * 2)
        
        # 自动换行
        max_title_width = video_width * 0.8
        wrapped_title, title_height = wrap_text(
            title_text,
            max_width=max_title_width,
            font=font_path,
            fontsize=title_font_size
        )
        
        title_clip = TextClip(
            text=wrapped_title,
            font=font_path,
            font_size=title_font_size,
            color="#FFFFFF",
            stroke_color="#000000",
            stroke_width=title_stroke_width,
        )
        
        # 开头显示3秒，居中
        title_clip = title_clip.with_duration(3)
        title_clip = title_clip.with_start(0)
        title_clip = title_clip.with_position(("center", "center"))
        
        return [title_clip]
        
    elif theme == VideoTheme.ancient_scroll.value:
        # 古书卷轴：右侧竖排，垂直居中，全程显示
        # 应用水平和垂直偏移量
        title_font_size = int(base_font_size * 1.2)
        title_stroke_width = int(stroke_width * 1.5)
        
        # 将标题文字竖排
        chars = list(title_text)
        char_clips = []
        
        # 应用偏移量（百分比）
        base_x = 0.85 + (title_x_offset / 100.0)  # 85%位置 + 偏移
        
        x_position = int(video_width * base_x)
        
        # 计算标题总高度并垂直居中
        char_height = title_font_size + 5
        title_height = len(chars) * char_height
        y_start = int((video_height - title_height) / 2) + int(video_height * (title_y_offset / 100.0))  # 垂直居中 + 偏移
        
        logger.info(f"🎋 古书卷轴标题: X={base_x*100:.1f}%, Y=垂直居中")
        
        for i, char in enumerate(chars):
            char_clip = TextClip(
                text=char,
                font=font_path,
                font_size=title_font_size,
                color="#8B4513",  # 棕色，古书效果
                stroke_color="#FFD700",  # 金色描边
                stroke_width=title_stroke_width,
            )
            
            y_position = int(y_start + i * char_height)
            char_clip = char_clip.with_duration(video_duration)
            char_clip = char_clip.with_start(0)
            char_clip = char_clip.with_position((x_position, y_position))
            char_clips.append(char_clip)
        
        return char_clips
        
    elif theme == VideoTheme.minimal.value:
        # 简约模式：居中靠上，全程显示
        title_font_size = int(base_font_size * 1.8)
        title_stroke_width = int(stroke_width * 1.5)
        
        max_title_width = video_width * 0.8
        wrapped_title, title_height = wrap_text(
            title_text,
            max_width=max_title_width,
            font=font_path,
            fontsize=title_font_size
        )
        
        title_clip = TextClip(
            text=wrapped_title,
            font=font_path,
            font_size=title_font_size,
            color="#FFFFFF",
            stroke_color="#000000",
            stroke_width=title_stroke_width,
        )
        
        title_clip = title_clip.with_duration(video_duration)
        title_clip = title_clip.with_start(0)
        # 顶部10%处
        title_clip = title_clip.with_position(("center", int(video_height * 0.1)))
        
        return [title_clip]
        
    else:  # modern_book 或默认
        # 现代图书模式：顶部居中（书皮），全程显示
        title_font_size = int(base_font_size * 1.5)
        title_stroke_width = int(stroke_width * 1.5)
        
        max_title_width = video_width * 0.8
        wrapped_title, title_height = wrap_text(
            title_text,
            max_width=max_title_width,
            font=font_path,
            fontsize=title_font_size
        )
        
        title_clip = TextClip(
            text=wrapped_title,
            font=font_path,
            font_size=title_font_size,
            color="#000000",  # 黑色标题
            stroke_color="#FFFFFF",  # 白色描边
            stroke_width=title_stroke_width,
        )
        
        title_clip = title_clip.with_duration(video_duration)
        title_clip = title_clip.with_start(0)
        # 顶部20%处
        title_clip = title_clip.with_position(("center", int(video_height * 0.2)))
        
        return [title_clip]


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "LXGWWenKai-Regular.ttf"
        
        font_path = os.path.join(utils.font_dir(), params.font_name)
        
        # 如果默认字体不存在，使用备用字体
        if not os.path.exists(font_path):
            fallback_fonts = [
                "STHeitiMedium.ttc",
                "MicrosoftYaHeiNormal.ttc",
                "STHeitiLight.ttc",
            ]
            for fallback in fallback_fonts:
                fallback_path = os.path.join(utils.font_dir(), fallback)
                if os.path.exists(fallback_path):
                    logger.warning(f"font {params.font_name} not found, using fallback: {fallback}")
                    font_path = fallback_path
                    params.font_name = fallback
                    break
        
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ font: {font_path}")
    
    # 如果没有字体路径但有视频标题，使用默认字体
    if not font_path and params.video_subject:
        params.font_name = "LXGWWenKai-Regular.ttf"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        
        # 如果默认字体不存在，使用备用字体
        if not os.path.exists(font_path):
            fallback_fonts = ["STHeitiMedium.ttc", "MicrosoftYaHeiNormal.ttc"]
            for fallback in fallback_fonts:
                fallback_path = os.path.join(utils.font_dir(), fallback)
                if os.path.exists(fallback_path):
                    font_path = fallback_path
                    params.font_name = fallback
                    break
        
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        interline = int(params.font_size * 0.25)
        size=(int(max_width), int(txt_height + params.font_size * 0.25 + (interline * (wrapped_txt.count("\n") + 1))))

        _clip = TextClip(
            text=wrapped_txt,
            font=font_path,
            font_size=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            # interline=interline,
            # size=size,
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "bottom_20":
            # 距离底部20%的位置
            _clip = _clip.with_position(("center", video_height * 0.8 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.with_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # Ensure the subtitle is fully within the screen bounds
            margin = 10  # Additional margin, in pixels
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(
                min_y, min(custom_y, max_y)
            )  # Constrain the y value within the valid range
            _clip = _clip.with_position(("center", custom_y))
        else:  # center
            _clip = _clip.with_position(("center", "center"))
        return _clip

    video_clip = VideoFileClip(video_path).without_audio()
    audio_clip = AudioFileClip(audio_path).with_effects(
        [afx.MultiplyVolume(params.voice_volume)]
    )

    def make_textclip(text):
        return TextClip(
            text=text,
            font=font_path,
            font_size=params.font_size,
        )

    if subtitle_path and os.path.exists(subtitle_path):
        logger.info(f"  ⑥ adding subtitles (theme: {params.video_theme})...")
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        
        # 根据主题选择不同的字幕样式
        theme = params.video_theme if hasattr(params, 'video_theme') else VideoTheme.modern_book.value
        
        if theme == VideoTheme.ancient_scroll.value or theme == VideoTheme.modern_book.value:
            # 古书卷轴和现代图书模式：使用追加显示，满屏后翻页
            logger.info(f"  using accumulated subtitle display with page turning")
            
            # 获取字幕偏移量参数（如果有）
            subtitle_x_offset = getattr(params, 'subtitle_x_offset', 0)
            subtitle_y_offset = getattr(params, 'subtitle_y_offset', 0)
            
            # 使用音频时长作为video_duration，确保所有字幕都能显示
            # 对于静态图片+音频，video_clip.duration可能不准确，audio_clip.duration才是完整时长
            total_duration = max(audio_clip.duration, video_clip.duration)
            logger.info(f"  total duration: video={video_clip.duration:.2f}s, audio={audio_clip.duration:.2f}s, using={total_duration:.2f}s")
            
            text_clips = create_accumulated_subtitles_for_book_theme(
                subtitle_items=sub.subtitles,
                font_path=font_path,
                font_size=params.font_size,
                video_width=video_width,
                video_height=video_height,
                theme=theme,
                text_color="#000000" if theme == VideoTheme.modern_book.value else params.text_fore_color,
                stroke_color=params.stroke_color,
                stroke_width=params.stroke_width,
                video_duration=total_duration,
                subtitle_x_offset=subtitle_x_offset,
                subtitle_y_offset=subtitle_y_offset
            )
        else:
            # 其他模式：使用传统横排字幕
            for item in sub.subtitles:
                clip = create_text_clip(subtitle_item=item)
                text_clips.append(clip)
        
        video_clip = CompositeVideoClip([video_clip, *text_clips])
        logger.success(f"  ✓ subtitles added ({len(text_clips)} clips)")        
    
    # 添加视频标题显示（根据主题）
    if params.video_subject and font_path:
        try:
            theme = params.video_theme if hasattr(params, 'video_theme') else VideoTheme.modern_book.value
            logger.info(f"  ⑦ adding title: {params.video_subject} (theme: {theme})")
            
            # 获取标题偏移量参数（如果有）
            title_x_offset = getattr(params, 'title_x_offset', 0)
            title_y_offset = getattr(params, 'title_y_offset', 0)
            
            # 使用与video_clip相同的时长（已经包含了字幕）
            current_duration = video_clip.duration
            
            # 根据主题创建标题
            title_clips = create_title_clips_for_theme(
                theme=theme,
                title_text=params.video_subject,
                font_path=font_path,
                video_width=video_width,
                video_height=video_height,
                video_duration=current_duration,
                base_font_size=params.font_size,
                stroke_width=params.stroke_width,
                title_x_offset=title_x_offset,
                title_y_offset=title_y_offset
            )
            
            # 将标题叠加到视频上
            video_clip = CompositeVideoClip([video_clip, *title_clips])
            
            logger.success(f"  ✓ title added successfully ({len(title_clips)} clips, theme: {theme})")
        except Exception as e:
            logger.error(f"failed to add title: {str(e)}")
            import traceback
            traceback.print_exc()

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            logger.info(f"  ⑦ adding background music: {os.path.basename(bgm_file)}")
            bgm_clip = AudioFileClip(bgm_file).with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ]
            )
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
            logger.success(f"  ✓ background music added")
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")
    
    logger.info(f"  ⑧ starting final video encoding (this may take a while)...")
    video_clip = video_clip.with_audio(audio_clip)
    
    import time
    encode_start = time.time()
    
    # 检测GPU编码器
    gpu_codec, gpu_params = detect_gpu_encoder()
    
    # 使用最优线程数
    optimal_threads = params.n_threads if params.n_threads else get_optimal_threads()
    
    # 构建完整的ffmpeg参数
    ffmpeg_params = gpu_params + [
        '-movflags', '+faststart',
    ]
    
    video_clip.write_videofile(
        output_file,
        audio_codec=audio_codec,
        codec=gpu_codec,  # 使用GPU编码器
        temp_audiofile_path=output_dir,
        threads=optimal_threads,
        logger=None,
        fps=fps,
        ffmpeg_params=ffmpeg_params
    )
    
    encode_time = time.time() - encode_start
    logger.success(f"  ✓ final video encoding completed in {encode_time:.1f}s")
    
    video_clip.close()
    del video_clip


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    if not materials:
        logger.warning("no materials provided for preprocessing")
        return []
    
    # 优化：如果只有一个图片素材，不需要预处理，直接返回
    # 将在combine_videos中直接生成视频，避免不必要的转换
    if len(materials) == 1:
        material = materials[0]
        ext = utils.parse_extension(material.url)
        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"detected single image material, skipping preprocessing for optimization")
            # 验证图片尺寸
            try:
                clip = ImageClip(material.url)
                width, height = clip.size
                close_clip(clip)
                if width < 480 or height < 480:
                    logger.warning(f"low resolution material: {width}x{height}, minimum 480x480 required")
                    return []
                logger.success(f"single image material validated: {width}x{height}")
                return materials  # 直接返回原始图片路径
            except Exception as e:
                logger.error(f"failed to validate image: {str(e)}")
                return []
    
    # 多个素材或非图片素材，走原有逻辑
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"low resolution material: {width}x{height}, minimum 480x480 required")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # Create an image clip and set its duration to 3 seconds
            clip = (
                ImageClip(material.url)
                .with_duration(clip_duration)
                .with_position("center")
            )
            # Apply a zoom effect using the resize method.
            # A lambda function is used to make the zoom effect dynamic over time.
            # The zoom effect starts from the original size and gradually scales up to 120%.
            # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
            # Note: 1 represents 100% size, so 1.2 represents 120% size.
            zoom_clip = clip.resized(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # Optionally, create a composite video clip containing the zoomed clip.
            # This is useful when you want to add other elements to the video.
            final_clip = CompositeVideoClip([zoom_clip])

            # Output the video to a file.
            video_file = f"{material.url}.mp4"
            
            # 检测GPU编码器
            gpu_codec, gpu_params = detect_gpu_encoder()
            
            final_clip.write_videofile(
                video_file, 
                fps=30, 
                logger=None,
                codec=gpu_codec,
                ffmpeg_params=gpu_params
            )
            close_clip(clip)
            material.url = video_file
            logger.success(f"image processed: {video_file}")
    return materials