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
from register_features import (SUPPORTED_ACCESS, info_feature_text, normalize_access, parse_info_features,
                               parse_interrupt_group, validate_feature_specs,
                               validate_interrupt_specs)
from openpyxl.styles import Alignment, Font, PatternFill


B_HEADERS = [
    'offset', 'repeat', 'reg_name', 'bits', 'field',
    'sw_access', 'hw_access', 'default', 'attribute', 'description', 'info',
]


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
    """Map a supported A-table attribute to a B-table software-access value."""
    if attribute is None or str(attribute).strip() == '':
        return 'RW'

    access = normalize_access(attribute)
    return access if access in SUPPORTED_ACCESS else None


def warn_skipped_register(reg_name, field_name, attribute, row_number):
    """Report an unsupported field access and the affected skipped register."""
    print(
        f"\033[33mWarning: Skipping register {reg_name!r}: field {field_name!r} "
        f"uses unsupported Attribute {attribute!r} at A table row {row_number}.\033[0m"
    )


def find_table_header(ws):
    """Locate the A-table header and return normalized header-to-column indexes."""
    for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
        headers = [normalize_header(value) for value in row]
        if 'reg_name' in headers and 'offset_addr' in headers:
            return row_number, {header: index for index, header in enumerate(headers) if header}
    raise ValueError("A table header containing 'Reg Name' and 'Offset Addr' was not found")


def find_register_sheet(wb):
    """Find the A-table worksheet by its required Module metadata label."""
    matches = []
    for ws in wb.worksheets:
        has_module_label = any(
            row and normalize_header(row[0]) == 'module'
            for row in ws.iter_rows(values_only=True)
        )
        if not has_module_label:
            continue

        try:
            header_row, columns = find_table_header(ws)
        except ValueError as error:
            raise ValueError(
                f"Worksheet {ws.title!r} contains 'Module' but has no valid A-table header"
            ) from error
        matches.append((ws, header_row, columns))

    if not matches:
        raise ValueError("No worksheet containing the required 'Module' label was found")
    if len(matches) > 1:
        names = ', '.join(ws.title for ws, _, _ in matches)
        raise ValueError(f"Multiple worksheets containing 'Module' were found: {names}")
    return matches[0]


def cell_value(row, columns, name):
    index = columns.get(name)
    return row[index] if index is not None and index < len(row) else None


def parse_variable_ranges(wb, register_ws):
    """Read variable ranges from any non-register worksheet in an A table workbook."""
    ranges = {}
    name_aliases = {'name', 'variable_name', '\u53d8\u91cf\u540d\u79f0'}
    range_aliases = {'range', 'variable_range', '\u53d8\u91cf\u8303\u56f4'}

    for ws in wb.worksheets:
        if ws is register_ws:
            continue

        header_row = None
        columns = {}
        for row_number, row in enumerate(ws.iter_rows(values_only=True), start=1):
            headers = [normalize_header(value) for value in row]
            name_index = next((index for index, header in enumerate(headers) if header in name_aliases), None)
            range_index = next((index for index, header in enumerate(headers) if header in range_aliases), None)
            if name_index is not None and range_index is not None:
                header_row = row_number
                columns = {'name': name_index, 'range': range_index}
                break

        if header_row is None:
            continue

        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            name = cell_value(row, columns, 'name')
            range_value = cell_value(row, columns, 'range')
            if name is None or str(name).strip() == '':
                continue
            if range_value is None or str(range_value).strip() == '':
                raise ValueError(f"Variable {name!r} in sheet {ws.title!r} has no range")

            match = re.fullmatch(r'\s*(\d+)\s*(?:~|-)\s*(\d+)\s*', str(range_value))
            if not match:
                raise ValueError(
                    f"Invalid range {range_value!r} for variable {name!r} in sheet {ws.title!r}; expected 0-N"
                )
            lower, upper = map(int, match.groups())
            if lower != 0 or upper < lower:
                raise ValueError(f"Variable {name!r} range must start at 0, got {range_value!r}")

            variable_name = str(name).strip()
            if variable_name in ranges:
                raise ValueError(f"Variable {variable_name!r} is defined more than once")
            ranges[variable_name] = upper

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

    ws, header_row, columns = find_register_sheet(wb)
    variable_ranges = parse_variable_ranges(wb, ws)

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
        'size': '64KB',
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
            if current_reg and not current_reg['skip']:
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
                'skip': False,
                'filtered_fields': False,
            }

        bits = cell_value(row, columns, 'bits')
        field_name = cell_value(row, columns, 'field_name')
        if field_name is not None and str(field_name).strip() != '':
            info = cell_value(row, columns, 'info')
            if 'NO_RTL_GEN' in info_feature_text(info).upper():
                if current_reg is not None:
                    current_reg['filtered_fields'] = True
                continue
            if current_reg is None:
                raise ValueError(f'Field is defined before a register in A table row {row_number}')

            attribute = cell_value(row, columns, 'attribute')
            sw_access = convert_attribute_to_sw_access(attribute)
            if sw_access is None:
                if parse_info_features(info) or parse_interrupt_group(info) is not None:
                    raise ValueError(f'Unsupported Attribute {attribute!r} on feature-marked field {field_name!r}')
                if not current_reg['skip']:
                    warn_skipped_register(
                        current_reg['reg_name'], str(field_name).strip(), attribute, row_number
                    )
                    current_reg['skip'] = True
                    current_reg['fields'].clear()
                continue
            if current_reg['skip']:
                continue

            bit_width = calculate_bit_width(bits)
            field_description = cell_value(row, columns, 'field_description')
            description = field_description if field_description not in (None, '') else current_reg['reg_description']
            current_reg['fields'].append({
                'bits': str(bits).strip(),
                'field': str(field_name).strip(),
                'sw_access': sw_access,
                'hw_access': '',
                'default': None if sw_access == 'RCI' else parse_default_value(cell_value(row, columns, 'default_value'), bit_width),
                'attribute': '',
                'description': description or '',
                'info': str(info).strip() if info is not None else '',
            })

    if current_reg and not current_reg['skip']:
        registers.append(current_reg)
    registers = [reg for reg in registers if reg['fields'] or not reg['filtered_fields']]
    for reg in registers:
        if not reg['fields']:
            raise ValueError(f"Register {reg['reg_name']!r} has no fields")

    validate_feature_specs(
        (field['field'], field['sw_access'], calculate_bit_width(field['bits']),
         reg['repeat'] is not None, parse_info_features(field.get('info')))
        for reg in registers for field in reg['fields']
    )
    validate_interrupt_specs(
        (parse_interrupt_group(field.get('info')), None, field['field'], field['sw_access'],
         calculate_bit_width(field['bits']),
         int(reg['repeat'].split('*')[0]) if reg['repeat'] is not None else None,
         parse_info_features(field.get('info')))
        for reg in registers for field in reg['fields']
    )
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
            ws.cell(row=output_row, column=11, value=field.get('info', ''))
            output_row += 1

    for column, width in {'A': 16, 'B': 14, 'C': 28, 'D': 12, 'E': 28, 'F': 14, 'G': 14, 'H': 16, 'I': 14, 'J': 36, 'K': 32}.items():
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


