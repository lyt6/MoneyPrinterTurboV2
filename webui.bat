@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****
set PYTHONPATH=%CURRENT_DIR%

rem 禁用Streamlit文件监视器，避免torch模块检查导致的错误
set STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

rem set HF_ENDPOINT=https://hf-mirror.com
streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True