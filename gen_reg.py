#########################################################################################
# Engineer:         czz
# Date:             2025-03-18
# Version:          1.0
# Description: This script is used to generate Verilog register files from an Excel file.
#########################################################################################

import openpyxl
import re
from datetime import datetime
import argparse
import os
import sys
def parse_offset_address(expression):
    """Parse an offset cell; the new Excel format accepts a base address only."""
    value = str(expression).strip()
    if not re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
        raise ValueError(f"Invalid offset {expression!r}; expected a hexadecimal base address such as 0x100")
    return value

def parse_repeat_expression(repeat_value, reg_name):
    """Parse repeat as '<count>*<step>', where count defines the table depth."""
    expression = str(repeat_value).strip()
    match = re.fullmatch(r'([1-9]\d*)\s*\*\s*(0[xX][0-9a-fA-F]+|\d+)', expression)
    if not match:
        raise ValueError(
            f"Invalid repeat expression {repeat_value!r} for register {reg_name!r}; "
            "expected <count>*<step>, for example 64*0x8"
        )

    repeat_count = int(match.group(1), 10)
    step = int(match.group(2), 0)
    if step <= 0:
        raise ValueError(f"Repeat address step of register {reg_name!r} must be positive")
    return repeat_count, step
class Register:
    def __init__(self):
        self.offset = ""
        self.var = ""
        self.var_step = ""
        self.reg_name = ""
        self.var_val= ""
        self.fields = []
        self.wr = ""

class Field:
    def __init__(self):
        self.bits = ""
        self.bits_size = ""
        self.name = ""
        self.sw_access = ""
        self.default = ""

def calculate_bit_width(bit_str):
    bit_str = str(bit_str)  # fix: ensure bit_str is a string
    parts = bit_str.split(':')
    if len(parts) == 1:
        _ = int(parts[0])  # Check if it is a valid integer
        return 1
        
    if len(parts) == 2:
        start = int(parts[0])
        end = int(parts[1])
        return abs(start - end) + 1 
            
    raise ValueError("format bits error: %s" % bit_str)

BUS_DATA_WIDTH = 32

def parse_field_bit_range(bit_str):
    """Parse and validate a field range against the generated 32-bit bus."""
    bit_str = str(bit_str).strip()
    parts = bit_str.split(':')
    if len(parts) == 1:
        start = end = int(parts[0])
    elif len(parts) == 2:
        start, end = map(int, parts)
    else:
        raise ValueError('format bits error: %s' % bit_str)

    if start < 0 or end < 0 or start >= BUS_DATA_WIDTH or end >= BUS_DATA_WIDTH:
        raise ValueError(
            f"Field bit range '{bit_str}' is outside supported range 0:{BUS_DATA_WIDTH - 1}"
        )

    return range(min(start, end), max(start, end) + 1)

def validate_default_value(field):
    """Validate default-value width and ensure known values fit the field."""
    default_str = str(field.default).strip()
    if default_str in ["'0", "'1"]:
        return

    match = re.fullmatch(r"(\d+)'([bBdDhHoO])([0-9a-fA-F_xXzZ?]+)", default_str)
    if match:
        default_width = int(match.group(1))
        if default_width != field.bits_size:
            raise ValueError(
                f"Default width mismatch in field '{field.name}' ({field.bits}): "
                f"expected {field.bits_size}, got {default_width} in '{default_str}'"
            )

        base = match.group(2).lower()
        digits = match.group(3).replace('_', '')
        allowed_digits = {
            'b': r'[01xXzZ?]+',
            'd': r'[0-9xXzZ?]+',
            'h': r'[0-9a-fA-FxXzZ?]+',
            'o': r'[0-7xXzZ?]+',
        }
        if not re.fullmatch(allowed_digits[base], digits):
            raise ValueError(f"Invalid default value '{default_str}' in field '{field.name}'")

        if not re.search(r'[xXzZ?]', digits):
            value = int(digits, {'b': 2, 'd': 10, 'h': 16, 'o': 8}[base])
            if value >= (1 << field.bits_size):
                raise ValueError(
                    f"Default value '{default_str}' exceeds width {field.bits_size} "
                    f"of field '{field.name}' ({field.bits})"
                )
        return

    try:
        value = int(default_str, 0)
    except ValueError:
        raise ValueError(f"Invalid default value '{default_str}' in field '{field.name}'")

    if value < 0 or value >= (1 << field.bits_size):
        raise ValueError(
            f"Default value '{default_str}' exceeds width {field.bits_size} "
            f"of field '{field.name}' ({field.bits})"
        )

