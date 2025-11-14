"""
字幕颜色主题配置
定义古书卷轴主题下，未读、正在读、已读三种状态的颜色搭配
"""

# 字幕颜色主题配置
SUBTITLE_COLOR_THEMES = {
    "classic_gold": {
        "name": "经典金棕",
        "name_en": "Classic Gold",
        "description": "传统古书风格，黑色 → 金色 → 棕色",
        "unread": {
            "color": "#000000",      # 黑色
            "stroke": "#8B4513",     # 棕色描边
        },
        "reading": {
            "color": "#FFD700",      # 金色
            "stroke": "#8B4513",     # 棕色描边
        },
        "read": {
            "color": "#8B4513",      # 棕色
            "stroke": "#FFD700",     # 金色描边
        },
        "title": {
            "color": "#8B4513",      # 棕色（标题跟随已读颜色）
            "stroke": "#FFD700",     # 金色描边
        }
    },
    
    "elegant_blue": {
        "name": "雅致蓝白",
        "name_en": "Elegant Blue",
        "description": "清雅书卷风格，深蓝 → 浅蓝 → 白色",
        "unread": {
            "color": "#1E3A8A",      # 深蓝色
            "stroke": "#93C5FD",     # 浅蓝描边
        },
        "reading": {
            "color": "#60A5FA",      # 浅蓝色（高亮）
            "stroke": "#1E3A8A",     # 深蓝描边
        },
        "read": {
            "color": "#E0F2FE",      # 极浅蓝/白色
            "stroke": "#60A5FA",     # 浅蓝描边
        },
        "title": {
            "color": "#E0F2FE",      # 极浅蓝/白色
            "stroke": "#60A5FA",     # 浅蓝描边
        }
    },
    
    "warm_sunset": {
        "name": "温暖落日",
        "name_en": "Warm Sunset",
        "description": "温馨暖色调，深红 → 橙色 → 淡黄",
        "unread": {
            "color": "#7C2D12",      # 深红棕色
            "stroke": "#FED7AA",     # 淡橙描边
        },
        "reading": {
            "color": "#FB923C",      # 明亮橙色（高亮）
            "stroke": "#7C2D12",     # 深红描边
        },
        "read": {
            "color": "#FEF3C7",      # 淡黄色
            "stroke": "#FB923C",     # 橙色描边
        },
        "title": {
            "color": "#FEF3C7",      # 淡黄色
            "stroke": "#FB923C",     # 橙色描边
        }
    },
    
    "fresh_green": {
        "name": "清新绿意",
        "name_en": "Fresh Green",
        "description": "自然清新风格，深绿 → 翠绿 → 浅绿",
        "unread": {
            "color": "#14532D",      # 深绿色
            "stroke": "#BBF7D0",     # 浅绿描边
        },
        "reading": {
            "color": "#22C55E",      # 翠绿色（高亮）
            "stroke": "#14532D",     # 深绿描边
        },
        "read": {
            "color": "#DCFCE7",      # 浅绿色
            "stroke": "#22C55E",     # 翠绿描边
        },
        "title": {
            "color": "#DCFCE7",      # 浅绿色
            "stroke": "#22C55E",     # 翠绿描边
        }
    },
    
    "purple_dream": {
        "name": "紫色梦境",
        "name_en": "Purple Dream",
        "description": "梦幻优雅风格，深紫 → 粉紫 → 淡紫",
        "unread": {
            "color": "#581C87",      # 深紫色
            "stroke": "#E9D5FF",     # 淡紫描边
        },
        "reading": {
            "color": "#C084FC",      # 粉紫色（高亮）
            "stroke": "#581C87",     # 深紫描边
        },
        "read": {
            "color": "#F3E8FF",      # 极淡紫色
            "stroke": "#C084FC",     # 粉紫描边
        },
        "title": {
            "color": "#F3E8FF",      # 极淡紫色
            "stroke": "#C084FC",     # 粉紫描边
        }
    },
    
    "ink_wash": {
        "name": "水墨丹青",
        "name_en": "Ink Wash",
        "description": "中国水墨风格，黑色 → 灰色 → 浅灰",
        "unread": {
            "color": "#1F2937",      # 深灰黑
            "stroke": "#D1D5DB",     # 浅灰描边
        },
        "reading": {
            "color": "#6B7280",      # 中灰色（高亮）
            "stroke": "#1F2937",     # 深灰描边
        },
        "read": {
            "color": "#F3F4F6",      # 极浅灰
            "stroke": "#6B7280",     # 中灰描边
        },
        "title": {
            "color": "#F3F4F6",      # 极浅灰
            "stroke": "#6B7280",     # 中灰描边
        }
    },
}


def get_subtitle_theme_colors(theme_name: str = "classic_gold"):
    """
    获取指定主题的颜色配置
    
    Args:
        theme_name: 主题名称
        
    Returns:
        主题颜色配置字典
    """
    return SUBTITLE_COLOR_THEMES.get(theme_name, SUBTITLE_COLOR_THEMES["classic_gold"])


def get_all_theme_names():
    """
    获取所有可用的主题名称列表
    
    Returns:
        [(theme_key, theme_display_name), ...]
    """
    return [(key, config["name"]) for key, config in SUBTITLE_COLOR_THEMES.items()]
