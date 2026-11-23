# 寄存器 Excel 填写说明

本说明适用于 `autoreg.py` 输入的 `.xlsx` 寄存器描述文件。一个文件描述一个模块，按“模块信息 → 寄存器字段 → 数组变量”的顺序填写。

## 1. 模块信息

在寄存器工作表顶部填写，名称放在第一列，值放在右侧。模块信息必须位于寄存器表头之前。

| 名称 | 示例值 | 填写要求 |
| --- | --- | --- |
| `Module` | `sys_reg` | 必填，使用合法的 Verilog 模块名。指定输出文件时，最终模块名以文件名为准。 |
| `ID` | `12` | 地址位宽，单位为 bit；留空默认 12，对应 `0x000`～`0xFFF`。 |
| `Base Addr` | `32'h0000` | 可选，仅用于文件头说明，不参与地址译码；默认 `32'h0000`。 |

工作簿中只保留一张包含 `Module` 信息和寄存器表的工作表。变量定义放在其他工作表。

## 2. 寄存器表头

建议使用以下列名，列顺序可调整，表头不区分大小写：

| 列名 | 填写内容 | 示例 |
| --- | --- | --- |
| `Reg Name` | 寄存器名称；每个寄存器的首行填写。 | `control` |
| `Offset Addr` | 相对模块起点的字节偏移地址，与寄存器名称同时填写。 | `0x100` |
| `Entry` | 数组数量与字节步进；标量留空。 | `8*0x4` |
| `Bits` | 字段位段，高位在前；单 bit 只填位号，不加方括号。 | `15:8`、`0` |
| `Field Name` | 字段名，作为生成端口的名称或前缀。 | `ctrl_enable` |
| `Attribute` | 访问类型，建议显式填写。 | `RW` |
| `Default Value` | 字段自身的复位值，不按寄存器位段左移。 | `0x12`、`8'h12` |
| `Info` | 可选，控制字段屏蔽、内部写权限、偶校验、中断分组和宽字段拼接。 | `LOCK_GEN; PARITY_GEN`、`int:group0`、`comb:g0` |
| `Reg Description` | 可选，寄存器说明。 | `控制寄存器` |
| `Field Description` | 可选，字段说明。 | `使能控制` |

名称建议使用字母或下划线开头，仅包含字母、数字和下划线，避免 Verilog 关键字。寄存器名不得重复。默认要求字段名在整个模块内唯一。使用 `--name_type reg_field` 时，不同寄存器可复用字段名，生成的完整名称仍须唯一，并避免与总线端口及自动生成的辅助信号重名。

### 多字段寄存器

一个字段占一行。首行填写 `Reg Name`、`Offset Addr` 和 `Entry`；后续字段的这三列留空，直到下一个寄存器开始。不要合并单元格或用重复的寄存器名称表示后续字段。

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value |
| --- | --- | --- | --- | --- | --- | --- |
| control | 0x000 | | 0 | ctrl_enable | RW | 0 |
| | | | 3:1 | ctrl_mode | RW | 3'h2 |
| | | | 8 | ctrl_start | W1P | 0 |
| status | 0x004 | | 0 | status_done | RCI | |
| | | | 7:4 | status_code | RO | 0 |

`ctrl_mode` 的复位值填写 `2` 或 `3'h2`，不能填写左移后的 `4`。

### 版本字段

标准表格使用以下两个标量字段，`Entry` 留空，字段名按下表小写填写；地址可按模块实际规划。

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value |
| --- | --- | --- | --- | --- | --- | --- |
| version | 0x000 | | 31:8 | rtl_version | RO | 24'h0 |
| | | | 7:0 | reg_version | RO | 8'h00 |

`rtl_version` 是 24 bit 外部输入，连接 RTL 代码版本号。`reg_version` 不生成端口，读取返回本次生成使用的常量；默认值必须是确定的 0～255 数值，不支持 X/Z。

调用 `autoreg.py` 时，两个字段齐全则将 `reg_version` 默认值加 1 后生成 RTL，成功后回写源 Excel（例如 `8'hff` → `8'h00`）。生成失败时不更新源表。缺少任一字段时输出红色 Warning，继续生成且不递增；若仅有 `reg_version`，仍按当前默认值生成常量读回。生成成功日志会用红色提醒将代码及 Excel 一并提交至 SVN 或 Git。

