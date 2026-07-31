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

变量寄存器默认使用非压缩数组端口，例如 `input [15:0] ltssm_time [63:0]`。如需生成压缩数组端口，例如 `input [63:0][15:0] ltssm_time`，增加 `--pack_array`：

```powershell
python autoreg.py test_new.xlsx -o sys_reg.v --pack_array
```

生成的 Verilog 文件位于 `-o` 指定的位置，模块名与输出文件名相同。例如 `sys_reg.v` 对应 `module sys_reg`。
