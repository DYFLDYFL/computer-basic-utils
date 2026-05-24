# Folder File Organizer

一个 Windows 桌面文件管理工具，用来管理项目目录下的 `myfile` 文件夹。项目使用 Python + Tkinter 编写，可以通过 PyInstaller 打包成 `exe`。

## 功能

- 浏览当前文件夹内的文件和文件夹
- 双击打开文件或文件夹
- 重命名选中的文件或文件夹
- 新建文件夹
- 将选中项移动到 `myfile/trash`（统一回收区）

## 运行源码

```powershell
cd C:\code\organize
.\run.ps1
```

也可以手动运行：

```powershell
cd C:\code\organize
$env:PYTHONPATH = ".\src"
python -m file_organizer
```

## 打包 exe

```powershell
cd C:\code\organize
.\build_exe.ps1
```

如果之前已经打开过 `FolderOrganizer.exe`，请先关闭它，再重新运行上面的命令生成新的 exe。

打包完成后，程序位于：

```text
dist\FolderOrganizer\FolderOrganizer.exe
```

打包目录结构：

```text
dist\FolderOrganizer\FolderOrganizer.exe
dist\FolderOrganizer\_internal\
dist\FolderOrganizer\myfile\
```

把要管理的文件放进 `myfile`。移动程序时，整体移动 `dist\FolderOrganizer` 文件夹即可。

## 测试

```powershell
cd C:\code\organize
$env:PYTHONPATH = ".\src"
python -m unittest discover -s tests
```
