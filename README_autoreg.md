# 寄存器自动生成使用说明

在本目录执行：

```powershell
python autoreg.py <A表格.xlsx> -o <输出文件>.v
```

示例：

```powershell
python autoreg.py test_new.xlsx -o sys_reg.v
```

默认生成 APB 配置接口。需要 regbus 配置接口时：

```powershell
python autoreg.py test_new.xlsx -o sys_reg.v --bus_type regbus
```

生成的 Verilog 文件位于 `-o` 指定的位置，模块名与输出文件名相同。例如 `sys_reg.v` 对应 `module sys_reg`。
