# 古书卷轴背景资源说明

本目录包含古书卷轴主题的默认背景图片。

## 目录结构

```
backgrounds/
├── landscape/     # 横屏背景（16:9, 1920x1080）
│   ├── ancient_paper_1.jpg    # 古纸质感1 - 米黄色
│   ├── ancient_paper_2.jpg    # 古纸质感2 - 浅棕色
│   ├── bamboo_scroll_1.jpg    # 竹简卷轴1 - 古朴典雅
│   ├── bamboo_scroll_2.jpg    # 竹简卷轴2 - 深色竹简
│   └── ink_wash.jpg           # 水墨山水 - 意境深远
└── portrait/      # 竖屏背景（9:16, 1080x1920）
    ├── ancient_paper_1.jpg
    ├── ancient_paper_2.jpg
    ├── bamboo_scroll_1.jpg
    ├── bamboo_scroll_2.jpg
    └── ink_wash.jpg
```

## 当前背景

当前的背景图片是自动生成的占位背景，具有简单的纹理效果。

## 如何替换为真实背景

你可以将这些占位背景替换为真实的古书卷轴背景图片：

### 1. 准备背景图片

- **横屏背景**: 推荐分辨率 1920x1080（16:9）
- **竖屏背景**: 推荐分辨率 1080x1920（9:16）
- **格式**: JPG 或 PNG
- **风格**: 古纸、竹简、水墨等古典风格

### 2. 替换图片

直接替换对应的文件即可，保持文件名不变：

```bash
# 例如替换横屏的古纸质感1背景
cp 你的背景图片.jpg landscape/ancient_paper_1.jpg

# 例如替换竖屏的竹简卷轴1背景  
cp 你的背景图片.jpg portrait/bamboo_scroll_1.jpg
```

### 3. 重启应用

替换后重启Web界面即可看到新的背景。

## 背景配置

背景的名称和描述在 `app/config/background_themes.py` 中定义。

如果需要添加新的背景，可以：
1. 在该配置文件中添加新的背景定义
2. 将对应的背景图片放入 `landscape/` 或 `portrait/` 目录
3. 重启应用

## 使用说明

在Web界面中：
1. 选择 **古书卷轴** 主题
2. 视频来源选择 **本地文件**
3. 背景来源选择 **默认背景**
4. 从下拉列表选择需要的背景
5. 系统会根据视频比例（横屏/竖屏）自动显示对应的背景选项

## 推荐背景素材来源

- Unsplash: https://unsplash.com (搜索 "ancient paper", "bamboo", "ink wash")
- Pexels: https://www.pexels.com (搜索 "old paper", "vintage paper")
- Pixabay: https://pixabay.com
- 自己拍摄或制作的古典风格背景

## 注意事项

- 确保背景颜色不会影响字幕的可读性
- 建议使用米黄色、浅棕色等温和的背景色
- 避免背景过于花哨，以免分散观众注意力
- 保持同一系列视频使用统一的背景风格
