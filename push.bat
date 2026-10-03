@echo off
chcp 65001 >nul
title Addenda-Think 一键推送
cd /d "%~dp0"

echo ============================================
echo  Addenda-Think ^→ GitHub 一键推送
echo  仓库: Sycho-Finally/Addenda-Think (main)
echo  （首次请在 GitHub 网页创建同名空仓库）
echo ============================================
echo.

git add -A
for /f %%i in ('git status -s ^| find /c /v ""') do set CHANGES=%%i
if not "%CHANGES%"=="0" (
    echo [1/2] 提交 %CHANGES% 个文件变更...
    git commit -m "update: content sync"
)

echo [2/2] 推送到 GitHub...
git -c http.schannelCheckRevoke=false push -u origin main
if errorlevel 1 (
    echo.
    echo [失败] 排查：1.代理已开启 2.GitHub 已建同名仓库 3.账号已登录
) else (
    echo.
    echo [成功] https://github.com/Sycho-Finally/Addenda-Think
)
echo.
pause
