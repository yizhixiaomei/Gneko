# 把 Gneko 打包成单文件 Windows exe（免装 Python）
# 用法：在仓库根目录执行  pwsh -File tools\build_exe.ps1
#       指定英文版： pwsh -File tools\build_exe.ps1 -Entry Gneko_en.py -Name Gneko-en

param(
    [string]$Entry = 'Gneko.py',
    [string]$Name  = 'Gneko'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. 确认打包器与依赖
py -3 -m PyInstaller --version > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    py -3 -m pip install pyinstaller
}
py -3 -c "import PIL, tkinter" > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    throw '缺少 Pillow 或 Tk，请先 pip install -r requirements.txt'
}

# 2. 图标（从 awake.png 现场生成多尺寸 ico）
py -3 -c @"
from PIL import Image
Image.open(r'Gneko_png/awake.png').convert('RGBA').save(
    r'docs/gneko.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
"@

# 3. 打包：素材随 exe 内嵌，配置与日志写回 exe 所在目录
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name $Name `
    --icon docs\gneko.ico `
    --add-data "Gneko_png;Gneko_png" `
    --add-data "skins;skins" `
    --add-data "README.md;." `
    --add-data "README.en.md;." `
    --add-data "LICENSE;." `
    --add-data "requirements.txt;." `
    --exclude-module numpy --exclude-module pytest `
    $Entry

$exe = Join-Path $root "dist\$Name.exe"
if (-not (Test-Path $exe)) { throw '打包失败：没有生成 exe' }
'{0}  {1:N1} MB' -f $exe, ((Get-Item $exe).Length / 1MB)
