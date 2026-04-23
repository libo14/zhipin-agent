# Windows 打包说明

目标：把当前智能招聘 Agent 打包成 Windows 10/11 可安装、可双击运行的本地桌面软件。

## 1. 构建桌面 EXE

```powershell
cd D:\codex\ai-recruitment-agent
.\packaging\windows\build_exe.ps1
```

输出目录：

```text
dist\ZhipinAgent\ZhipinAgent.exe
```

双击 `ZhipinAgent.exe` 会启动本地服务，并用内嵌 WebView 桌面窗口打开应用界面，不会跳转到外部浏览器。调试时如需浏览器模式，可手动执行：

```powershell
.\dist\ZhipinAgent\ZhipinAgent.exe --browser
```

## 2. 本机安装到桌面

```powershell
.\packaging\windows\install_app.ps1
```

默认安装到当前用户桌面文件夹：

```text
Desktop\ZhipinAgent
```

并创建桌面快捷方式：

```text
Desktop\ZhipinAgent.lnk
```

## 3. 卸载

```powershell
.\packaging\windows\uninstall_app.ps1
```

## 4. 生成单文件安装包

```powershell
.\packaging\windows\build_installer.ps1
```

输出：

```text
dist\installer\ZhipinAgentSetup.exe
```

这个安装包是单文件安装器。双击后会安装到桌面 `ZhipinAgent` 文件夹，创建桌面快捷方式 `ZhipinAgent.lnk`，并自动启动应用。

## 5. 运行要求

桌面窗口依赖 Windows 的 Microsoft Edge WebView2 Runtime。大多数 Windows 10/11 系统已经内置；如果启动时提示缺少 WebView2，需要先安装 WebView2 Runtime 后再打开软件。