## 3. 访问类型

| Attribute | 用途及填写要求 |
| --- | --- |
| `RW` | 软件读写配置。 |
| `RO` | 软件只读，值由外部输入。 |
| `WO` | 软件只写，读取返回零；生成时输出 Warning，保留该字段。 |
| `W1P` | 写 1 触发一拍脉冲，也可填写 `pulse`，读取返回零。 |
| `event` | 软件写 1 清零，等宽输入 `<field>_hw_set` 逐位置位，硬件优先，字段输出到端口。旧表中的 `W1C` 按此类型生成。 |
| `one-shot` | 软件写 1 置位；等宽输入 `<field>_hw_clr` 逐位清零，硬件优先；也接受 `one_shot`、`one shot`，字段输出到端口。 |
| `RWW` | 软件读写；通过 `<field>_hw_en/_hw_val` 更新整个字段，硬件优先，字段输出到端口。 |
| `cnt` | 软件读写；1 bit 输入 `<field>_hw_inc` 每拍加 1，计数到全 1 后保持；有效软件写优先，字段输出到端口。 |
| `rcnt` | 同 cnt，但溢出后回卷为零。 |
| `RC` | 读后清零，值由生成模块维护，硬件通过 `<field>_hw_en/_hw_val` 更新，硬件更新优先。 |
| `RCI` | 读后通知外部清零；值通过 `<field>` 输入，清零指示为 `<field>_hw_clc`。默认值留空。 |
| `RAM_RW` | 外部读写 RAM 表，按第 5 节填写。 |
| `RAM_RO` | 外部只读 RAM 表，按第 5 节填写。 |

访问类型不区分大小写；留空按 `RW` 处理。`R/W`、`R/O`、`R/C`、`R/W/W` 分别等价于 `RW`、`RO`、`RC`、`RWW`，A 表 Attribute 和 B 表 sw_access 均支持。填写不支持的类型会警告并跳过整个寄存器，因此不要使用自定义属性表示保留字段。

`W1S` 是字段过滤项。同地址仍有其他字段时保留这些字段，整个寄存器都被过滤时省略该寄存器。

普通字段的默认值留空按零处理。显式填写时支持十进制、`0x` 十六进制及带位宽的 Verilog 数值；数值必须落在字段宽度范围内，Verilog 数值的位宽须与字段宽度一致。`RO` 的实际输入值由外部决定。

## 4. 寄存器数组

`Entry` 格式为 `<数量>*<字节步进>`。例如：

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value |
| --- | --- | --- | --- | --- | --- | --- |
| channel_cfg | 0x100 | 4*0x8 | 7:0 | channel_mode | RW | 0 |

此例包含 4 个元素，下标为 `0`～`3`，地址分别为 `0x100`、`0x108`、`0x110`、`0x118`。数量是元素总数，不是最大下标；步进单位为字节。

### 使用变量定义数量

可新增一张 `variables` 工作表：

| Name | Range |
| --- | --- |
| CHANNEL | 0-7 |

寄存器表填写 `Entry=CHANNEL*0x4`，即 8 个元素、步进 4 字节。变量范围必须从零开始，也支持 `0~7`；变量名区分大小写且不得重复定义。

## 5. RAM 表

每张 RAM 表只填写一个字段，`Entry` 必填。建议 `Bits` 从 bit 0 开始；超过 32 bit 时必须填写 `W-1:0`，并按下文的大位宽规则设置步进。默认值可留空，外部 RAM 内容不由模块复位。

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value |
| --- | --- | --- | --- | --- | --- | --- |
| config_table | 0x200 | 16*0x4 | 15:0 | config_ram | RAM_RW | |
| status_table | 0x300 | 8*0x4 | 31:0 | status_ram | RAM_RO | |

`config_ram` 深度为 16、数据宽度为 16 bit。生成端口使用 `Field Name` 作为前缀，例如 `config_ram_en`、`config_ram_addr`、`config_ram_rdata`。

