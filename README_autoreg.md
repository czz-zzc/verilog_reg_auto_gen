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

标准表格应包含两个标量 RO 字段：`rtl_version[31:8]` 和 `reg_version[7:0]`，字段名使用上述小写名称。`rtl_version` 保留 24 bit 输入端口；`reg_version` 无端口，读取返回本次生成使用的表格版本常量。

每次调用 `autoreg.py`，若两个字段均存在，则将 `reg_version` 默认值加 1（255 回卷为 0），用于生成 RTL 和中间表。生成及可用的编译检查通过后，将新值回写输入 Excel 的 `Default Value` 单元格。失败时不递增源表；缺少任一字段时输出红色 Warning，继续生成且不递增。版本字段的类型或位段填写错误会报错。

生成成功后会用红色日志提醒及时将 RTL 代码及 Excel 表格一并提交至 SVN 或 Git。单独运行 `convert_excel.py` 或 `gen_reg.py` 不递增版本号。