def validate_register_bit_ranges(reg):
    """Reject invalid or overlapping field bit ranges within one register."""
    bit_owners = {}

    for field in reg.fields:
        bit_str = str(field.bits).strip()
        field_bits = parse_field_bit_range(bit_str)
        if field.sw_access not in RAM_ACCESS_TYPES:
            validate_default_value(field)
        overlaps = [(bit, bit_owners[bit]) for bit in field_bits if bit in bit_owners]
        if overlaps:
            overlap_bits = ', '.join(str(bit) for bit, _ in sorted(overlaps, reverse=True))
            overlap_fields = ', '.join(sorted({owner for _, owner in overlaps}))
            raise ValueError(
                f'Overlapping bit range in register {reg.reg_name!r}: '
                f'field {field.name!r} ({bit_str}) overlaps field(s) '
                f'{overlap_fields} at bit(s) {overlap_bits}'
            )

        for bit in field_bits:
            bit_owners[bit] = field.name

RAM_RW_ACCESS = 'RAM_RW'
RAM_RO_ACCESS = 'RAM_RO'
RAM_ACCESS_TYPES = {RAM_RW_ACCESS, RAM_RO_ACCESS}

def is_ram_register(reg):
    return len(reg.fields) == 1 and reg.fields[0].sw_access in RAM_ACCESS_TYPES

def is_ram_rw_register(reg):
    return len(reg.fields) == 1 and reg.fields[0].sw_access == RAM_RW_ACCESS

def is_ram_ro_register(reg):
    return len(reg.fields) == 1 and reg.fields[0].sw_access == RAM_RO_ACCESS

def validate_ram_register(reg):
    ram_fields = [field for field in reg.fields if field.sw_access in RAM_ACCESS_TYPES]
    if not ram_fields:
        return
    if len(reg.fields) != 1:
        raise ValueError(f"{ram_fields[0].sw_access} register {reg.reg_name!r} must contain exactly one field")
    if reg.var is None or reg.var_step is None:
        raise ValueError(
            f"{ram_fields[0].sw_access} register {reg.reg_name!r} requires a repeat expression such as 5*0x4"
        )
    step = int(reg.var_step, 16)
    if step <= 0 or (step & (step - 1)):
        raise ValueError(
            f"{ram_fields[0].sw_access} register {reg.reg_name!r} requires a positive power-of-two address step"
        )
def describe_address_owner(reg, index):
    """Return a readable name for one concrete register/table address."""
    kind = f"{reg.fields[0].sw_access} table" if is_ram_register(reg) else 'register'
    array_index = f'[{index}]' if reg.var is not None else ''
    return f"{kind} {reg.reg_name!r}{array_index}"

def validate_register_addresses(registers, module_size, addr_width):
    """Validate the complete address map after expanding register arrays."""
    bytes_per_register = BUS_DATA_WIDTH // 8
    if module_size <= 0:
        raise ValueError('Module size must be positive for address validation')

    max_bus_address = (1 << addr_width) - 1
    occupied_bytes = {}

    for reg in registers:
        base_address = int(reg.offset, 16)
        if reg.var is None:
            indices = [0]
            step = 0
        else:
            if reg.var_val < 0:
                raise ValueError(f"Variable {reg.var!r} for register {reg.reg_name!r} has a negative upper bound")
            step = int(reg.var_step, 16)
            if step <= 0:
                raise ValueError(f"Address step of register {reg.reg_name!r} must be positive")
            indices = range(reg.var_val + 1)

        for index in indices:
            address = base_address + index * step
            last_byte_address = address + bytes_per_register - 1
            owner = describe_address_owner(reg, index)

            if address % bytes_per_register:
                raise ValueError(
                    f"Address 0x{address:x} of {owner} is not {bytes_per_register}-byte aligned"
                )
            if last_byte_address >= module_size:
                raise ValueError(
                    f"Address range 0x{address:x}-0x{last_byte_address:x} of {owner} "
                    f"exceeds module size {module_size}B"
                )
            if last_byte_address > max_bus_address:
                raise ValueError(
                    f"Address range 0x{address:x}-0x{last_byte_address:x} of {owner} "
                    f"exceeds {addr_width}-bit address width"
                )

            for byte_address in range(address, last_byte_address + 1):
                previous = occupied_bytes.get(byte_address)
                if previous is not None:
                    previous_owner, previous_start = previous
                    raise ValueError(
                        f"Address overlap: {owner} at 0x{address:x} overlaps "
                        f"{previous_owner} at 0x{previous_start:x}"
                    )

            for byte_address in range(address, last_byte_address + 1):
                occupied_bytes[byte_address] = (owner, address)
