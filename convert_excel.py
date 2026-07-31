#########################################################################################
# Engineer:         czz
# Date:             2025-10-28
# Version:          2.0
# Description: Convert A-format register Excel files to the B format consumed by gen_reg.py
#########################################################################################

import argparse
import os
import re

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill


B_HEADERS = [
    'offset', 'repeat', 'reg_name', 'bits', 'field',
    'sw_access', 'hw_access', 'default', 'attribute', 'description',
]
SUPPORTED_ACCESS = {'RW', 'WO', 'RO', 'W1P', 'W1C', 'RC', 'RAM_RW', 'RAM_RO'}


def normalize_header(value):
    """Normalize an A-table header for alias matching."""
    if value is None:
        return ''
    return re.sub(r'\s+', '_', str(value).strip().lower())


def parse_integer(value, field_name):
    """Parse an integer stored as a decimal or hexadecimal Excel value."""
    if isinstance(value, bool):
        raise ValueError(f'{field_name} must be an integer, not a boolean')
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)

    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith('0x') else int(text, 10)
    except ValueError as error:
        raise ValueError(f'Invalid {field_name}: {value!r}') from error


def calculate_bit_width(bit_str):
    """Return a field width from a bit index or range such as 31:16."""
    if bit_str is None or str(bit_str).strip() == '':
        raise ValueError('Field bits are required')

    parts = str(bit_str).strip().split(':')
    if len(parts) == 1:
        int(parts[0])
        return 1
    if len(parts) == 2:
        high, low = map(int, parts)
        return abs(high - low) + 1
    raise ValueError(f'Invalid bit range: {bit_str!r}')


def parse_default_value(default_value, bit_width):
    """Convert an A-table default value to a B-table Verilog literal."""
    if default_value is None or str(default_value).strip() == '':
        return f"{bit_width}'h0"

    text = str(default_value).strip()
    if re.fullmatch(r"\d+'[bBdDhHoO][0-9a-fA-F_xXzZ?]+", text):
        return text

    try:
        number = parse_integer(text, 'default value')
    except ValueError as error:
        raise ValueError(f'Invalid default value {default_value!r}') from error

    if number < 0 or number >= (1 << bit_width):
        raise ValueError(f"Default value {default_value!r} exceeds field width {bit_width}")
    return f"{bit_width}'h{number:x}"


def convert_attribute_to_sw_access(attribute):
    """Map A-table attributes to B-table software-access values."""
    if attribute is None or str(attribute).strip() == '':
        return 'RW'

    access = str(attribute).strip().upper()
    if access == 'PULSE':
        return 'W1P'
    if access not in SUPPORTED_ACCESS:
        raise ValueError(f'Unsupported Attribute value: {attribute!r}')
    return access


def find_table_header(ws):
    """Locate the A-table header and return normalized header-to-column indexes."""
    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        headers = [normalize_header(value) for value in row]
        if 'reg_name' in headers and 'offset_addr' in headers:
            return row_number, {header: index for index, header in enumerate(headers) if header}
    raise ValueError("A table header containing 'Reg Name' and 'Offset Addr' was not found")


def cell_value(row, columns, name):
    index = columns.get(name)
    return row[index] if index is not None and index < len(row) else None


def parse_variable_ranges(wb):
    """Read variable ranges such as a: 0-3 from A table's variables sheet."""
    if len(wb.worksheets) < 2:
        return {}

    ws = wb.worksheets[1]
    header_row = None
    columns = {}
    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        headers = [normalize_header(value) for value in row]
        name_aliases = {'name', 'variable_name', '变量名称'}
        range_aliases = {'range', 'variable_range', '变量范围'}
        name_index = next((index for index, header in enumerate(headers) if header in name_aliases), None)
        range_index = next((index for index, header in enumerate(headers) if header in range_aliases), None)
        if name_index is not None and range_index is not None:
            header_row = row_number
            columns = {'name': name_index, 'range': range_index}
            break

    if header_row is None:
        return {}

    ranges = {}
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        name = cell_value(row, columns, 'name')
        range_value = cell_value(row, columns, 'range')
        if name is None or str(name).strip() == '':
            continue
        if range_value is None or str(range_value).strip() == '':
            raise ValueError(f"Variable {name!r} has no range")

        match = re.fullmatch(r'\s*(\d+)\s*(?:~|-)\s*(\d+)\s*', str(range_value))
        if not match:
            raise ValueError(f"Invalid range {range_value!r} for variable {name!r}; expected 0-N")
        lower, upper = map(int, match.groups())
        if lower != 0 or upper < lower:
            raise ValueError(f"Variable {name!r} range must start at 0, got {range_value!r}")
        ranges[str(name).strip()] = upper

    return ranges


