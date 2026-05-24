from __future__ import annotations


def _hotkey_scope_label(*, enabled: bool) -> str:
    return "全局" if enabled else "仅窗口聚焦时"


def build_help_text(
    *,
    screenshot_hotkey: str,
    screenshot_hotkey_global: bool,
    record_hotkey: str,
    record_hotkey_global: bool,
    screenshot_fullscreen: bool,
    screenshot_hide_window: bool,
    record_hide_window: bool,
) -> str:
    screenshot_scope = _hotkey_scope_label(enabled=screenshot_hotkey_global)
    record_scope = _hotkey_scope_label(enabled=record_hotkey_global)
    screenshot_mode = "全屏" if screenshot_fullscreen else "区域选择"
    screenshot_hide = "隐藏窗口" if screenshot_hide_window else "不隐藏窗口"
    record_hide = "隐藏窗口" if record_hide_window else "不隐藏窗口"
    return f"""文件整理器 — 使用说明

【工具栏】
  返回上级      进入上一级目录
  截图 ▾        悬停展开：区域截图 / 二维码 / 全屏录屏
  收藏夹        目录与文件分两列，双击打开
  设置          分「常规 / 截图·录屏 / 截图 AI」三类
  帮助          打开本说明

【快捷键】
  Alt + ←             后退到上一个浏览过的目录
  Alt + →             前进
  鼠标侧键（后退）     同 Alt + ←（若系统/驱动支持）
  鼠标侧键（前进）     同 Alt + →
  Ctrl + Z            撤销上一步文件操作
  Delete              将选中项移到回收区（myfile/trash）
  {screenshot_hotkey:<18}  截图（{screenshot_scope}，{screenshot_mode}，{screenshot_hide}）
  {record_hotkey:<18}  全屏录屏开/停（{record_scope}，{record_hide}）
  Esc                 区域选区时取消

【文件列表 — 选择】
  左键单击              选中单项
  Ctrl + 左键           追加选中 / 取消选中该项
  Shift + 左键          与上次选中项之间连续选中
  空白处左键拖动        框选多个文件/文件夹
  Ctrl + 空白处拖动     在已有选中基础上追加框选
  双击                  打开文件，或进入文件夹

【文件列表 — 右键】
  在文件/文件夹上：
    打开/进入、加入收藏、重命名（仅选中 1 项时可用）
    移到回收区（可多选，菜单显示项数）
  在空白处：
    刷新、新建文件夹、收藏当前目录、撤销上一步

【路径栏】
  点击路径中的某一级     跳转到该目录
  路径文字               可选中复制

【最近打开】（右侧栏）
  拖动中间分隔条           调节文件列表与最近打开的宽度（宽度会记住）
  双击                   再次打开该文件（程序、图片、视频等）
  右键                   打开 / 从列表移除

【截图】
  1. 点击「截图 ▾」选「区域截图」，或使用截图快捷键
  2. 若未开启「默认全屏截图」，拖动框选区域后保存
  3. 可在设置中勾选「截图时隐藏本程序窗口」；隐藏后稍等再抓取，结束后自动恢复
  4. 若已在设置中启用 AI，保存后可选择识图翻译（识图请选 Poe；DeepSeek 仅文本）
  5. AI 识图成功后，原截图会自动删除（结果支持代码、图片、公式；可保存为文本或 HTML）

【二维码识别】
  1. 悬停「截图 ▾」选「二维码」
  2. 拖动框选含二维码的区域（始终区域框选，不受「默认全屏截图」影响）
  3. 识别成功后弹窗显示内容，可一键复制；选区内有多个码时会列出全部
  4. 与截图共用「截图时隐藏本程序窗口」设置

【全屏录屏】
  1. 悬停「截图 ▾」选「全屏录屏」，或使用录屏快捷键
  2. 录制整个屏幕；默认仅用录屏快捷键开始/结束（可在设置中开启右上角停止按钮）
  3. 可在设置中勾选「录屏时隐藏本程序窗口」；结束后自动恢复
  4. 再次按录屏快捷键结束；若已开启停止按钮，也可点「停止」
  5. 视频保存到 myfile/photocut/recordings/
  6. 在「设置 → 截图 / 录屏」可调帧率 (5–60 FPS) 与输出宽高（填「自动」或像素数）

【收藏夹弹窗】
  左列「目录」  收藏的文件夹路径，双击进入
  右列「文件」  收藏的可打开文件，双击用系统默认程序打开
  右键条目    打开 / 删除收藏
  清空目录 / 清空文件    分别清除两列收藏

【数据位置】
  管理的文件：程序目录下 myfile
  设置文件：  .folder_organizer_settings.json
  回收区：    myfile/trash（统一目录，不在当前子文件夹下）
  截图目录：  myfile/photocut
  录屏目录：  myfile/photocut/recordings
"""
