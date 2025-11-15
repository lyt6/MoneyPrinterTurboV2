"""
快速视频生成服务 - 避免重复编码
使用FFmpeg直接拼接和叠加，速度提升95%以上
"""
import os
import subprocess
import shutil
from loguru import logger
from typing import List, Tuple, Optional
from app.models.schema import VideoAspect
from app.config.subtitle_themes import get_subtitle_theme_colors  # 导入颜色主题配置


def find_ffmpeg() -> Optional[str]:
    """
    查找ffmpeg可执行文件路径
    优先级：
    1. 系统PATH中的ffmpeg
    2. MoviePy/imageio_ffmpeg内置的ffmpeg
    3. 常见安装位置
    4. 直接尝试执行ffmpeg（即使which找不到）
    
    Returns:
        ffmpeg路径，如果未找到则返回None
    """
    # 1. 检查系统PATH
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        logger.debug(f"找到系统ffmpeg: {ffmpeg_path}")
        return ffmpeg_path
    
    # 2. 直接尝试执行ffmpeg命令（有时PATH已更新但shutil.which检测不到）
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            logger.info("✅ ffmpeg命令可执行（在系统PATH中），但shutil.which未检测到")
            logger.info("💡 这是正常的，将直接使用'ffmpeg'命令")
            return 'ffmpeg'  # 直接返回命令名
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    
    # 3. 检查imageio_ffmpeg（MoviePy内置）
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_path):
            logger.info(f"使用imageio_ffmpeg内置版本: {ffmpeg_path}")
            return ffmpeg_path
    except ImportError:
        pass
    
    # 4. 检查常见Windows安装位置
    if os.name == 'nt':  # Windows
        common_paths = [
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"找到ffmpeg: {path}")
                return path
    
    logger.warning("未找到ffmpeg可执行文件")
    return None