def parse_entry(entry_value, variable_ranges, reg_name):
    """Map A entry '<count-or-variable>*<byte-step>' to B repeat '<count>*<step>'."""
    if entry_value is None or str(entry_value).strip() == '':
        return None

    expression = str(entry_value).strip()
    match = re.fullmatch(r'([A-Za-z_]\w*|[1-9]\d*)\s*\*\s*(0[xX][0-9a-fA-F]+|\d+)', expression)
    if not match:
        raise ValueError(
            f"Invalid Entry {entry_value!r} for register {reg_name!r}; expected <count-or-variable>*<byte-step>"
        )

    count_token, step_token = match.groups()
    if count_token[0].isalpha() or count_token[0] == '_':
        if count_token not in variable_ranges:
            raise ValueError(f"Entry variable {count_token!r} of register {reg_name!r} is not defined in variables")
        count = variable_ranges[count_token] + 1
    else:
        count = int(count_token, 10)

    step = parse_integer(step_token, f'Entry step of register {reg_name!r}')
    if count <= 0 or step <= 0:
        raise ValueError(f"Entry {entry_value!r} of register {reg_name!r} must have positive count and step")
    return f'{count}*0x{step:x}'


def parse_new_format(filename, bus_type='apb'):
    """Parse A table and return module metadata plus B-format register records."""
    bus_type = str(bus_type).strip().lower()
    if bus_type not in {'apb', 'regbus'}:
        raise ValueError(f"Unsupported bus_type '{bus_type}', expected apb or regbus")

    wb = openpyxl.load_workbook(filename)
    if not wb.worksheets:
        raise ValueError('A table workbook contains no worksheets')

    ws = wb.worksheets[0]
    header_row, columns = find_table_header(ws)
    variable_ranges = parse_variable_ranges(wb)

    metadata = {}
    for row in ws.iter_rows(max_row=header_row - 1, values_only=True):
        if not row or row[0] is None:
            continue
        key = normalize_header(row[0])
        value = next((item for item in row[1:] if item is not None and str(item).strip() != ''), None)
        if value is not None:
            metadata[key] = value

    if not metadata.get('module'):
        raise ValueError("A table is missing the 'Module' value")

    module_info = {
        'module': str(metadata['module']).strip(),
        'owner': 'czz',
        'size': '4KB',
        'cfg_interface': bus_type,
        'base_addr': metadata.get('base_addr', "32'h0000"),
        'addr_width': parse_integer(metadata.get('id', 12), 'ID'),
        'data_width': 'data_width',
        'tool_version': 'v0p0',
    }

    registers = []
    current_reg = None
    for row_number, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        reg_name_value = cell_value(row, columns, 'reg_name')
        offset_value = cell_value(row, columns, 'offset_addr')
        has_register = reg_name_value is not None and str(reg_name_value).strip() != ''
        has_offset = offset_value is not None and str(offset_value).strip() != ''

        if has_register or has_offset:
            if not (has_register and has_offset):
                raise ValueError(f'Register name and Offset Addr must both be set in A table row {row_number}')
            if current_reg:
                registers.append(current_reg)

            reg_name = str(reg_name_value).strip()
            byte_offset = parse_integer(offset_value, f'Offset Addr of register {reg_name!r}')
            if byte_offset < 0:
                raise ValueError(f'Offset Addr of register {reg_name!r} must be non-negative')
            current_reg = {
                'offset': f'0x{byte_offset:x}',
                'repeat': parse_entry(cell_value(row, columns, 'entry'), variable_ranges, reg_name),
                'reg_name': reg_name,
                'reg_description': cell_value(row, columns, 'reg_description'),
                'fields': [],
            }

        bits = cell_value(row, columns, 'bits')
        field_name = cell_value(row, columns, 'field_name')
        if field_name is not None and str(field_name).strip() != '':
            if current_reg is None:
                raise ValueError(f'Field is defined before a register in A table row {row_number}')
            bit_width = calculate_bit_width(bits)
            field_description = cell_value(row, columns, 'field_description')
            description = field_description if field_description not in (None, '') else current_reg['reg_description']
            current_reg['fields'].append({
                'bits': str(bits).strip(),
                'field': str(field_name).strip(),
                'sw_access': convert_attribute_to_sw_access(cell_value(row, columns, 'attribute')),
                'hw_access': '',
                'default': parse_default_value(cell_value(row, columns, 'default_value'), bit_width),
                'attribute': '',
                'description': description or '',
            })

    if current_reg:
        registers.append(current_reg)
    if not registers:
        raise ValueError('A table contains no registers')
    for reg in registers:
        if not reg['fields']:
            raise ValueError(f"Register {reg['reg_name']!r} has no fields")

    return module_info, registers


