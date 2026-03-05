# 项目规则

## Lint

- PowerShell: mvp_pest_mgda\scripts\lint.ps1
- 命令: python -m ruff check src

## Typecheck

- PowerShell: mvp_pest_mgda\scripts\typecheck.ps1
- 命令: python -m mypy src
 
## 项目记忆

- DSSAT 根目录: C:\DSSAT48
- 作物与实测文件: C:\DSSAT48\Wheat\SWSW7501.WHA, C:\DSSAT48\Wheat\SWSW7501.WHT, C:\DSSAT48\Wheat\SWSW7501.WHX
- 目标函数: 使每个处理的模拟值总体上更接近实测值
