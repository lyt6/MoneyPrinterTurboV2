#!/bin/bash

# If you could not download the model from the official site, you can use the mirror site.
# Just remove the comment of the following line .
# 如果你无法从官方网站下载模型,你可以使用镜像网站。
# 只需要移除下面一行的注释即可。

# export HF_ENDPOINT=https://hf-mirror.com

# 检测并激活 MoneyPrinterTurbo conda 环境
if command -v conda &> /dev/null; then
    # 初始化 conda (如果需要)
    eval "$(conda shell.bash hook)"
    
    # 检查环境是否存在
    if conda env list | grep -q "MoneyPrinterTurbo"; then
        echo "正在激活 MoneyPrinterTurbo conda 环境..."
        conda activate MoneyPrinterTurbo
    else
        echo "错误: 找不到 MoneyPrinterTurbo conda 环境"
        echo "请先创建环境: conda create -n MoneyPrinterTurbo python=3.10"
        exit 1
    fi
else
    echo "警告: 未找到 conda 命令,将使用当前环境"
fi

streamlit run ./webui/Main.py --browser.serverAddress="0.0.0.0" --server.enableCORS=True --browser.gatherUsageStats=False