def write_b_format(module_info, registers, output_file):
    """Write the B table that is consumed directly by the current gen_reg.py."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'reglist'

    header_font = Font(bold=True)
    header_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center')

    metadata_rows = [
        ('module', module_info['module']),
        ('owner', module_info['owner']),
        ('size', module_info['size']),
        ('cfg_interface', module_info['cfg_interface']),
        ('base_addr', module_info['base_addr']),
        ('addr_width', module_info['addr_width']),
        ('data_width', module_info['data_width']),
        ('tool_version', module_info['tool_version']),
    ]
    for row_number, (key, value) in enumerate(metadata_rows, start=1):
        ws.cell(row=row_number, column=1, value=key)
        ws.cell(row=row_number, column=2, value=value)

    header_row = len(metadata_rows) + 1
    for column_number, header in enumerate(B_HEADERS, start=1):
        cell = ws.cell(row=header_row, column=column_number, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    output_row = header_row + 1
    for reg in registers:
        for field_index, field in enumerate(reg['fields']):
            if field_index == 0:
                ws.cell(row=output_row, column=1, value=reg['offset'])
                ws.cell(row=output_row, column=2, value=reg['repeat'])
                ws.cell(row=output_row, column=3, value=reg['reg_name'])
            ws.cell(row=output_row, column=4, value=field['bits'])
            ws.cell(row=output_row, column=5, value=field['field'])
            ws.cell(row=output_row, column=6, value=field['sw_access'])
            ws.cell(row=output_row, column=7, value=field['hw_access'])
            ws.cell(row=output_row, column=8, value=field['default'])
            ws.cell(row=output_row, column=9, value=field['attribute'])
            ws.cell(row=output_row, column=10, value=field['description'])
            output_row += 1

    for column, width in {'A': 16, 'B': 14, 'C': 28, 'D': 12, 'E': 28, 'F': 14, 'G': 14, 'H': 16, 'I': 14, 'J': 36}.items():
        ws.column_dimensions[column].width = width

    wb.save(output_file)
    print(f'Successfully converted A table to B table: {output_file}')


def main():
    parser = argparse.ArgumentParser(description='Convert A-format register Excel to B format for gen_reg.py')
    parser.add_argument('input', help='Input A-table Excel file')
    parser.add_argument('-o', '--output', help='Output B-table Excel file (default: <input>_b.xlsx)')
    parser.add_argument('--bus_type', choices=['apb', 'regbus'], default='apb',
                        help='B-table cfg_interface (default: apb)')
    args = parser.parse_args()

    if args.output:
        output_file = args.output
        if os.path.isdir(output_file):
            base_name = os.path.splitext(os.path.basename(args.input))[0]
            output_file = os.path.join(output_file, f'{base_name}_b.xlsx')
    else:
        base_name = os.path.splitext(args.input)[0]
        output_file = f'{base_name}_b.xlsx'

    module_info, registers = parse_new_format(args.input, bus_type=args.bus_type)
    write_b_format(module_info, registers, output_file)


if __name__ == '__main__':
    main()


