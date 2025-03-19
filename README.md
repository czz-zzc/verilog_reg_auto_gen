# verilog_reg_auto_gen

## Description
This project contains a Python script (`gen_reg.py`) that generates Verilog register files from an Excel file. The script parses the Excel file to extract module information and register definitions, and then generates a Verilog file based on the extracted data.

## Usage
To use the script, run the following command:

```sh
python gen_reg.py <input_excel_file> [-o <output_verilog_file>] [-p]
```

- `<input_excel_file>`: The path to the input Excel file containing the register definitions.
- `-o <output_verilog_file>`: (Optional) The name of the output Verilog file. If not specified, the module name from the Excel file will be used.
- `-p`: (Optional) Enable parallel implementation for loop. Default is array implementation.

## Example
```sh
python gen_reg.py sys_reg.xlsx -o sys_reg.v -p
```

This command will generate a Verilog file named `sys_reg.v` from the `sys_reg.xlsx` Excel file with parallel implementation enabled.

## Dependencies
- `openpyxl`: To install, run `pip install openpyxl`
- `argparse`

## Author
- Engineer: czz
- Date: 2025-03-18
- Version: 1.0