def parse_excel(filename, parallel=False, module_name_override=None):
    wb = openpyxl.load_workbook(filename)
    if not wb.worksheets:
        raise ValueError('Register description file does not contain a worksheet')

    ws = wb.worksheets[0]
    module_info = {}
    registers = []

    header_row_number = None
    header_columns = {}
    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        normalized_headers = [str(value).strip().lower() if value is not None else '' for value in row]
        if 'offset' not in normalized_headers:
            continue
        header_row_number = row_number
        for index, header in enumerate(normalized_headers):
            if not header:
                continue
            if header in header_columns:
                raise ValueError(f"Duplicate column header {header!r} in row {header_row_number}")
            header_columns[header] = index
        break

    if header_row_number is None:
        raise ValueError("Invalid register description file format. 'offset' column not found.")

    required_columns = {'offset', 'repeat', 'reg_name', 'bits', 'field', 'sw_access', 'default'}
    missing_columns = sorted(required_columns - set(header_columns))
    if missing_columns:
        raise ValueError(f"Register description is missing required column(s): {', '.join(missing_columns)}")

    # Module metadata occupies the rows above the register-table header.  Read the
    # first non-empty value after the key so an inserted register-table column does
    # not change the metadata format.
    metadata_keys = {'module', 'owner', 'size', 'base_addr', 'addr_width', 'data_width', 'cfg_interface'}
    for row in ws.iter_rows(max_row=header_row_number - 1, values_only=True):
        if not row or row[0] is None:
            continue
        key = str(row[0]).strip()
        if key not in metadata_keys:
            continue
        value = next((cell for cell in row[1:] if cell is not None and str(cell).strip() != ''), None)
        if value is not None:
            module_info[key] = value

    if not module_info.get('module'):
        raise ValueError("Module name not found in the 'module' metadata row")
    if module_name_override:
        module_info['module'] = module_name_override
    elif str(module_info['module']) not in filename:
        print(
            f"Warning: Module name '{module_info['module']}' does not match filename '{filename}'. "
            'Changing module name to match filename.'
        )
        module_info['module'] = os.path.splitext(os.path.basename(filename))[0]

    module_size_str = str(module_info.get('size', '')).strip()
    if not module_size_str:
        raise ValueError("Module size not found in the 'size' metadata row")
    if module_size_str.upper().endswith('KB'):
        module_size = int(module_size_str[:-2]) * 1024
    elif module_size_str.upper().endswith('B'):
        module_size = int(module_size_str[:-1])
    else:
        module_size = int(module_size_str, 0)

    if 'addr_width' not in module_info:
        raise ValueError("Address width not found in the 'addr_width' metadata row")
    addr_width = int(module_info['addr_width'])
    cfg_interface = str(module_info.get('cfg_interface', 'regbus')).strip().lower()
    if cfg_interface not in {'regbus', 'apb'}:
        raise ValueError(f"Unsupported cfg_interface {cfg_interface!r}; expected 'regbus' or 'apb'")
    module_info['cfg_interface'] = cfg_interface

    def cell_value(row, column_name):
        column_index = header_columns[column_name]
        return row[column_index] if column_index < len(row) else None

    def finalize_register(reg):
        validate_ram_register(reg)
        validate_register_bit_ranges(reg)
        sw_writable = any(field.sw_access in {'RW', 'WO', 'W1P', 'W1C'} for field in reg.fields)
        reg.wr = 'w' if sw_writable else 'r'
        registers.append(reg)

    current_reg = None
    reg_name_set = set()
    field_name_set = set()

    for row_number, row in enumerate(ws.iter_rows(min_row=header_row_number + 1, values_only=True), start=header_row_number + 1):
        offset_value = cell_value(row, 'offset')
        if offset_value is not None and str(offset_value).strip() != '':
            offset = parse_offset_address(offset_value)
            reg_name = cell_value(row, 'reg_name')
            if reg_name is None or str(reg_name).strip() == '':
                raise ValueError(f'Register name not found in row {row_number}')
            reg_name = str(reg_name).strip()

            repeat_value = cell_value(row, 'repeat')
            has_repeat = repeat_value is not None and str(repeat_value).strip() != ''
            if has_repeat:
                repeat_count, repeat_step = parse_repeat_expression(repeat_value, reg_name)

            if reg_name in reg_name_set:
                raise ValueError(f'Duplicate register name found: {reg_name}')
            reg_name_set.add(reg_name)

            if current_reg:
                finalize_register(current_reg)

            current_reg = Register()
            current_reg.offset = offset[2:]
            current_reg.reg_name = reg_name
            if has_repeat:
                # The Excel repeat column replaces the former offset variable.
                # ``var`` remains an internal array marker and is only used for
                # generated-loop naming in parallel mode.
                current_reg.var = 'i'
                current_reg.var_step = hex(repeat_step)[2:]
                current_reg.var_val = repeat_count - 1
            else:
                current_reg.var = None
                current_reg.var_step = None
                current_reg.var_val = None
        bits_value = cell_value(row, 'bits')
        if bits_value is not None and str(bits_value).strip() != '':
            if current_reg is None:
                raise ValueError(f'Field is defined before a register in row {row_number}')
            field_name = cell_value(row, 'field')
            sw_access = cell_value(row, 'sw_access')
            if field_name is None or str(field_name).strip() == '' or sw_access is None or str(sw_access).strip() == '':
                raise ValueError(f'One or more required field columns are missing in row {row_number}')

            field = Field()
            field.bits = bits_value
            field.bits_size = calculate_bit_width(bits_value)
            field.name = str(field_name).strip()
            if field.name in field_name_set:
                raise ValueError(f'Duplicate field name found: {field.name}')
            field_name_set.add(field.name)
            field.sw_access = str(sw_access).strip().upper()
            if field.sw_access not in ['RW', 'WO', 'W1P', 'W1C', 'RO', 'RC', RAM_RW_ACCESS, RAM_RO_ACCESS]:
                raise ValueError(f'Invalid sw_access value: {field.sw_access}')
            field.default = cell_value(row, 'default')
            if field.sw_access not in RAM_ACCESS_TYPES and field.default is None:
                raise ValueError(f'Default value not found for field {field.name!r}')
            current_reg.fields.append(field)

    if current_reg:
        finalize_register(current_reg)

    validate_register_addresses(registers, module_size=module_size, addr_width=addr_width)

    if parallel == True:
        ram_tables = [reg for reg in registers if is_ram_register(reg)]
        if ram_tables:
            table_names = ', '.join(reg.reg_name for reg in ram_tables)
            print(
                f"\033[33mWarning: -p does not expand RAM tables ({table_names}); "
                "they are generated as RAM interfaces.\033[0m",
                file=sys.stderr,
            )

        expanded_registers = []
        for reg in registers:
            if reg.var is not None and not is_ram_register(reg):
                for i in range(reg.var_val + 1):
                    new_reg = Register()
                    new_reg.offset = hex(int(reg.offset, 16) + i * int(reg.var_step, 16))[2:]
                    new_reg.var_step = None
                    new_reg.var = None
                    new_reg.var_val = None
                    new_reg.reg_name = f"{reg.var}{i}_{reg.reg_name}"
                    new_reg.wr = reg.wr
                    for field in reg.fields:
                        new_field = Field()
                        new_field.bits = field.bits
                        new_field.bits_size = field.bits_size
                        new_field.name = f"{reg.var}{i}_{field.name}"
                        new_field.sw_access = field.sw_access
                        new_field.default = field.default
                        new_reg.fields.append(new_field)
                    expanded_registers.append(new_reg)
            else:
                expanded_registers.append(reg)
        expanded_registers.sort(key=lambda reg: int(reg.offset, 16))
        registers = expanded_registers
    return module_info, registers
