# Phone Control

Phone Control 是一个面向 Android 的电脑端手机投屏与控制工具。当前版本通过 Android Debug Bridge（ADB）实现：电脑周期性抓取手机屏幕截图并显示在桌面窗口，同时把鼠标点击、拖动和键盘事件转成 Android `input` 命令发送回手机。

> 这是一个可运行的 MVP，优先保证无需手机端 APK、兼容主流 Android 手机。后续可以在此基础上扩展为更高帧率的视频流、无线连接、音频转发和更完整的输入法桥接。

## 功能

- 发现通过 USB 连接的 Android 设备。
- 投屏显示 Android 当前屏幕。
- 鼠标点击电脑端画面可点击手机屏幕。
- 鼠标拖动电脑端画面可在手机上滑动。
- 键盘输入可发送到手机；支持常用快捷键：
  - `Esc`：返回
  - `Enter`：确认/回车
  - `Backspace`：删除
  - 方向键：Android DPAD 方向键
  - `F5`：多任务/最近任务
- 工具栏提供返回、主页、多任务按钮。

## 前置条件

1. 安装 Android Platform Tools，并确保 `adb` 在 `PATH` 中。
2. 在手机上开启“开发者选项”和“USB 调试”。
3. 用 USB 连接手机，在手机弹窗中允许当前电脑调试。
4. 在终端运行 `adb devices`，确认设备状态为 `device`。

## 安装与运行

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
phone-control
```

也可以不安装脚本，直接运行：

```bash
python -m phone_control
```

## 使用方法

1. 打开程序后点击“刷新设备”。
2. 在设备下拉框中选择状态为 `device` 的 Android 设备。
3. 点击“开始投屏”。
4. 在投屏画面中：
   - 单击：手机点击。
   - 拖动后松开：手机滑动。
   - 直接键盘输入：向手机当前输入框发送文本。

## 当前限制

- 当前投屏方式是 `adb exec-out screencap -p` 周期截图，帧率低于 scrcpy 这类视频编码方案，但实现简单且无需安装手机端应用。
- Android 原生 `adb shell input text` 对复杂中文、表情和部分符号支持有限。中文输入建议后续通过剪贴板桥接或手机端输入法辅助服务增强。
- 某些厂商系统需要额外允许“USB 调试（安全设置）”才能模拟点击和输入。
- 当前仅实现 Android；iOS 需要完全不同的授权、投屏和输入控制方案。

## 开发

运行测试：

```bash
python -m unittest discover -s tests
```

项目结构：

```text
src/phone_control/adb.py   # ADB 命令封装
src/phone_control/app.py   # Tkinter 桌面 UI 和输入映射
tests/                     # 单元测试
```