地址步进必须为正的 2 的幂，并满足 4 字节对齐。表内地址不能与其他寄存器或表元素重叠。

是否使用等待握手由命令行 `--table_pending` 决定，无需在表格中增加标记。接口连接和时序见 [README](README.md) 的 RAM 表接口章节。

### 大位宽字段

超过 32 bit 时仅支持 RW、RO、RAM_RW、RAM_RO。每个寄存器只填一个字段，`Bits` 从 bit 0 开始，无需新增 Info 标记。例如：

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value |
| --- | --- | --- | --- | --- | --- | --- |
| WIDE_REG_TEST | 0x600 | | 94:0 | wide_reg_test | RW | 95'h1 |
| WIDE_RO_TEST | 0x610 | | 94:0 | wide_ro_test | RO | 0 |
| WIDE_RAM_RW_TEST | 0x620 | 2*0x10 | 94:0 | wide_ram_rw_test | RAM_RW | 0 |
| WIDE_RAM_RO_TEST | 0x640 | 2*0x10 | 94:0 | wide_ram_ro_test | RAM_RO | 0 |

- `wide_reg_test` 占用 `0x600/0x604/0x608`，依次对应 `[31:0]/[63:32]/[94:64]`。低段写入影子寄存器，最高地址写入才提交全部 95 bit；读取最终已提交值。
- RO 的最低地址读取锁存完整输入，后续读同一快照。RAM_RO/RAM_RW 的最低地址读取整条 RAM 并锁存，后续地址不再访问 RAM。
- RAM_RW 暂存每段数据及写掩码，最高地址才提交一次外部 RAM 写入。软件须按低到高顺序完成同一 entry，不能在同一表内交错访问不同 entry。
- 一个元素占用 `ceil(位宽/32)*4` 字节，最后一段不足 32 bit 的高位读零、写忽略。数组步进不得小于此值；RAM 步进须为 2 的幂，95 bit 至少使用 `0x10`。
- 普通大位宽数组同样支持 `-p`、`--pack_array`。RW 可启用 PARITY_GEN，校验完整提交值；软件写入与提交仍受 LOCK_GEN 控制。

测试表已包含以上示例，以及 65 bit RW 数组、96 bit RO 数组、EVENT、one-shot 三种拼写、RWW、CNT、RCNT、W1S 字段过滤、中断组及普通 RAM/RCI 类型。原有 `reg_lock_en` 默认 0，软件测试前须向 `0x0` 的 bit 0 写 1 打开写权限。