def generate_verilog(module_info, registers, filename):
    now = datetime.now()
    code = []
    
    _addr_width = int(module_info.get('addr_width', '12'))
    cfg_interface = str(module_info.get('cfg_interface', 'regbus')).strip().lower()
    is_apb = cfg_interface == 'apb'
    ram_regs = [reg for reg in registers if is_ram_register(reg)]
    has_ram = bool(ram_regs)
    ram_select_signal = " | ".join(f"{reg.fields[0].name}_sel" for reg in ram_regs)
    # Header
    header_separator = "//------------------------------------------------------------------------------"
    code.append(header_separator)
    code.append(f"// Filename         : {filename}.v")
    code.append(f"// Author           : {module_info.get('owner', 'unknown')}")
    code.append(f"// Created          : {now.strftime('%Y-%m-%d %H:%M:%S')}")
    code.append( "// Description      : This file is auto generated by gen_reg.py script. Not edit by hand")
    code.append(f"// addr_width       : {_addr_width}")
    code.append(f"// bus_type         : {cfg_interface}")
    code.append(f"// base_addr        : {module_info.get('base_addr', '0')}")
    code.append(header_separator + "\n")    
    # Module declaration
    code.append(f"module {module_info['module']} (")
    if is_apb:
        code.append( "input               pclk,")
        code.append( "input               presetn,")
        code.append( "input               psel,")
        code.append( "input               penable,")
        code.append( "input               pwrite,")
        code.append(f"input       [{_addr_width-1}:0]  paddr,")
        code.append( "input       [31:0]  pwdata,")
        code.append( "output      [31:0]  prdata,")
        code.append( "output              pready,")
    else:
        code.append( "input               clk,")
        code.append( "input               rst_n,")
        code.append(f"input       [{_addr_width-1}:0]  reg_addr,")
        code.append( "input               wr_en,")
        code.append( "input               rd_en,")
        code.append( "input       [3 :0]  wr_msk,")
        code.append( "input       [31:0]  wr_data,")
        code.append("output      [31:0]  rd_data," if has_ram else "output reg  [31:0]  rd_data,")
    # Signals
    for reg in registers:
        if reg.var is not None:# Variable registers
            if is_ram_register(reg):
                field = reg.fields[0]
                ram_addr_width = max(1, reg.var_val.bit_length())
                code.append(f"output              {field.name}_en,")
                if field.sw_access == RAM_RW_ACCESS:
                    code.append(f"output              {field.name}_we,")
                code.append(f"output      [{ram_addr_width-1:02}:0]  {field.name}_addr,")
                if field.sw_access == RAM_RW_ACCESS:
                    code.append(f"output      [{field.bits_size-1:02}:0]  {field.name}_wdata,")
                    code.append(f"output      [{field.bits_size-1:02}:0]  {field.name}_wmask,")
                code.append(f"input       [{field.bits_size-1:02}:0]  {field.name}_rdata,")
                continue
            for field in reg.fields:
                if field.sw_access in ("RW", "WO", "W1P"): 
                    if field.bits_size == 1:
                        code.append(f"output reg          {field.name}[{reg.var_val}:0],")
                    else:
                        code.append(f"output reg  [{field.bits_size-1:02}:0]  {field.name}[{reg.var_val}:0],")
                elif field.sw_access in ("W1C", "RC"):
                    if field.bits_size == 1:
                        code.append(f"input               {field.name}_hw_en[{reg.var_val}:0],")
                        code.append(f"input               {field.name}_hw_val[{reg.var_val}:0],")
                        code.append(f"output reg          {field.name}[{reg.var_val}:0],")
                    else:
                        code.append(f"input               {field.name}_hw_en[{reg.var_val}:0],")
                        code.append(f"input       [{field.bits_size-1:02}:0]  {field.name}_hw_val[{reg.var_val}:0],")
                        code.append(f"output reg  [{field.bits_size-1:02}:0]  {field.name}[{reg.var_val}:0],")
                elif field.sw_access == "RO":
                    if field.bits_size == 1:
                        code.append(f"input               {field.name}[{reg.var_val}:0],")
                    else:
                        code.append(f"input       [{field.bits_size-1:02}:0]  {field.name}[{reg.var_val}:0],")
        else:# Non-variable registers                        
            for field in reg.fields:
                if field.sw_access in ("RW", "WO", "W1P"): 
                    if field.bits_size == 1:
                        code.append(f"output reg          {field.name},")
                    else:
                        code.append(f"output reg  [{field.bits_size-1:02d}:0]  {field.name},")
                elif field.sw_access in ("W1C", "RC"):
                    if field.bits_size == 1:
                        code.append(f"input               {field.name}_hw_en,")
                        code.append(f"input               {field.name}_hw_val,")
                        code.append(f"output reg          {field.name},")
                    else:
                        code.append(f"input               {field.name}_hw_en,")
                        code.append(f"input       [{field.bits_size-1:02}:0]  {field.name}_hw_val,")
                        code.append(f"output reg  [{field.bits_size-1:02}:0]  {field.name},")
                elif field.sw_access == "RO":
                    if field.bits_size == 1:
                        code.append(f"input               {field.name},")
                    else:
                        code.append(f"input       [{field.bits_size-1:02}:0]  {field.name},")
    
    code[-1] = code[-1].rstrip(',')  # Remove last comma
    code.append(");\n")
    if is_apb:
        code.append("//============================================================================")
        code.append("// regbus to apb trans")
        code.append("//============================================================================")
        code.append("wire           clk;")
        code.append("wire           rst_n;")
        code.append(f"wire [{_addr_width-1}:0]    reg_addr;")
        code.append("wire           wr_en;")
        code.append("wire           rd_en;")
        code.append("wire [3 :0]    wr_msk;")
        code.append("wire [31:0]    wr_data;")
        code.append("wire [31:0]    rd_data;" if has_ram else "reg  [31:0]    rd_data;")
        code.append("")
        code.append("assign clk      = pclk;")
        code.append("assign rst_n    = presetn;")
        code.append("assign reg_addr = paddr;")
        code.append("assign wr_en    = psel & penable & pwrite;")
        code.append("assign rd_en    = psel & ~penable & ~pwrite;")
        code.append("assign wr_msk   = 4'b1111;")
        code.append("assign wr_data  = pwdata;")
        code.append("assign prdata   = rd_data;")
        code.append("assign pready   = 1'b1;")
        code.append("")
    
    # Register and wire declarations
    code.append("//============================================================================")
    code.append("// reg and wire declaration")
    code.append("//============================================================================")
    code.append("reg  [31:0]    rd_data_nxt ;")
    if has_ram:
        code.append("reg  [31:0]    normal_rd_data;")
    code.append("wire [31:0]    msk;")
    for reg in ram_regs:
        field = reg.fields[0]
        code.append(f"wire           {field.name}_sel;")
        code.append(f"reg            {field.name}_sel_d;")
        code.append(f"wire [31:0]    {field.name}_rdata_final;")
    
    # Address decode wires
    for reg in registers:
        if is_ram_register(reg):
            continue
        if reg.var is not None:    
            if reg.wr == 'r':
                code.append(f"reg  [31:0]    rd_data_nxt_{reg.reg_name};")
            else:
                code.append(f"reg  [31:0]    rd_data_nxt_{reg.reg_name};")
                code.append(f"wire           wr_en_{reg.reg_name}[{reg.var_val}:0];")
        else:
            if reg.wr == 'w':
                code.append(f"wire           wr_en_{reg.reg_name};")

    # Main code
    code.append("//============================================================================")
    code.append("//main code")
    code.append("//============================================================================")
    code.append("assign msk = {{8{wr_msk[3]}},{8{wr_msk[2]}},{8{wr_msk[1]}},{8{wr_msk[0]}}};\n")
    
    # Address decoding
    code.append("//============================================================================")
    code.append("// reg wr_en/rd_en assignment")
    code.append("//============================================================================")

    gvar_i_declared = False
    ginter_j_declared = False
    # Calculate the maximum length of the left-hand side expressions
    max_lhs_length = 0
    for reg in registers:
        if reg.wr == 'w':
            if reg.var is not None:
                lhs_length = len(f"wr_en_{reg.reg_name}[{reg.var_val}]")
            else:
                lhs_length = len(f"wr_en_{reg.reg_name}")
            if lhs_length > max_lhs_length:
                max_lhs_length = lhs_length


    # Generate the Verilog code with aligned assign statements
    for reg in registers:
        if reg.wr == 'w':
            if reg.var is not None:
                if not gvar_i_declared:
                    code.append("\ngenvar i;")
                    gvar_i_declared = True
                code.append("generate")
                code.append(f"    for(i = 0; i <= {reg.var_val}; i = i + 1) begin: wr_{reg.reg_name}")
                code.append(f"        assign wr_en_{reg.reg_name}[i]= wr_en & (reg_addr[{_addr_width-1}:0] == {_addr_width}'h{reg.offset} + {_addr_width}'h{reg.var_step} * i );")
                code.append(f"    end")
                code.append("endgenerate")
            else:
                lhs = f"wr_en_{reg.reg_name}"
                code.append(f"assign {lhs:<{max_lhs_length}} = wr_en & (reg_addr[{_addr_width-1}:0] == {_addr_width}'h{reg.offset});")
    


    # Register writes
    code.append("\n//============================================================================")
    code.append(  "// reg write")
    code.append(  "//============================================================================")
    for reg in registers:
        if is_ram_register(reg):
            continue
        if reg.var is not None:# Variable registers
            if reg.wr == 'w' or any(field.sw_access == "RC" for field in reg.fields):
                if not gvar_i_declared:
                    code.append("\ngenvar i;")
                    gvar_i_declared = True
                for field in reg.fields:
                    if field.sw_access not in ("RW", "WO", "W1P", "W1C", "RC"):
                        continue
                    code.append( "//============================================================================")
                    code.append(f"// {field.name} addr:{_addr_width}'h{reg.offset} type:{field.sw_access} bits:[{field.bits}] default:{field.default}")
                    code.append("//============================================================================")
                    code.append("generate")
                    code.append(f"    for(i = 0; i <= {reg.var_val}; i = i + 1) begin: wr_{field.name}")
                    code.append(f"        always @(posedge clk or negedge rst_n) begin")
                    code.append(f"            if (!rst_n)")
                    code.append(f"                {field.name}[i] <= {field.default};")
                    code.append(f"            else begin")
                    if field.sw_access in ("RW", "WO"):
                        code.append(f"                if (wr_en_{reg.reg_name}[i] == 1'b1)")
                        if field.bits_size == 1:
                            code.append(f"                    {field.name}[i] <= ({field.name}[i] & ~msk[{field.bits}]) | (wr_data[{field.bits}] & msk[{field.bits}]);")
                        else:
                            code.append(f"                    {field.name}[i][{field.bits_size-1}:0] <= ({field.name}[i][{field.bits_size-1}:0] & ~msk[{field.bits}]) | (wr_data[{field.bits}] & msk[{field.bits}]);")
                    elif field.sw_access == "W1P":
                        code.append(f"                if (wr_en_{reg.reg_name}[i] == 1'b1)")
                        code.append(f"                    {field.name}[i] <= wr_data[{field.bits}] & msk[{field.bits}];")
                    elif field.sw_access == "W1C":
                        code.append(f"                if ({field.name}_hw_en[i] == 1'b1)")
                        code.append(f"                    {field.name}[i] <= {field.name}_hw_val[i];")
                        code.append(f"                else if (wr_en_{reg.reg_name}[i] == 1'b1)")
                        code.append(f"                    {field.name}[i] <= (~wr_data[{field.bits}] | ~msk[{field.bits}]) & {field.name}[i];")
                    elif field.sw_access == "RC":
                        code.append(f"                if ({field.name}_hw_en[i] == 1'b1)")
                        code.append(f"                    {field.name}[i] <= {field.name}_hw_val[i];")
                        code.append(f"                else if (rd_en && (reg_addr[{_addr_width-1}:0] == {_addr_width}'h{reg.offset} + {_addr_width}'h{reg.var_step} * i))")
                        code.append(f"                    {field.name}[i] <= {field.bits_size}'h0;")
                    code.append("            end")
                    code.append("        end")
                    code.append("    end")
                    code.append("endgenerate")
            # Read data logic
            code.append( "//============================================================================")
            code.append(f"// rd_data_nxt_{reg.reg_name}")
            code.append("//============================================================================")
            if not ginter_j_declared:
                code.append("integer j;")
                ginter_j_declared = True
            code.append(f"always @(*) begin")
            code.append(f"    rd_data_nxt_{reg.reg_name}[31:0]  = 32'h0;")
            code.append(f"    for(j = 0; j <= {reg.var_val}; j = j + 1) begin:rdata_loop_{reg.reg_name}")
            code.append(f"        if (reg_addr[{_addr_width-1}:0] == {_addr_width}'h{reg.offset} + {_addr_width}'h{reg.var_step} * j) begin")
            for field in reg.fields:
                if field.sw_access == "WO":
                    continue
                if field.bits_size == 1:
                    code.append(f"            rd_data_nxt_{reg.reg_name}[{field.bits}] = {field.name}[j];")
                else:
                    code.append(f"            rd_data_nxt_{reg.reg_name}[{field.bits}] = {field.name}[j][{field.bits_size -1}:0];")
            code.append("        end")
            code.append("    end")
            code.append("end\n")    
        else:# Non-variable registers                  
            for field in reg.fields:
                if field.sw_access != "RO": 
                    code.append( "//============================================================================")
                    code.append(f"// {field.name} addr:{_addr_width}'h{reg.offset} type:{field.sw_access} bits:[{field.bits}] default:{field.default}")
                    code.append("//============================================================================")
                    code.append("always @(posedge clk or negedge rst_n) begin")
                    code.append("    if (!rst_n)")
                    if field.bits_size == 1:
                        code.append(f"        {field.name} <= {field.default};")
                    else:
                        code.append(f"        {field.name}[{field.bits_size-1}:0] <= {field.default};")
                    code.append("    else begin")
                    if field.sw_access in ("RW", "WO"):
                        code.append(f"        if (wr_en_{reg.reg_name} == 1'b1)")
                        if field.bits_size == 1:
                            code.append(f"            {field.name} <= ({field.name} & ~msk[{field.bits}]) | (wr_data[{field.bits}] & msk[{field.bits}]);")
                        else:
                            code.append(f"            {field.name}[{field.bits_size-1}:0] <= ({field.name}[{field.bits_size-1}:0] & ~msk[{field.bits}]) | (wr_data[{field.bits}] & msk[{field.bits}]);")
                    elif field.sw_access == "W1P":
                        code.append(f"        if (wr_en_{reg.reg_name} == 1'b1)")
                        code.append(f"            {field.name} <= wr_data[{field.bits}] & msk[{field.bits}];")
                        code.append("        else")
                        code.append(f"            {field.name} <= 1'b0;")
                    elif field.sw_access == "W1C":
                        code.append(f"        if ({field.name}_hw_en == 1'b1)")
                        code.append(f"            {field.name} <= {field.name}_hw_val;")
                        code.append(f"        else if (wr_en_{reg.reg_name} == 1'b1)")
                        code.append(f"            {field.name} <= (~wr_data[{field.bits}] | ~msk[{field.bits}]) & {field.name};")
                    
                    elif field.sw_access == "RC":
                        code.append(f"        if ({field.name}_hw_en == 1'b1)")
                        code.append(f"            {field.name} <= {field.name}_hw_val;")
                        code.append(f"        else if (rd_en && (reg_addr[{_addr_width-1}:0] == {_addr_width}'h{reg.offset}))")
                        code.append(f"            {field.name} <= {field.bits_size}'h0;")

                    code.append("    end")
                    code.append("end\n")
    
    #============================================================================
    # RAM table interfaces
    #============================================================================
    for reg in ram_regs:
        field = reg.fields[0]
        ram_addr_width = max(1, reg.var_val.bit_length())
        table_last_offset = hex(int(reg.offset, 16) + reg.var_val * int(reg.var_step, 16))[2:]
        code.append("//============================================================================")
        code.append(f"// {field.name} addr:{_addr_width}'h{reg.offset} type:{field.sw_access} bits:[{field.bits}] depth:{reg.var_val + 1}")
        code.append("//============================================================================")
        code.append(f"assign {field.name}_sel   = (reg_addr >={_addr_width}'h{reg.offset}) && (reg_addr <= {_addr_width}'h{reg.offset}+ {reg.var_val} * {_addr_width}'h{reg.var_step});")
        if field.sw_access == RAM_RW_ACCESS:
            code.append(f"assign {field.name}_en    = {field.name}_sel  & (wr_en | rd_en);")
            code.append(f"assign {field.name}_we    = {field.name}_sel  & wr_en;")
        else:
            code.append(f"assign {field.name}_en    = {field.name}_sel  & rd_en;")
        code.append(f"assign {field.name}_addr  = (reg_addr - {_addr_width}'h{reg.offset}) >> {int(reg.var_step, 16).bit_length() - 1};")
        if field.sw_access == RAM_RW_ACCESS:
            code.append(f"assign {field.name}_wdata = wr_data[{field.bits_size-1}:0];")
            code.append(f"assign {field.name}_wmask = msk[{field.bits_size-1}:0];")
        code.append("")
        code.append("always @(posedge clk or negedge rst_n) begin")
        code.append("    if (!rst_n)")
        code.append(f"        {field.name}_sel_d <= 1'b0;")
        code.append("    else")
        code.append(f"        {field.name}_sel_d <= rd_en & {field.name}_sel;")
        code.append("end")
        if field.bits_size == 32:
            rdata_expr = f"{field.name}_rdata[31:0]"
        else:
            zero_extend = f"{{{32 - field.bits_size}{{1'b0}}}}"
            rdata_expr = f"{{{zero_extend}, {field.name}_rdata[{field.bits_size-1}:0]}}"
        code.append(f"assign {field.name}_rdata_final = ({{32{{{field.name}_sel_d}}}} & {rdata_expr});")
        code.append("")
    # Read data logic
    code.append("//============================================================================")
    code.append("// next read data")
    code.append("//============================================================================")
    code.append("always @(*) begin")
    code.append("    rd_data_nxt[31:0] = 32'h0;")
    code.append(f"    case(reg_addr[{_addr_width-1}:0])")
    
    for reg in registers:
        if reg.var is None:
            addr = reg.offset
            code.append(f"    {_addr_width}'h{addr}: begin")
            for field in reg.fields:
                if field.sw_access in ("WO", "W1P"):
                    code.append(f"        rd_data_nxt[{field.bits}] = {field.bits_size}'h0;")
                else:
                    if field.bits_size == 1:
                        code.append(f"        rd_data_nxt[{field.bits}] = {field.name};")
                    else:   
                        code.append(f"        rd_data_nxt[{field.bits}] = {field.name}[{field.bits_size-1}:0];")
            code.append("    end")
    all_var_none = all(reg.var is None or is_ram_register(reg) for reg in registers)
    if all_var_none:
        code.append("    default:")
        code.append("        rd_data_nxt = 32'h0;")
    else:
        # Default read data for variable registers
        default_signal = []  
        for reg in registers:
            if reg.var is not None and not is_ram_register(reg):
                default_signal.append(f"rd_data_nxt_{reg.reg_name} | ")
        # Remove last " | "
        default_signal = "".join(default_signal)[:-3]
        code.append( "    default: ")
        code.append(f"        rd_data_nxt = {default_signal};")
    code.append("    endcase")
    code.append("end\n")
    
    read_data_target = "normal_rd_data" if has_ram else "rd_data"

    # Final read data register
    code.append("//============================================================================")
    code.append("// read data")
    code.append("//============================================================================")
    code.append("always @(posedge clk or negedge rst_n) begin")
    code.append("    if (!rst_n)")
    code.append(f"        {read_data_target}[31:0] <= 32'h0; ")
    if has_ram:
        code.append("    else if (rd_en) begin")
        code.append(f"        if ({ram_select_signal})")
        code.append("            normal_rd_data[31:0] <= 32'h0;")
        code.append("        else")
        code.append("            normal_rd_data[31:0] <= rd_data_nxt[31:0];")
        code.append("    end")
    else:
        code.append("    else if (rd_en)")
        code.append("        rd_data[31:0] <= rd_data_nxt[31:0];")
    code.append("end\n")
    
    if has_ram:
        ram_read_data = " | ".join(f"{reg.fields[0].name}_rdata_final" for reg in ram_regs)
        code.append(f"assign rd_data = normal_rd_data | {ram_read_data};")

    code.append("endmodule")
    
    return "\n".join(code)