def normalize_video_materials(
    video_paths: List[str],
    output_dir: str,
    target_width: int,
    target_height: int,
) -> Tuple[List[str], bool]:
    """
    规范化视频素材 - 统一编码格式，为快速拼接做准备
    
    策略：将所有素材转换为统一的编码格式（H.264 + AAC + 30fps）
    这样后续拼接时可以使用 -c copy 直接复制流，不需要重新编码
    
    Args:
        video_paths: 原始视频素材路径列表
        output_dir: 输出目录
        target_width: 目标宽度
        target_height: 目标高度
        
    Returns:
        (normalized_paths, is_already_compatible)
        - normalized_paths: 规范化后的视频路径列表
        - is_already_compatible: 是否所有素材已经兼容（无需转换）
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        logger.warning("未找到ffmpeg，无法规范化素材")
        return video_paths, False
    
    normalized_paths = []
    need_normalize = False
    
    # 检测第一个视频的编码参数作为基准
    probe_cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,r_frame_rate',
        '-of', 'default=noprint_wrappers=1',
        video_paths[0]
    ]
    
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        base_info = result.stdout
        logger.info(f"基准素材信息: {base_info}")
    except:
        base_info = None
    
    # 逐个检查和转换素材
    for i, video_path in enumerate(video_paths):
        # 检测当前视频参数
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,width,height,r_frame_rate',
            '-of', 'default=noprint_wrappers=1',
            video_path
        ]
        
        try:
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            current_info = result.stdout
            
            # 如果与基准不一致，需要规范化
            if base_info and current_info != base_info:
                need_normalize = True
                logger.info(f"素材 {i+1} 格式不一致，需要规范化")
            
        except:
            need_normalize = True
        
        if need_normalize:
            # 转换为标准格式
            normalized_path = os.path.join(output_dir, f"normalized_{i+1}.mp4")
            
            normalize_cmd = [
                ffmpeg_path,
                '-i', video_path,
                '-vf', f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264',      # 统一使用H.264
                '-preset', 'fast',       # 平衡速度和质量
                '-crf', '23',            # 质量参数
                '-r', '30',              # 统一30fps
                '-c:a', 'aac',           # 统一AAC音频
                '-b:a', '128k',
                '-pix_fmt', 'yuv420p',   # 统一像素格式
                '-y',
                normalized_path
            ]
            
            logger.info(f"⚙️ 规范化素材 {i+1}/{len(video_paths)}...")
            result = subprocess.run(normalize_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                normalized_paths.append(normalized_path)
                logger.info(f"✅ 素材 {i+1} 规范化完成")
            else:
                logger.error(f"❌ 素材 {i+1} 规范化失败: {result.stderr}")
                normalized_paths.append(video_path)  # 失败则使用原文件
        else:
            normalized_paths.append(video_path)
    
    is_compatible = not need_normalize
    if is_compatible:
        logger.info("✅ 所有素材已兼容，可直接快速拼接")
    else:
        logger.info("⚙️ 素材已规范化为统一格式，可进行快速拼接")
    
    return normalized_paths, is_compatible


def generate_video_fast(
    video_paths: List[str],
    audio_file: str,
    subtitle_file: str,
    output_path: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    background_music: str = None,
    bgm_volume: float = 0.2,
    auto_normalize: bool = True,  # 新增：是否自动规范化素材
) -> str:
    """
    快速生成视频 - 使用FFmpeg直接拼接，避免重新编码
    
    工作流程：
    1. 检测素材是否兼容（编码格式、分辨率、帧率是否一致）
    2. 如果不兼容：
       - auto_normalize=True: 自动规范化素材为统一格式
       - auto_normalize=False: 回退到标准重编码模式
    3. 使用 -c copy 快速拼接（无需编码）
    4. 最后叠加音频和字幕（仅编码一次）
    
    Args:
        video_paths: 视频素材路径列表
        audio_file: 音频文件路径
        subtitle_file: 字幕文件路径（ASS或SRT格式）
        output_path: 输出视频路径
        video_aspect: 视频比例
        background_music: 背景音乐路径
        bgm_volume: 背景音乐音量
        auto_normalize: 是否自动规范化不兼容的素材
        
    Returns:
        生成的视频文件路径
    """
    try:
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            logger.error("未找到ffmpeg，无法使用快速生成模式")
            logger.info("💡 提示：")
            logger.info("  1. 如果已安装ffmpeg：")
            logger.info("     - 完全关闭当前终端窗口")
            logger.info("     - 打开新的PowerShell窗口")
            logger.info("     - 测试: ffmpeg -version")
            logger.info("     - 在新窗口中运行: .\\webui.bat")
            logger.info("  2. 如果未安装ffmpeg：")
            logger.info("     - 使用: winget install Gyan.FFmpeg")
            logger.info("  3. 将自动回退到标准模式（使用MoviePy内置ffmpeg）")
            logger.info("")
            return None
        
        output_dir = os.path.dirname(output_path)
        aspect = VideoAspect(video_aspect)
        video_width, video_height = aspect.to_resolution()
        
        # ✨ 新增：自动规范化素材
        if auto_normalize:
            logger.info("🔍 检测素材兼容性...")
            video_paths, is_compatible = normalize_video_materials(
                video_paths=video_paths,
                output_dir=output_dir,
                target_width=video_width,
                target_height=video_height
            )
            
            if not is_compatible:
                logger.info("⚙️ 素材已自动规范化为统一格式，开始快速拼接...")
        
        temp_concat_file = os.path.join(output_dir, "concat_list.txt")
        temp_video_only = os.path.join(output_dir, "temp_video_only.mp4")
        
        # 1. 创建视频拼接列表
        with open(temp_concat_file, 'w', encoding='utf-8') as f:
            for video_path in video_paths:
                # FFmpeg concat格式，路径需要转义
                safe_path = video_path.replace("\\", "/").replace("'", "\\'")
                f.write(f"file '{safe_path}'\n")
        
        logger.info("⚡ 快速模式：开始拼接视频素材...")
        
        # 2. 使用concat协议快速拼接视频（不重新编码）
        concat_cmd = [
            ffmpeg_path,
            '-f', 'concat',
            '-safe', '0',
            '-i', temp_concat_file,
            '-c', 'copy',  # 关键：不重新编码，直接复制流
            '-y',
            temp_video_only
        ]
        
        result = subprocess.run(concat_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"视频拼接失败: {result.stderr}")
            # 回退：如果拼接失败（编码不一致），使用重新编码
            logger.warning("拼接失败，使用重新编码模式...")
            return _generate_with_reencode(
                video_paths, audio_file, subtitle_file, output_path,
                video_aspect, background_music, bgm_volume
            )
        
        logger.info("✅ 视频拼接完成（无重新编码）")
        
        # 3. 使用MoviePy叠加字幕（兼容所有FFmpeg版本）
        logger.info("⚡ 快速模式：叠加字幕...")
        
        from moviepy import VideoFileClip
        from moviepy.video.tools.subtitles import SubtitlesClip
        from moviepy import TextClip, CompositeVideoClip
        
        video_clip = VideoFileClip(temp_video_only)
        
        # 读取字幕文件并创建字幕clip
        try:
            # 尝试使用SubtitlesClip（如果字幕格式正确）
            subtitle_clip = SubtitlesClip(subtitle_file, lambda txt: TextClip(
                text=txt,
                font_size=48,
                color='white',
                stroke_color='black',
                stroke_width=2,
                method='caption',
                size=(int(video_clip.w * 0.9), None)
            ))
            video_with_subs = CompositeVideoClip([video_clip, subtitle_clip.with_position(('center', 'bottom'))])
        except Exception as e:
            # 如果字幕处理失败，跳过字幕
            logger.warning(f"字幕叠加失败，跳过字幕: {e}")
            video_with_subs = video_clip
        
        temp_video_with_subs = os.path.join(output_dir, "temp_with_subs.mp4")
        video_with_subs.write_videofile(
            temp_video_with_subs,
            codec='libx264',
            preset='ultrafast',
            audio=False,
            logger=None
        )
        
        from app.services.video import close_clip
        close_clip(video_clip)
        close_clip(video_with_subs)
        
        logger.info("✅ 字幕叠加完成")
        
        # 4. 叠加音频（视频使用-c:v copy不重新编码）
        logger.info("⚡ 快速模式：叠加音频...")
        
        # 构建FFmpeg命令
        final_cmd = [ffmpeg_path, '-i', temp_video_with_subs, '-i', audio_file]
        
        # 添加背景音乐输入
        if background_music and os.path.exists(background_music):
            final_cmd.extend(['-i', background_music])
            # 混音：语音 + 背景音乐
            final_cmd.extend([
                '-filter_complex', f"[1:a][2:a]amix=inputs=2:duration=first:weights=1 {bgm_volume}[audio]",
                '-map', '0:v',
                '-map', '[audio]',
                '-c:v', 'copy',  # 关键：视频直接复制，不重新编码
                '-c:a', 'aac',
                '-shortest',  # 以最短的流为准
                '-y',
                output_path
            ])
        else:
            # 没有背景音乐，直接映射音频流
            final_cmd.extend([
                '-map', '0:v',
                '-map', '1:a',
                '-c:v', 'copy',  # 关键：视频直接复制，不重新编码
                '-c:a', 'aac',
                '-shortest',  # 以最短的流为准
                '-y',
                output_path
            ])
        
        result = subprocess.run(final_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"音频叠加失败: {result.stderr}")
            return None
        
        logger.info("✅ 快速视频生成完成！")
        
        # 清理临时文件
        try:
            os.remove(temp_concat_file)
            os.remove(temp_video_only)
            os.remove(temp_video_with_subs)
        except:
            pass
        
        return output_path
        
    except Exception as e:
        logger.error(f"快速生成失败: {e}")
        return None


def _generate_with_reencode(
    video_paths: List[str],
    audio_file: str,
    subtitle_file: str,
    output_path: str,
    video_aspect: VideoAspect,
    background_music: str = None,
    bgm_volume: float = 0.2,
) -> str:
    """
    回退方案：使用重新编码的方式生成视频
    当素材编码格式不一致时使用
    """
    logger.info("使用重新编码模式生成视频...")
    
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        logger.error("未找到ffmpeg")
        return None
    
    output_dir = os.path.dirname(output_path)
    
    # 获取视频分辨率
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    
    # 1. 先拼接视频（重新编码统一格式）
    temp_merged = os.path.join(output_dir, "temp_merged.mp4")
    temp_concat_file = os.path.join(output_dir, "concat_list.txt")
    
    with open(temp_concat_file, 'w', encoding='utf-8') as f:
        for video_path in video_paths:
            safe_path = video_path.replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{safe_path}'\n")
    
    # 拼接并统一格式
    concat_cmd = [
        ffmpeg_path,
        '-f', 'concat',
        '-safe', '0',
        '-i', temp_concat_file,
        '-vf', f'scale={video_width}:{video_height}:force_original_aspect_ratio=decrease,pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-an',  # 暂时不要音频
        '-y',
        temp_merged
    ]
    
    subprocess.run(concat_cmd, capture_output=True)
    
    # 2. 使用MoviePy叠加字幕
    logger.info("叠加字幕...")
    
    from moviepy import VideoFileClip
    from moviepy.video.tools.subtitles import SubtitlesClip
    from moviepy import TextClip, CompositeVideoClip
    
    video_clip = VideoFileClip(temp_merged)
    
    try:
        subtitle_clip = SubtitlesClip(subtitle_file, lambda txt: TextClip(
            text=txt,
            font_size=48,
            color='white',
            stroke_color='black',
            stroke_width=2,
            method='caption',
            size=(int(video_clip.w * 0.9), None)
        ))
        video_with_subs = CompositeVideoClip([video_clip, subtitle_clip.with_position(('center', 'bottom'))])
    except Exception as e:
        logger.warning(f"字幕叠加失败，跳过字幕: {e}")
        video_with_subs = video_clip
    
    temp_video_with_subs = os.path.join(output_dir, "temp_with_subs.mp4")
    video_with_subs.write_videofile(
        temp_video_with_subs,
        codec='libx264',
        preset='ultrafast',
        audio=False,
        logger=None
    )
    
    from app.services.video import close_clip
    close_clip(video_clip)
    close_clip(video_with_subs)
    
    # 3. 叠加音频
    logger.info("叠加音频...")
    final_cmd = [ffmpeg_path, '-i', temp_video_with_subs, '-i', audio_file]
    
    # 添加背景音乐输入
    if background_music and os.path.exists(background_music):
        final_cmd.extend(['-i', background_music])
        # 混音：语音 + 背景音乐
        final_cmd.extend([
            '-filter_complex', f"[1:a][2:a]amix=inputs=2:duration=first:weights=1 {bgm_volume}[audio]",
            '-map', '0:v',
            '-map', '[audio]',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            '-y',
            output_path
        ])
    else:
        # 没有背景音乐，直接映射音频流
        final_cmd.extend([
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            '-y',
            output_path
        ])
    
    subprocess.run(final_cmd, capture_output=True)
    
    # 清理临时文件
    try:
        os.remove(temp_concat_file)
        os.remove(temp_merged)
        os.remove(temp_video_with_subs)
    except:
        pass
    
    return output_path


def generate_video_from_image_fast(
    image_path: str,
    audio_file: str,
    subtitle_file: str,
    output_path: str,
    video_width: int,
    video_height: int,
    background_music: str = None,
    bgm_volume: float = 0.2,
    video_subject: str = None,  # 新增：视频主题/标题
    video_theme: str = None,    # 新增：视频主题模式
    subtitle_color_theme: str = "classic_gold",  # 新增：字幕颜色主题
    font_size: int = 60,  # 新增：字体大小（用户配置）
) -> str:
    """
    从静态图片快速生成视频 - 使用FFmpeg直接处理，速度提升10倍以上
    
    传统方式（MoviePy）：
        图片 -> MoviePy处理 -> 逐帧渲染 -> 编码 (60秒)
    
    快速方式（FFmpeg）：
        图片 -> FFmpeg一步生成 -> 完成 (5秒)
    
    Args:
        image_path: 图片路径
        audio_file: 音频文件路径
        subtitle_file: 字幕文件路径
        output_path: 输出视频路径
        video_width: 视频宽度
        video_height: 视频高度
        background_music: 背景音乐路径
        bgm_volume: 背景音乐音量
        
    Returns:
        生成的视频文件路径
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        logger.error("未找到ffmpeg，无法使用快速生成模式")
        logger.info("💡 提示：")
        logger.info("  1. 如果已安装ffmpeg：")
        logger.info("     - 完全关闭当前终端窗口")
        logger.info("     - 打开新的PowerShell窗口")
        logger.info("     - 测试: ffmpeg -version")
        logger.info("     - 在新窗口中运行: .\\webui.bat")
        logger.info("  2. 如果未安装ffmpeg：")
        logger.info("     - 使用: winget install Gyan.FFmpeg")
        logger.info("  3. 将自动回退到标准模式（使用MoviePy内置ffmpeg）")
        logger.info("")
        return None
    
    try:
        logger.info("⚡ 快速模式：从静态图片生成视频...")
        
        # 获取音频时长
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_file
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        audio_duration = float(result.stdout.strip())
        logger.info(f"  - 音频时长: {audio_duration:.2f}秒")
        
        output_dir = os.path.dirname(output_path)
        temp_video = os.path.join(output_dir, "temp_image_video.mp4")
        
        # 步骤1：使用FFmpeg从图片生成视频（超快！）
        logger.info("  - 步骤1/3: 从图片生成视频基础流...")
        
        video_gen_cmd = [
            ffmpeg_path,
            '-loop', '1',                    # 循环图片
            '-i', image_path,                # 输入图片
            '-t', str(audio_duration),       # 视频时长等于音频时长
            '-vf', f'scale={video_width}:{video_height}:force_original_aspect_ratio=decrease,pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',          # 最快编码速度
            '-crf', '23',
            '-r', '30',                      # 30fps
            '-pix_fmt', 'yuv420p',
            '-y',
            temp_video
        ]
        
        result = subprocess.run(video_gen_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"图片生成视频失败: {result.stderr}")
            return None
        
        logger.info("  ✅ 视频基础流生成完成")
        
        # 步骤2：叠加音频和字幕（使用FFmpeg，避免重编码）
        logger.info("  - 步骤2/2: 叠加音频、字幕和标题...")
        
        # 构建FFmpeg命令
        final_cmd = [ffmpeg_path, '-i', temp_video, '-i', audio_file]
        
        # 添加背景音乐输入
        if background_music and os.path.exists(background_music):
            final_cmd.extend(['-i', background_music])
        
        # 检查是否支持subtitles滤镜
        try:
            check_result = subprocess.run(
                [ffmpeg_path, '-filters'],
                capture_output=True,
                text=True,
                timeout=3
            )
            has_subtitle_filter = 'subtitles' in check_result.stdout.lower() or 'ass' in check_result.stdout.lower()
        except:
            has_subtitle_filter = False
        
        # 构建视频滤镜（叠加字幕和标题）
        video_filters = []
        
        # 1. 字幕滤镜
        if subtitle_file and os.path.exists(subtitle_file):
            # 古书卷轴主题：使用竖排多列字幕，不使用subtitles滤镜
            if video_theme == 'ancient_scroll':
                logger.info("  - 古书卷轴模式：将在后续添加竖排字幕")
                # 竖排字幕将通过drawtext单独渲染，不在这里处理
                pass
            elif has_subtitle_filter:
                # 方案1：使用subtitles滤镜（支持ASS/SRT格式）
                logger.debug("  使用subtitles滤镜渲染字幕")
                # 转义字幕文件路径（Windows和特殊字符）
                subtitle_path_escaped = subtitle_file.replace('\\', '/').replace(':', '\\:')
                video_filters.append(f"subtitles='{subtitle_path_escaped}'")
            else:
                # 方案2：字幕不支持，使用默认样式
                logger.warning("  ⚠️  FFmpeg不支持subtitles滤镜，将使用默认字幕样式")
        
        # 2. 标题滤镜（使用drawtext）
        if video_subject:
            logger.info(f"  - 添加视频标题: {video_subject}")
            
            # 转义文本中的特殊字符
            title_text = video_subject.replace("'", "").replace('"', '').replace(':', '').replace('\\', '')
            
            # 获取字体文件路径（支持中文字符）
            from app.config import config
            font_name = config.ui.get('font_name', 'STHeitiMedium.ttc')
            # 获取项目根目录（正确的路径计算方式）
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            font_dir = os.path.join(project_root, 'resource', 'fonts')
            font_path = os.path.join(font_dir, font_name)
            
            # 如果字体文件不存在，尝试使用系统默认中文字体
            if not os.path.exists(font_path):
                logger.warning(f"  ⚠️  字体文件不存在: {font_path}")
                # Mac系统默认中文字体
                import platform
                if platform.system() == 'Darwin':  # macOS
                    # 尝试使用系统中文字体
                    system_fonts = [
                        '/System/Library/Fonts/STHeiti Light.ttc',
                        '/System/Library/Fonts/STHeiti Medium.ttc',
                        '/System/Library/Fonts/PingFang.ttc',
                        '/Library/Fonts/Arial Unicode.ttf',
                    ]
                    for sys_font in system_fonts:
                        if os.path.exists(sys_font):
                            font_path = sys_font
                            logger.info(f"  ✓ 使用系统字体: {sys_font}")
                            break
            
            # 转义字体路径（FFmpeg要求）
            font_path_escaped = font_path.replace('\\', '/').replace(':', '\\:')
            
            # 根据主题设置不同的样式
            if video_theme == 'ancient_scroll':
                # 古书卷轴：竖排标题在右侧垂直居中
                logger.info("  - 使用古书卷轴样式：竖排标题（垂直居中）")
                
                # 获取颜色主题配置
                theme_colors = get_subtitle_theme_colors(subtitle_color_theme)
                title_color = theme_colors['title']['color']
                title_stroke = theme_colors['title']['stroke']
                logger.info(f"  - 颜色主题: {subtitle_color_theme}, 标题颜色: {title_color}")
                
                # 将标题拆分成单个字符，竖排显示
                chars = list(title_text)
                # 标题字体大小：使用字幕字体的1.2倍，确保标题更醒目
                title_fontsize = int(font_size * 1.3)  # 标题比字幕大30%
                x_pos = int(video_width * 0.85)  # 右侧85%位置
                
                # 计算标题总高度并垂直居中
                title_height = len(chars) * int(title_fontsize * 1.2)
                y_start = int((video_height - title_height) / 2)  # 垂直居中
                
                logger.info(f"  - 标题字体大小: {title_fontsize}px（字幕字体的1.3倍）")
                
                # 为每个字符创建drawtext滤镜
                for i, char in enumerate(chars):
                    y_pos = y_start + i * int(title_fontsize * 1.2)
                    # 使用主题颜色
                    char_filter = f"drawtext=text='{char}':fontfile='{font_path_escaped}':x={x_pos}:y={y_pos}:fontsize={title_fontsize}:fontcolor={title_color}:borderw=2:bordercolor={title_stroke}"
                    video_filters.append(char_filter)
                
                # 添加竖排字幕（如果有字幕文件）
                if subtitle_file and os.path.exists(subtitle_file):
                    logger.info("  - 添加竖排字幕（古书卷轴样式 - 分屏显示）")
                    # 解析SRT字幕文件
                    import re
                    with open(subtitle_file, 'r', encoding='utf-8') as f:
                        srt_content = f.read()
                    
                    # SRT格式：序号\n时间戳\n文本\n空行
                    subtitle_pattern = r'(\d+)\s+([\d:,]+)\s+-->\s+([\d:,]+)\s+([\s\S]+?)(?=\n\n|\n*$)'
                    subtitles = re.findall(subtitle_pattern, srt_content)
                    
                    # 古书卷轴字幕参数（根据视频比例自适应）
                    # 判断视频方向
                    is_portrait = video_height > video_width  # 竖屏
                    
                    # 使用用户配置的字体大小，但根据视频比例进行适当调整
                    if is_portrait:
                        # 竖屏（9:16）：字体更大，列数更少，列间距适中
                        subtitle_fontsize = max(int(font_size * 1.2), int(video_height * 0.030))  # 竖屏加大20%或至少3%高度
                        column_count = 6  # 6列
                        column_spacing_multiplier = 1.5  # 列间距倍数：1.5倍字体大小
                        subtitle_left = int(video_width * 0.10)  # 左边界10%
                        subtitle_right = int(video_width * 0.70)  # 右边界70%（离标题更近）
                        subtitle_y_start = int(video_height * 0.12)  # 竖屏：从12%开始（与标题靠近）
                    else:
                        # 横屏（16:9）：使用用户配置的字体大小
                        subtitle_fontsize = max(int(font_size), int(video_height * 0.035))  # 使用配置值或至少3.5%高度
                        column_count = 15  # 15列（列间距减半后可放更多列）
                        column_spacing_multiplier = 0.75  # 列间距倍数：0.75倍字体大小（减半）
                        subtitle_left = int(video_width * 0.18)  # 左边界18%
                        subtitle_right = int(video_width * 0.80)  # 右边界80%（水平离标题更近）
                        subtitle_y_start = int(video_height * 0.12)  # 横屏：从12%开始
                    
                    # 计算每列可容纳的字符数（根据视频比例计算可用高度）
                    if is_portrait:
                        # 竖屏：88% - 12% = 76%可用高度
                        available_height = int(video_height * 0.76)
                    else:
                        # 横屏：88% - 12% = 76%可用高度（恢复原高度）
                        available_height = int(video_height * 0.76)
                    
                    char_spacing = 1.4  # 字符间距倍数（缩小间距，增加容量）
                    chars_per_column = int(available_height / (subtitle_fontsize * char_spacing))
                    
                    # 计算列间距（根据视频比例使用不同的倍数）
                    available_width = subtitle_right - subtitle_left
                    column_spacing = int(subtitle_fontsize * column_spacing_multiplier)
                    
                    logger.info(f"  - 视频比例: {'9:16 竖屏' if is_portrait else '16:9 横屏'}")
                    logger.info(f"  - 字幕布局: {column_count}列，字体大小{subtitle_fontsize}px，字符间距{char_spacing}x")
                    
                    # 计算每屏可显示的总字符数
                    chars_per_screen = chars_per_column * column_count
                    logger.info(f"  - 每屏可显示 {chars_per_screen} 个字符（{column_count}列 × {chars_per_column}字/列）")
                    
                    # 将字幕按时间和字符数分组成多屏
                    screens = []  # [(start_time, end_time, chars_list)]
                    current_screen_chars = []
                    current_screen_start = None
                    current_screen_end = None
                    
                    def parse_time(time_str):
                        """将SRT时间格式转换为秒数"""
                        h, m, s = time_str.replace(',', '.').split(':')
                        return float(h) * 3600 + float(m) * 60 + float(s)
                    
                    for idx, (num, start_time, end_time, text) in enumerate(subtitles):
                        # 清理文本
                        clean_text = text.strip().replace('\n', '').replace('\r', '')
                        chars = list(clean_text)
                        
                        # 如果是第一个字幕或者当前屏已满，开始新屏
                        if current_screen_start is None:
                            current_screen_start = parse_time(start_time)
                        
                        # 添加字符到当前屏
                        current_screen_chars.extend(chars)
                        # 在每句字幕之间添加一个空格作为分隔符（除了最后一句）
                        if idx < len(subtitles) - 1:
                            current_screen_chars.append(' ')  # 添加空格分隔
                        current_screen_end = parse_time(end_time)
                        
                        # 如果当前屏字符数达到上限，或者是最后一个字幕，保存这一屏
                        if len(current_screen_chars) >= chars_per_screen or idx == len(subtitles) - 1:
                            if current_screen_chars:
                                screens.append((
                                    current_screen_start,
                                    current_screen_end,
                                    current_screen_chars[:chars_per_screen]  # 截取最多chars_per_screen个字符
                                ))
                                # 如果还有剩余字符，开始下一屏
                                if len(current_screen_chars) > chars_per_screen:
                                    current_screen_chars = current_screen_chars[chars_per_screen:]
                                    current_screen_start = current_screen_end
                                else:
                                    current_screen_chars = []
                                    current_screen_start = None
                    
                    logger.info(f"  - 共分为 {len(screens)} 屏显示")
                    
                    # 为每一屏创建drawtext滤镜（带时间控制和三色高亮效果）
                    for screen_idx, (start_time, end_time, chars_list) in enumerate(screens):
                        logger.info(f"  - 第{screen_idx + 1}屏: {start_time:.1f}s - {end_time:.1f}s，{len(chars_list)}个字符")
                        
                        # 计算每个字符的时间（均匀分配）
                        screen_duration = end_time - start_time
                        char_duration = screen_duration / len(chars_list) if len(chars_list) > 0 else screen_duration
                        
                        # 将这一屏的字符排列成多列（从右向左，确保覆盖整个区域）
                        char_index = 0
                        for col in range(column_count):
                            # 从右向左排列：第0列在最右侧，最后一列在最左侧
                            # 使用线性插值确保均匀分布在 subtitle_left 到 subtitle_right 之间
                            if column_count > 1:
                                # 线性插值：从右(subtitle_right)到左(subtitle_left)
                                x_pos = subtitle_right - int((subtitle_right - subtitle_left) * col / (column_count - 1))
                            else:
                                x_pos = subtitle_right
                            
                            for row in range(chars_per_column):
                                if char_index >= len(chars_list):
                                    break
                                
                                char = chars_list[char_index]
                                y_pos = subtitle_y_start + row * int(subtitle_fontsize * char_spacing)
                                
                                # 计算当前字符的时间范围
                                char_start_time = start_time + char_index * char_duration
                                char_end_time = char_start_time + char_duration
                                
                                # 三色高亮效果：使用颜色主题
                                if char.strip():  # 跳过空格
                                    char_escaped = char.replace("'", "").replace('"', '')
                                    
                                    # 获取主题颜色
                                    unread_color = theme_colors['unread']['color']
                                    unread_stroke = theme_colors['unread']['stroke']
                                    reading_color = theme_colors['reading']['color']
                                    reading_stroke = theme_colors['reading']['stroke']
                                    read_color = theme_colors['read']['color']
                                    read_stroke = theme_colors['read']['stroke']
                                    
                                    # 1. 未读状态（从屏幕开始到当前字开始朗读）
                                    if char_start_time > start_time:
                                        unread_filter = f"drawtext=text='{char_escaped}':fontfile='{font_path_escaped}':x={x_pos}:y={y_pos}:fontsize={subtitle_fontsize}:fontcolor={unread_color}:borderw=2:bordercolor={unread_stroke}:enable='between(t,{start_time},{char_start_time})'"
                                        video_filters.append(unread_filter)
                                    
                                    # 2. 正在读状态：高亮颜色+略微放大（当前字正在朗读时）
                                    reading_fontsize = int(subtitle_fontsize * 1.1)  # 放大10%
                                    reading_filter = f"drawtext=text='{char_escaped}':fontfile='{font_path_escaped}':x={x_pos}:y={y_pos}:fontsize={reading_fontsize}:fontcolor={reading_color}:borderw=2:bordercolor={reading_stroke}:enable='between(t,{char_start_time},{char_end_time})'"
                                    video_filters.append(reading_filter)
                                    
                                    # 3. 已读状态（当前字读完到屏幕结束）
                                    if char_end_time < end_time:
                                        read_filter = f"drawtext=text='{char_escaped}':fontfile='{font_path_escaped}':x={x_pos}:y={y_pos}:fontsize={subtitle_fontsize}:fontcolor={read_color}:borderw=2:bordercolor={read_stroke}:enable='between(t,{char_end_time},{end_time})'"
                                        video_filters.append(read_filter)
                                
                                char_index += 1
                            
                            if char_index >= len(chars_list):
                                break
                
            elif video_theme == 'modern_book':
                # 现代图书：标题在正中间
                title_x = '(w-text_w)/2'
                title_y = '(h-text_h)/2'
                fontsize = int(video_height * 0.08)  # 8%高度
                logger.info(f"  - 使用现代图书样式：标题居中")
                drawtext_filter = f"drawtext=text='{title_text}':fontfile='{font_path_escaped}':x={title_x}:y={title_y}:fontsize={fontsize}:fontcolor=white:borderw=3:bordercolor=black"
                video_filters.append(drawtext_filter)
                
            else:
                # 其他主题：标题在顶部
                title_x = '(w-text_w)/2'
                title_y = 'h*0.1'
                fontsize = int(video_height * 0.06)  # 6%高度
                drawtext_filter = f"drawtext=text='{title_text}':fontfile='{font_path_escaped}':x={title_x}:y={title_y}:fontsize={fontsize}:fontcolor=white:borderw=3:bordercolor=black"
                video_filters.append(drawtext_filter)
        
        # 合并所有视频滤镜
        video_filter = ','.join(video_filters) if video_filters else None
        
        # 构建完整命令
        if background_music and os.path.exists(background_music):
            # 混音：语音 + 背景音乐
            if video_filter:
                final_cmd.extend([
                    '-filter_complex', 
                    f"[0:v]{video_filter}[v];[1:a][2:a]amix=inputs=2:duration=first:weights=1 {bgm_volume}[a]",
                    '-map', '[v]',
                    '-map', '[a]',
                ])
            else:
                final_cmd.extend([
                    '-filter_complex', 
                    f"[1:a][2:a]amix=inputs=2:duration=first:weights=1 {bgm_volume}[a]",
                    '-map', '0:v',
                    '-map', '[a]',
                ])
        else:
            # 没有背景音乐
            if video_filter:
                final_cmd.extend([
                    '-vf', video_filter,
                    '-map', '0:v',
                    '-map', '1:a',
                ])
            else:
                final_cmd.extend([
                    '-map', '0:v',
                    '-map', '1:a',
                ])
        
        # 编码参数：如果有字幕滤镜则需要重编码，否则复制
        if video_filter:
            # 需要重编码以渲染字幕
            final_cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'ultrafast',  # 最快速度
                '-crf', '23',
            ])
        else:
            # 无字幕或跳过字幕，直接复制视频流（超快）
            final_cmd.extend([
                '-c:v', 'copy',
            ])
        
        final_cmd.extend([
            '-c:a', 'aac',
            '-b:a', '128k',
            '-shortest',
            '-movflags', '+faststart',
            '-y',
            output_path
        ])
        
        # 直接生成最终视频（不使用MoviePy）
        result = subprocess.run(final_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"视频生成失败: {result.stderr}")
            return None
        
        # 清理临时文件
        try:
            os.remove(temp_video)
        except:
            pass
        
        logger.success(f"⚡ 快速视频生成完成！")
        return output_path
        
    except Exception as e:
        logger.error(f"快速生成失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_template_video(
    duration: int,
    video_aspect: VideoAspect,
    output_path: str,
    background_color: str = "black"
) -> str:
    """
    生成模板视频 - 纯色背景，指定时长
    可以预先生成常用时长的模板，后续只需叠加内容
    
    Args:
        duration: 视频时长（秒）
        video_aspect: 视频比例
        output_path: 输出路径
        background_color: 背景颜色
        
    Returns:
        模板视频路径
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        return None
    
    aspect = VideoAspect(video_aspect)
    width, height = aspect.to_resolution()
    
    # 使用color源生成纯色视频
    cmd = [
        ffmpeg_path,
        '-f', 'lavfi',
        '-i', f'color=c={background_color}:s={width}x{height}:d={duration}:r=30',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-y',
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info(f"✅ 模板视频已生成: {output_path}")
        return output_path
    else:
        logger.error(f"模板视频生成失败: {result.stderr}")
        return None

