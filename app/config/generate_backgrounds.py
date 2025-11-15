"""
生成古书卷轴背景占位图片

如果背景图片不存在，将根据配置生成纯色占位背景
用户可以替换为真实的背景图片
"""

import os
from PIL import Image, ImageDraw, ImageFont
import background_themes

def generate_placeholder_background(bg_key: str, bg_info: dict, width: int, height: int, output_path: str):
    """
    生成占位背景图片
    
    Args:
        bg_key: 背景键名
        bg_info: 背景配置信息
        width: 图片宽度
        height: 图片高度
        output_path: 输出路径
    """
    # 创建纯色背景
    color = bg_info.get("color", "#F5E6D3")
    # 将十六进制颜色转换为RGB
    color_rgb = tuple(int(color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    
    # 创建图片
    img = Image.new('RGB', (width, height), color_rgb)
    draw = ImageDraw.Draw(img)
    
    # 添加简单的纹理效果（可选）
    # 这里添加一些细微的线条模拟纸张纹理
    import random
    random.seed(hash(bg_key))  # 使用背景名作为随机种子，保证每次生成相同
    
    for _ in range(50):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = x1 + random.randint(-100, 100)
        y2 = y1 + random.randint(-100, 100)
        
        # 计算比背景色稍暗的颜色
        line_color = tuple(max(0, c - 10) for c in color_rgb)
        draw.line([(x1, y1), (x2, y2)], fill=line_color, width=1)
    
    # 添加文字水印
    try:
        # 尝试加载中文字体
        font_size = min(width, height) // 20
        text = bg_info.get("name", "占位背景")
        
        # 在中心位置绘制文字
        text_bbox = draw.textbbox((0, 0), text)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # 半透明文字
        text_color = tuple(max(0, c - 30) for c in color_rgb)
        draw.text((x, y), text, fill=text_color)
    except Exception as e:
        print(f"添加文字水印失败: {e}")
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 保存图片
    img.save(output_path, 'JPEG', quality=95)
    print(f"✅ 已生成占位背景: {output_path}")


def generate_all_backgrounds():
    """生成所有占位背景图片"""
    backgrounds_dir = background_themes.BACKGROUNDS_DIR
    
    # 生成横屏背景（1920x1080）
    print("\n📺 生成横屏背景（1920x1080）...")
    for bg_key, bg_info in background_themes.LANDSCAPE_BACKGROUNDS.items():
        output_path = os.path.join(backgrounds_dir, bg_info["file"])
        if not os.path.exists(output_path):
            generate_placeholder_background(bg_key, bg_info, 1920, 1080, output_path)
        else:
            print(f"⏭️  跳过已存在的背景: {output_path}")
    
    # 生成竖屏背景（1080x1920）
    print("\n📱 生成竖屏背景（1080x1920）...")
    for bg_key, bg_info in background_themes.PORTRAIT_BACKGROUNDS.items():
        output_path = os.path.join(backgrounds_dir, bg_info["file"])
        if not os.path.exists(output_path):
            generate_placeholder_background(bg_key, bg_info, 1080, 1920, output_path)
        else:
            print(f"⏭️  跳过已存在的背景: {output_path}")
    
    print("\n✅ 所有占位背景生成完成！")
    print(f"📂 背景目录: {backgrounds_dir}")
    print("\n💡 提示: 这些是占位背景，你可以替换为真实的古书卷轴背景图片")


if __name__ == "__main__":
    generate_all_backgrounds()