完整时序及读写掩码规则见 [README 的大位宽分段访问说明](README.md#大位宽分段访问)。

原表若已将宽字段拆成多个地址，可在每段的 `Info` 中填写同一个 `comb:<组名>`。下面三行合成基址 `0x600`、位段 `94:0` 的 RAM，生成的接口名以 `g0_` 开头。

| Reg Name | Offset Addr | Entry | Bits | Field Name | Attribute | Default Value | Info |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G0_LOW | 0x600 | 2*0x10 | 31:0 | g0_low | RAM_RW | | comb:g0 |
| G0_MID | 0x604 | | 31:0 | g0_mid | RAM_RW | | comb:g0 |
| G0_HIGH | 0x608 | | 30:0 | g0_high | RAM_RW | | comb:g0 |

- 每段独占一个寄存器地址，地址连续增加 4，访问类型相同。除最高段可为 1～32 bit 外，其余段均为 32 bit。`Bits` 可填写每个总线字内的位段，也可填写整字段位段，如 `31:0`、`63:32`、`94:64`。
- 普通标量的 `Entry` 留空。数组和 RAM 的最低地址行填写 `Entry`，其余行可留空或填相同值。组名区分大小写，须为 Verilog 标识符并避免和其他字段重名。
- `RW` 的各段默认值按地址拼接。任一段填 `PARITY_GEN` 时，对拼接后的完整 `RW` 值做校验。已经用单行表示的大位宽字段可继续直接填写 `W-1:0`。

## 6. 屏蔽字段

在该字段行的 `Info` 中填写 `NO_RTL_GEN`，即可不生成该字段。匹配不区分大小写，也允许包含其他文字，例如 `暂不实现 no_rtl_gen`。

仅屏蔽当前字段，不影响同一寄存器的其他字段；全部字段被屏蔽时，整个寄存器省略。即使首行字段被屏蔽，仍需保留该行有效的寄存器名称、地址和数组定义，供后续字段使用。

未使用的保留位可以不填写字段，读取时返回零。

### 功能标记 LOCK_GEN / PARITY_GEN

在对应字段行的 `Info` 填写标记。标记名不区分大小写，可用分号、逗号、换行或空格分隔，也可用成对的单引号或双引号包住，例如 `'PARITY_GEN'; "comb:g0"` 或 `int:group0; PARITY_GEN`。

| Bits | Field Name | Attribute | Default Value | Info |
| --- | --- | --- | --- | --- |
| 0 | cfg_write_en | RW | 0 | LOCK_GEN; PARITY_GEN |
| 15:8 | cfg_mode | RW | 0 | PARITY_GEN |

- `LOCK_GEN` 只能用于标量 1 bit RW，每张有效寄存器工作表最多一个，数组不允许。该字段不生成值输出端口，但可经总线读写；默认 0 时，软件须先写 1 打开其他软件写入权限。
- 写权限按当前值判断，仅控制字段自身豁免，同地址其他字段仍受控。硬件更新和读操作不受影响。
- `PARITY_GEN` 只能用于 RW/WO，数组逐元素校验；生成独立校验位和逐字段时序错误输出，错误汇总与保持由系统安全岛处理。锁字段也可同时启用，隐藏值端口但输出错误端口，校验不一致时关闭其他写权限。
- `NO_RTL_GEN` 字段被忽略，不参与锁数量和校验属性检查。不支持的功能组合会报错。

错误接口及恢复行为见 [README](README.md) 的 Info 功能标记说明。

### 中断分组 int:

在同组的三个字段行填写相同的 `int:<组名>`：

| Reg Name | Offset Addr | Bits | Field Name | Attribute | Default Value | Info |
| --- | --- | --- | --- | --- | --- | --- |
| irq_status | 0x400 | 7:0 | irq_pending | event | 0 | int:group0 |
| irq_mask | 0x404 | 7:0 | irq_mask_bits | RW | 0xff | int:group0 |
| irq_test | 0x408 | 7:0 | irq_test_bits | W1P | 0 | int:group0 |

此例输出 `irq_pending`、`irq_pending_irq`，输入 `irq_pending_hw_set`；`irq_mask_bits` 和 `irq_test_bits` 仅在模块内部保存。mask=1 表示屏蔽，以上默认值屏蔽全部中断源。中断输出为 `|(irq_pending & ~irq_mask_bits)`。

每组必须恰有 EVENT、W1P、RW 各一个，位宽一致，数组元素数也须一致。组名区分大小写。`int:` 和 `comb:` 的未加引号组名都读到第一个分号、逗号或空白为止。若中断组名本身含这些字符，给整个标记加引号，例如 `"int:组 A"; PARITY_GEN`。组内 RW 可加偶校验，与 LOCK_GEN 互斥。

软件测试写 1 在写入沿生成 W1P 脉冲，EVENT 在下一时钟沿锁存并触发未屏蔽中断。硬件/测试置位优先于软件清零，mask 不影响状态记录。软件清零只清除写入 1 且写掩码有效的位。

## 7. 填写检查

- 地址以字节为单位，填写模块内偏移，不叠加 `Base Addr`；每个元素的所有 32 bit 地址槽都必须位于地址位宽范围内。当前模块地址空间上限为 64KB。
- 所有寄存器及数组元素地址须 4 字节对齐且不重叠；数组范围需包含全部元素后再检查。
- 普通字段 `Bits` 仅使用 `0`～`31`，同一寄存器的字段位段不得重叠；大位宽字段须符合上文的类型、单字段和 `W-1:0` 约束。
- 每个保留的寄存器至少有一个有效字段；字段不能出现在首个寄存器之前。
- 建议将 `Bits`、`Entry` 和 Verilog 默认值单元格设为文本格式，避免 Excel 自动识别为时间或日期。

填写完成后执行：

```sh
python autoreg.py <寄存器描述.xlsx> -o <模块名>.v
```
