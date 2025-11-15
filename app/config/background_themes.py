"""
古书卷轴背景主题配置

支持横屏和竖屏两种比例的背景图片
"""

import os

# 获取资源目录路径
RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resource")
BACKGROUNDS_DIR = os.path.join(RESOURCE_DIR, "backgrounds")

# 横屏背景（16:9）
LANDSCAPE_BACKGROUNDS = {
    "ancient_paper_1": {
        "name": "古纸质感1",
        "name_en": "Ancient Paper 1",
        "description": "米黄色古纸质感，适合古典文学内容",
        "file": "landscape/ancient_paper_1.jpg",
        "color": "#F5E6D3",  # 主色调，用于生成占位背景
    },
    "ancient_paper_2": {
        "name": "古纸质感2",
        "name_en": "Ancient Paper 2", 
        "description": "浅棕色古纸质感，适合历史故事",
        "file": "landscape/ancient_paper_2.jpg",
        "color": "#E8D5C4",
    },
    "bamboo_scroll_1": {
        "name": "竹简卷轴1",
        "name_en": "Bamboo Scroll 1",
        "description": "竹简纹理背景，古朴典雅",
        "file": "landscape/bamboo_scroll_1.jpg",
        "color": "#D4C5B0",
    },
    "bamboo_scroll_2": {
        "name": "竹简卷轴2",
        "name_en": "Bamboo Scroll 2",
        "description": "深色竹简纹理，适合诗词内容",
        "file": "landscape/bamboo_scroll_2.jpg",
        "color": "#C8B89A",
    },
    "ink_wash": {
        "name": "水墨山水",
        "name_en": "Ink Wash",
        "description": "水墨山水背景，意境深远",
        "file": "landscape/ink_wash.jpg",
        "color": "#E5DDD5",
    },
}

# 竖屏背景（9:16）
PORTRAIT_BACKGROUNDS = {
    "ancient_paper_1": {
        "name": "古纸质感1",
        "name_en": "Ancient Paper 1",
        "description": "米黄色古纸质感，适合古典文学内容",
        "file": "portrait/ancient_paper_1.jpg",
        "color": "#F5E6D3",
    },
    "ancient_paper_2": {
        "name": "古纸质感2",
        "name_en": "Ancient Paper 2",
        "description": "浅棕色古纸质感，适合历史故事",
        "file": "portrait/ancient_paper_2.jpg",
        "color": "#E8D5C4",
    },
    "bamboo_scroll_1": {
        "name": "竹简卷轴1",
        "name_en": "Bamboo Scroll 1",
        "description": "竹简纹理背景，古朴典雅",
        "file": "portrait/bamboo_scroll_1.jpg",
        "color": "#D4C5B0",
    },
    "bamboo_scroll_2": {
        "name": "竹简卷轴2",
        "name_en": "Bamboo Scroll 2",
        "description": "深色竹简纹理，适合诗词内容",
        "file": "portrait/bamboo_scroll_2.jpg",
        "color": "#C8B89A",
    },
    "ink_wash": {
        "name": "水墨山水",
        "name_en": "Ink Wash",
        "description": "水墨山水背景，意境深远",
        "file": "portrait/ink_wash.jpg",
        "color": "#E5DDD5",
    },
}


def get_background_path(background_key: str, is_portrait: bool = True) -> str:
    """
    获取背景图片的完整路径
    
    Args:
        background_key: 背景键名
        is_portrait: 是否竖屏
    
    Returns:
        背景图片完整路径，如果不存在返回空字符串
    """
    backgrounds = PORTRAIT_BACKGROUNDS if is_portrait else LANDSCAPE_BACKGROUNDS
    
    if background_key not in backgrounds:
        return ""
    
    bg_info = backgrounds[background_key]
    bg_path = os.path.join(BACKGROUNDS_DIR, bg_info["file"])
    
    # 检查文件是否存在
    if os.path.exists(bg_path):
        return bg_path
    
    return ""


def get_all_backgrounds(is_portrait: bool = True) -> dict:
    """
    获取所有背景配置
    
    Args:
        is_portrait: 是否竖屏
    
    Returns:
        背景配置字典
    """
    return PORTRAIT_BACKGROUNDS if is_portrait else LANDSCAPE_BACKGROUNDS


def get_background_keys(is_portrait: bool = True) -> list:
    """
    获取所有背景的键名列表
    
    Args:
        is_portrait: 是否竖屏
    
    Returns:
        背景键名列表
    """
    backgrounds = PORTRAIT_BACKGROUNDS if is_portrait else LANDSCAPE_BACKGROUNDS
    return list(backgrounds.keys())


def get_background_names(is_portrait: bool = True) -> list:
    """
    获取所有背景的显示名称列表（用于UI选择器）
    
    Args:
        is_portrait: 是否竖屏
    
    Returns:
        (key, name, description) 元组列表
    """
    backgrounds = PORTRAIT_BACKGROUNDS if is_portrait else LANDSCAPE_BACKGROUNDS
    return [(key, bg["name"], bg["description"]) for key, bg in backgrounds.items()]
