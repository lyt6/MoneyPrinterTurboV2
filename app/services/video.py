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
)
from app.services.utils import video_effects
from app.utils import utils

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
        
        # 使用更快的编码预设
        output_dir = os.path.dirname(output_path)
        final_clip.write_videofile(
            output_path,
            fps=fps,
            codec=video_codec,
            preset='ultrafast',  # 使用最快的编码预设
            threads=threads,
            logger=None,
            audio=False,  # 不包含音频
            temp_audiofile_path=output_dir,
            ffmpeg_params=[
                '-crf', '23',  # 质量参数（18-28，越小质量越好）
                '-movflags', '+faststart',  # 优化web播放
            ]
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
            clip.write_videofile(
                clip_file, 
                logger=None, 
                fps=fps, 
                codec=video_codec,
                preset='ultrafast'  # 快速编码
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

            # save merged result to temp file
            merged_clip.write_videofile(
                filename=temp_merged_next,
                threads=threads,
                logger=None,
                temp_audiofile_path=output_dir,
                audio_codec=audio_codec,
                fps=fps,
                preset='ultrafast',  # 快速编码
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
        logger.info(f"  ⑥ adding subtitles...")
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])
        logger.success(f"  ✓ subtitles added ({len(text_clips)} segments)")
    
    # 添加视频标题显示（全程显示）
    if params.video_subject and font_path:
        try:
            logger.info(f"  ⑥ adding title: {params.video_subject}")
            
            # 标题字体大小比字幕更大
            title_font_size = int(params.font_size * 1.5)
            title_stroke_width = int(params.stroke_width * 1.5)
            
            # 自动换行
            max_title_width = video_width * 0.8
            wrapped_title, title_height = wrap_text(
                params.video_subject,
                max_width=max_title_width,
                font=font_path,
                fontsize=title_font_size
            )
            
            # 创建标题文本
            title_clip = TextClip(
                text=wrapped_title,
                font=font_path,
                font_size=title_font_size,
                color="#FFFFFF",
                stroke_color="#000000",
                stroke_width=title_stroke_width,
            )
            
            # 标题全程显示，与视频时长一致
            title_clip = title_clip.with_duration(video_clip.duration)
            title_clip = title_clip.with_start(0)
            
            # 位置：水平居中，垂直位置在画面上方，距离顶部20%处（标题通常位置）
            title_y_position = int(video_height * 0.2)
            title_clip = title_clip.with_position(("center", title_y_position))
            
            # 将标题叠加到视频上
            video_clip = CompositeVideoClip([video_clip, title_clip])
            
            logger.success(f"  ✓ title added successfully (full duration)")
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
    
    video_clip.write_videofile(
        output_file,
        audio_codec=audio_codec,
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger=None,
        fps=fps,
        preset='ultrafast',  # 快速编码
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
            final_clip.write_videofile(
                video_file, 
                fps=30, 
                logger=None,
                preset='ultrafast'  # 快速编码
            )
            close_clip(clip)
            material.url = video_file
            logger.success(f"image processed: {video_file}")
    return materials