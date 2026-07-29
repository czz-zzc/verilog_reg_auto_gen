# Verilog 寄存器自动生成工具

`gen_reg.py` 根据 Excel 寄存器描述生成 Verilog 寄存器模块，支持普通寄存器、数组寄存器及外部 RAM 表项，并可直接生成 regbus 或 APB 配置接口。

## 使用方法

```sh
python gen_reg.py <输入Excel文件> [-o <输出Verilog文件或目录>] [-p]
```

- `<输入Excel文件>`：寄存器描述 Excel 文件。
- `-o`：输出 Verilog 文件路径；未指定时使用 Excel 中的 `module` 名称。
- `-p`：将普通数组寄存器展开为独立寄存器实现。`RAM_RW` 与 `RAM_RO` 保持 RAM 表项接口生成，并输出 Warning。

示例：

```sh
python gen_reg.py sys_reg.xlsx -o sys_reg.v
```

## A 表格转换

`convert_excel.py` 用于把 A 表格转换为本工具使用的 B 表格：

```sh
python convert_excel.py <A表格.xlsx> -o <B表格.xlsx> --bus_type apb
python gen_reg.py <B表格.xlsx> -o <输出Verilog文件>
```

- A 表格的 `Offset Addr` 已按 byte 地址处理，转换时不会乘 4。
- A 表格的 `Entry` 映射到 B 表格的 `repeat`，格式为 `<数量>*<byte步进>`。
- `Entry` 的数量可为常数或变量；变量范围从第二张 `variables` sheet 读取。范围 `0-N` 转换为数量 `N+1`。
- `Attribute` 直接映射 `RW/RO/W1P/W1C/RC/RAM_RW/RAM_RO`；`pulse` 映射为 `W1P`。
- 通过 `--bus_type apb` 或 `--bus_type regbus` 指定 B 表格的 `cfg_interface`，默认 `apb`。

## 一键生成

`autoreg.py` 用于从 A 表格直接生成 Verilog，内部依次调用转换和生成流程：

```sh
python autoreg.py <A表格.xlsx> -o <输出Verilog文件> --bus_type apb
```

- `--bus_type`：选择 `apb` 或 `regbus`，默认 `apb`。
- `-p`：传递给 `gen_reg.py`，展开普通数组寄存器。
- `--keep_excel`：保留输出目录中的中间 B 表格 `mid.xlsx`；未指定时，成功生成 Verilog 后自动删除。
- 指定 Verilog 文件时，模块名使用输出文件名（如 `-o sys_reg.v` 生成 `module sys_reg`）。
- 转换或生成失败时，中间 B 表格会保留，便于定位问题。

## Excel 格式

寄存器描述位于第一张 sheet。脚本会通过 `offset` 表头定位寄存器表，因此寄存器表各列可以调整顺序。

### 模块信息

寄存器表之前填写模块信息。支持的项目包括：

| 名称 | 说明 |
| --- | --- |
| `module` | 生成的模块名 |
| `owner` | 文件头作者信息 |
| `size` | 地址空间大小，例如 `4KB` |
| `base_addr` | 文件头展示的基地址 |
| `addr_width` | 配置地址宽度 |
| `cfg_interface` | `regbus` 或 `apb`，默认为 `regbus` |

### 寄存器表

至少需要以下表头：`offset`、`repeat`、`reg_name`、`bits`、`field`、`sw_access`、`default`。

- `offset` 仅填写十六进制基地址，例如 `0x100`；不再在该列填写数组变量或步进。
- 标量寄存器的 `repeat` 留空。
- 数组寄存器的 `repeat` 使用 `<数量>*<地址步进>`，例如 `64*0x8` 表示地址为 `0x100`、共 64 项、每项相隔 8 字节，实例下标为 `0` 到 `63`。
- 填写 `repeat` 时必须使用上述格式；未填写时按单个寄存器处理。
- field 名称全局唯一；同一寄存器内的 bit 段不可重叠。

生成前会检查每个数组元素的实际地址：地址必须 4 字节对齐、位于模块地址空间和 `addr_width` 范围内，并且不能与其他寄存器或 RAM 表项重叠。

## 配置接口

### regbus

`cfg_interface=regbus` 时，顶层直接提供：

```verilog
clk, rst_n, reg_addr, wr_en, rd_en, wr_msk, wr_data, rd_data
```

### APB

`cfg_interface=apb` 时，顶层直接提供 APB 从设备接口：

```verilog
pclk, presetn, psel, penable, pwrite, paddr, pwdata, prdata, pready
```

生成模块内部直接完成 APB 到寄存器总线的转换，不会实例化额外的适配模块：

```verilog
wr_en  = psel & penable & pwrite;
rd_en  = psel & ~penable & ~pwrite;
wr_msk = 4'b1111;
pready = 1'b1;
```

## 支持的访问类型

| 类型 | 行为 |
| --- | --- |
| `RW` | 软件可读写，写入遵循字节写掩码。 |
| `RO` | 软件只读，数据由模块外部输入。 |
| `W1P` | 软件写入 `1` 时产生一个时钟周期的脉冲；读取返回 `0`。 |
| `W1C` | 软件写入 `1` 清除对应位；硬件通过 `<field>_hw_en/_hw_val` 更新且优先级更高。 |
| `RC` | 软件读取当前值后清零；硬件通过 `<field>_hw_en/_hw_val` 更新且优先级更高。 |
| `RAM_RW` | 外部单端口读写 RAM 表项。 |
| `RAM_RO` | 外部只读 RAM 表项。 |

### RAM 表项

`RAM_RW` 与 `RAM_RO` 都必须满足：仅一个 field、`offset` 为表基地址、`repeat` 使用 `<数量>*<地址步进>` 定义表深度与步进，且地址步进为正的 2 的幂。默认值可以留空。

`<table>_sel` 为生成模块内部信号，不会出现在顶层端口。

`RAM_RW` 顶层接口包含：

```verilog
output              <table>_en,
output              <table>_we,
output       [A:0]  <table>_addr,
output       [W:0]  <table>_wdata,
output       [W:0]  <table>_wmask,
input        [W:0]  <table>_rdata
```

`RAM_RO` 顶层接口仅包含：

```verilog
output              <table>_en,
output       [A:0]  <table>_addr,
input        [W:0]  <table>_rdata
```

两类表项读取均为一拍延迟：读请求有效时输出地址，外部 RAM 在下一拍提供对应 `rdata`，生成模块再将其合入 `rd_data/prdata`。

## 依赖

```sh
pip install openpyxl
```

Python 标准库还使用 `argparse`、`re`、`datetime`、`os` 与 `sys`。

## 作者

- Engineer：czz
- 初始版本：2025-03-18





