import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import video_fast  # 快速视频生成模式
from app.services import state as sm
from app.utils import utils


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def generate_audio(task_id, params, video_script):
    logger.info("\n\n## generating audio")
    audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
    sub_maker = voice.tts(
        text=video_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
    )
    if sub_maker is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
        """.strip()
        )
        return None, None, None

    audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
    return audio_file, audio_duration, sub_maker


def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
            )
            return None
        return downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path
):
    final_video_paths = []
    combined_video_paths = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        
        # 检查是否启用快速模式
        enable_fast_mode = getattr(params, 'enable_fast_mode', True)
        
        # 检查是否为单张静态图片
        is_single_image = False
        if len(downloaded_videos) == 1:
            single_path = downloaded_videos[0]
            ext = utils.parse_extension(single_path)
            if ext in const.FILE_TYPE_IMAGES:
                is_single_image = True
        
        # 如果启用快速模式且不需要过渡效果，直接使用快速生成
        # 注意：VideoTransitionMode 继承 str，所以 none.value 是字符串 "None" 而不是 Python 的 None
        use_fast_generation = (
            enable_fast_mode and 
            subtitle_path and 
            (not video_transition_mode or video_transition_mode.value is None or video_transition_mode.value == "None")  # 快速模式不支持过渡效果
            # 注意：单张图片也支持快速模式（使用专门的图片快速生成函数）
        )
        
        # 打印快速模式检查日志
        if enable_fast_mode:
            logger.info("\n" + "="*60)
            logger.info("⚡ 快速模式检查：")
            logger.info(f"  ✓ 用户选择：快速模式")
            logger.info(f"  {'✓' if subtitle_path else '✗'} 字幕文件：{'存在' if subtitle_path else '不存在（快速模式需要字幕）'}")
            
            # 检查转场模式（处理None的情况）
            # video_transition_mode 本身是枚举对象，需要检查其 .value 属性
            logger.debug(f"  [DEBUG] video_transition_mode = {video_transition_mode}")
            logger.debug(f"  [DEBUG] type(video_transition_mode) = {type(video_transition_mode)}")
            if video_transition_mode:
                logger.debug(f"  [DEBUG] video_transition_mode.value = {video_transition_mode.value}")
                logger.debug(f"  [DEBUG] type(video_transition_mode.value) = {type(video_transition_mode.value)}")
                logger.debug(f"  [DEBUG] video_transition_mode.value is None = {video_transition_mode.value is None}")
                logger.debug(f"  [DEBUG] video_transition_mode.value == 'None' = {video_transition_mode.value == 'None'}")
            
            # 注意：VideoTransitionMode 继承 str，所以 none.value 是字符串 "None"
            is_no_transition = (not video_transition_mode or video_transition_mode.value is None or video_transition_mode.value == "None")
            logger.debug(f"  [DEBUG] is_no_transition = {is_no_transition}")
            
            transition_display = "无转场" if is_no_transition else str(video_transition_mode.value)
            logger.info(f"  {'✓' if is_no_transition else '✗'} 转场模式：{transition_display} {'(符合要求)' if is_no_transition else '(需要设置为: 无转场)'}")
            
            logger.info(f"  ✓ 素材类型：{'单张图片（支持快速模式）' if is_single_image else '视频素材（支持快速模式）'}")
            
            # 调试信息：显示快速模式判断结果
            logger.debug(f"  [DEBUG] use_fast_generation = {use_fast_generation}")
            logger.debug(f"  [DEBUG] enable_fast_mode = {enable_fast_mode}, subtitle_path = {bool(subtitle_path)}, is_no_transition = {is_no_transition}")
            
            if use_fast_generation:
                logger.info("  ✅ 所有条件满足，启用快速模式！")
                if is_single_image:
                    logger.info("  🖼️  将使用专门的图片快速生成功能（FFmpeg直接处理）")
            else:
                logger.warning("  ⚠️  条件不满足，自动切换到标准模式")
                # 详细说明哪个条件不满足
                if not is_no_transition:
                    logger.warning(f"  💡 提示：将【视频转场模式】设置为【无转场】即可使用快速模式")
                    logger.warning(f"      当前转场模式值：{video_transition_mode} (value={video_transition_mode.value if video_transition_mode else None})")
                if not subtitle_path:
                    logger.warning(f"  💡 提示：快速模式需要启用字幕")
            logger.info("="*60 + "\n")
        
        if use_fast_generation:
            logger.info("\n" + "="*60)
            logger.info("⚡⚡⚡ 快速生成模式已启用 ⚡⚡⚡")
            
            # 区分单张图片和多视频素材
            if is_single_image:
                logger.info("🖼️  使用图片快速生成功能 (FFmpeg直接处理)")
                logger.info("⏱️  预计速度提升: 10-15倍")
            else:
                logger.info("🚀 使用 FFmpeg concat + stream copy (无重新编码)")
                logger.info("⏱️  预计速度提升: 10-20倍")
            
            logger.info("💾 输出文件更小，CPU/GPU使用率更低")
            logger.info("="*60 + "\n")
            
            final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")
            bgm_file = video.get_bgm_file(params.bgm_type, params.bgm_file)
            
            # 根据是否为单张图片选择不同的快速生成方法
            if is_single_image:
                # 单张图片：使用FFmpeg一步生成（图片+音频+字幕）
                from app.models.schema import VideoAspect
                aspect = VideoAspect(params.video_aspect)
                video_width, video_height = aspect.to_resolution()
                
                logger.info("  - 使用FFmpeg快速生成视频（图片+音频+字幕）...")
                
                result = video_fast.generate_video_from_image_fast(
                    image_path=downloaded_videos[0],
                    audio_file=audio_file,
                    subtitle_file=subtitle_path,
                    output_path=final_video_path,
                    video_width=video_width,
                    video_height=video_height,
                    background_music=bgm_file,
                    bgm_volume=params.bgm_volume if params.bgm_volume else 0.2,
                    video_subject=params.video_subject if hasattr(params, 'video_subject') else None,
                    video_theme=params.video_theme if hasattr(params, 'video_theme') else None,
                    subtitle_color_theme=params.subtitle_color_theme if hasattr(params, 'subtitle_color_theme') else "classic_gold",
                )
            else:
                # 多视频素材使用普通的快速拼接
                result = video_fast.generate_video_fast(
                    video_paths=downloaded_videos,
                    audio_file=audio_file,
                    subtitle_file=subtitle_path,
                    output_path=final_video_path,
                    video_aspect=params.video_aspect,
                    background_music=bgm_file,
                    bgm_volume=params.bgm_volume if params.bgm_volume else 0.2,
                    auto_normalize=True,  # 自动规范化素材
                )
            
            if result:
                logger.info("\n" + "✅"*20)
                logger.success("⚡ 快速模式生成成功！")
                logger.info(f"🎬 输出文件: {path.basename(final_video_path)}")
                logger.info("✅"*20 + "\n")
                final_video_paths.append(final_video_path)
                combined_video_paths.append(final_video_path)  # 快速模式不需要combined文件
            else:
                logger.warning("\n" + "⚠️ "*15)
                logger.warning("⚠️  快速模式失败，自动回退到标准模式...")
                logger.warning("⚠️ "*15 + "\n")
                use_fast_generation = False
        
        # 如果不使用快速模式或快速模式失败，使用标准流程
        if not use_fast_generation:
            # 只有用户主动选择标准模式时才显示详细日志
            if not enable_fast_mode:
                logger.info("\n" + "="*60)
                logger.info("🎬🎬🎬 标准生成模式已启用 🎬🎬🎬")
                logger.info("🎨 使用 MoviePy 完整处理流程")
                logger.info("✨ 支持所有过渡效果和高级功能")
                logger.info("🔧 最大灵活性和质量控制")
                logger.info("="*60 + "\n")
            elif is_single_image:
                # 单张图片情况的特别说明
                logger.info("\n" + "="*60)
                logger.info("🖼️  单张图片优化模式")
                logger.info("🚀 使用优化的图片转视频流程")
                logger.info("✨ 支持缩放动画效果")
                logger.info(f"💾 动画效果：{'已启用' if params.enable_video_animation else '已禁用（更快）'}")
                logger.info("="*60 + "\n")
            
            video.combine_videos(
                combined_video_path=combined_video_path,
                video_paths=downloaded_videos,
                audio_file=audio_file,
                video_aspect=params.video_aspect,
                video_concat_mode=video_concat_mode,
                video_transition_mode=video_transition_mode,
                max_clip_duration=params.video_clip_duration,
                threads=params.n_threads,
                enable_animation=params.enable_video_animation,
            )

            _progress += 50 / params.video_count / 2
            sm.state.update_task(task_id, progress=_progress)

            final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

            logger.info(f"\n\n## generating video: {index} => {final_video_path}")
            video.generate_video(
                video_path=combined_video_path,
                audio_path=audio_file,
                subtitle_path=subtitle_path,
                output_file=final_video_path,
                params=params,
            )
            
            final_video_paths.append(final_video_path)
            combined_video_paths.append(combined_video_path)

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Generate audio
    audio_file, audio_duration, sub_maker = generate_audio(
        task_id, params, video_script
    )
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    subtitle_path = generate_subtitle(
        task_id, params, video_script, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Get video materials
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