# if __name__ == "__main__":
#     module_info, registers = parse_excel("sys_reg.xlsx",parallel=False)
#     verilog_code = generate_verilog(module_info, registers, "sys_reg")
#     with open("sys_pcie_reg.v", "w") as f:
#         f.write(verilog_code)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate Verilog registers from Excel')
    parser.add_argument('input', help='Input Excel file')
    parser.add_argument('-o', '--output', help='Output path or file. Can be a directory path (generates module_name.v) or complete file path')
    parser.add_argument('-p', '--parallel', action='store_true', help='Enable parrllel implement for loop. Default by array implement')
    args = parser.parse_args()

    try:
        module_info, registers = parse_excel(args.input, parallel=args.parallel)
    except (ValueError, OSError) as error:
        print(f'\033[31mError: {error}\033[0m', file=sys.stderr)
        sys.exit(1)
    
    # Handle output path/file logic
    if args.output:
        output_path = args.output
        
        # Check if output_path is a directory or a file
        if os.path.isdir(output_path) or (not os.path.exists(output_path) and not output_path.endswith('.v')):
            # It's a directory path (existing or new directory without .v extension)
            output_dir = output_path
            output_file = os.path.join(output_dir, f"{module_info['module']}.v")
        else:
            # It's a complete file path
            output_dir = os.path.dirname(output_path)
            output_file = output_path
        
        # Create directory if it doesn't exist
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
    else:
        # Default: generate in current directory
        output_file = f"{module_info['module']}.v"
    
    verilog_code = generate_verilog(module_info, registers, os.path.basename(output_file).split('.')[0])
    with open(output_file, 'w') as f:
        f.write(verilog_code)
    print(f"Successfully generated {output_file}")

