"""Advance the register-table version after successful RTL generation."""

import os
import re
import sys
import tempfile

import openpyxl

from convert_excel import find_register_sheet, parse_default_value


def version_value(value):
    """Require a known 8-bit value before incrementing the table version."""
    literal = parse_default_value(value, 8)
    match = re.fullmatch(r"8'([bBdDhHoO])([0-9a-fA-F_]+)", literal)
    if match:
        base = {'b': 2, 'd': 10, 'h': 16, 'o': 8}[match[1].lower()]
        try:
            number = int(match[2].replace('_', ''), base)
        except ValueError:
            number = -1
        if 0 <= number <= 255:
            return number
    raise ValueError('reg_version default must be a known 8-bit value (0..255)')


def prepare_version_update(registers):
    """Update the parsed default; defer changes to the source Excel until success."""
    fields = {field['field']: field for reg in registers for field in reg['fields']}
    if 'reg_version' in fields:
        previous = version_value(fields['reg_version']['default'])
    missing = {'rtl_version', 'reg_version'} - fields.keys()
    if missing:
        print('\033[31mWarning: missing RO version field(s): ' + ', '.join(sorted(missing))
              + '; reg_version will not be incremented.\033[0m', file=sys.stderr)
        return None
    field = fields['reg_version']
    current = (previous + 1) & 0xff
    field['default'] = f"8'h{current:02x}"
    return field['source_row'], previous, current


def save_version_update(filename, update):
    """Preserve the original workbook and replace it only after a complete save."""
    row, previous, current = update
    filename = os.path.abspath(filename)
    suffix = os.path.splitext(filename)[1]
    wb = openpyxl.load_workbook(filename, keep_vba=suffix.lower() == '.xlsm')
    temporary = None
    try:
        ws, _, columns = find_register_sheet(wb)
        if 'default_value' not in columns:
            raise ValueError('Version fields require a Default Value column')
        if str(ws.cell(row, columns['field_name'] + 1).value).strip() != 'reg_version':
            raise ValueError('reg_version source row changed during generation; Excel was not updated')
        cell = ws.cell(row, columns['default_value'] + 1)
        if version_value(cell.value) != previous:
            raise ValueError('reg_version default changed during generation; Excel was not updated')
        cell.value = f"8'h{current:02x}"
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(filename), suffix=suffix, delete=False) as file:
            temporary = file.name
        wb.save(temporary)
        wb.close()
        os.replace(temporary, filename)
    finally:
        wb.close()
        if temporary and os.path.exists(temporary):
            os.remove(temporary)
    print(f'reg_version updated: {previous} -> {current} ({filename})')
