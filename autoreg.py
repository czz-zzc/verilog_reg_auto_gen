#!/usr/bin/env python3
"""Convert an A-format register table and generate its Verilog implementation."""

import argparse
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

from convert_excel import parse_new_format, write_b_format
from gen_reg import generate_verilog, parse_excel


def intermediate_excel_path(input_file, output_file):
    """Put the intermediate B table beside the requested Verilog output as mid.xlsx."""
    if output_file:
        output_dir = output_file if os.path.isdir(output_file) else os.path.dirname(output_file)
        if output_dir:
            return os.path.join(output_dir, 'mid.xlsx')
    return os.path.join(os.path.dirname(os.path.abspath(input_file)), 'mid.xlsx')


def resolve_verilog_path(output_file, module_name):
    if not output_file:
        return f'{module_name}.v'
    if os.path.isdir(output_file) or (not os.path.exists(output_file) and not output_file.endswith('.v')):
        return os.path.join(output_file, f'{module_name}.v')
    return output_file

def check_verilog(verilog_file, module_name):
    """Compile the generated module when Icarus Verilog is available."""
    iverilog = shutil.which('iverilog')
    if not iverilog:
        print('\033[33mWarning: iverilog was not found; skipping Verilog compilation check.\033[0m')
        return

    result = subprocess.run(
        [iverilog, '-g2012', '-s', module_name, '-tnull', verilog_file],
        capture_output=True,
        text=True,
        errors='replace',
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise ValueError(f'Icarus Verilog compilation failed for {verilog_file}:\n{details}')
    print(f'Icarus Verilog check passed: {verilog_file}')


def main():
    parser = argparse.ArgumentParser(
        description='Convert an A-format register Excel table and generate Verilog in one command.'
    )
    parser.add_argument('input', help='Input A-format Excel file')
    parser.add_argument('-o', '--output', help='Output Verilog file or directory')
    parser.add_argument('--bus_type', choices=['apb', 'regbus'], default='apb',
                        help='Generated configuration interface (default: apb)')
    parser.add_argument('-p', '--parallel', action='store_true',
                        help='Enable parallel implementation for ordinary arrays')
    parser.add_argument('--keep_excel', action='store_true',
                        help='Keep the intermediate B-format Excel table')
    args = parser.parse_args()

    intermediate_file = None
    try:
        module_info, registers = parse_new_format(args.input, bus_type=args.bus_type)
        output_file = resolve_verilog_path(args.output, module_info['module'])
        intermediate_file = intermediate_excel_path(args.input, output_file)
        intermediate_dir = os.path.dirname(intermediate_file)
        if intermediate_dir:
            os.makedirs(intermediate_dir, exist_ok=True)

        write_b_format(module_info, registers, intermediate_file)
        b_module_info, b_registers = parse_excel(
            intermediate_file,
            parallel=args.parallel,
            module_name_override=os.path.splitext(os.path.basename(output_file))[0],
        )

        verilog_file = resolve_verilog_path(args.output, b_module_info['module'])
        verilog_dir = os.path.dirname(verilog_file)
        if verilog_dir:
            os.makedirs(verilog_dir, exist_ok=True)
        verilog_code = generate_verilog(b_module_info, b_registers, os.path.basename(verilog_file).split('.')[0])
        with open(verilog_file, 'w', encoding='utf-8') as file:
            file.write(verilog_code)
        check_verilog(verilog_file, b_module_info['module'])
        print(f'Successfully generated {verilog_file}')
    except (ValueError, OSError) as error:
        print(f'\033[31mError: {error}\033[0m', file=sys.stderr)
        if intermediate_file and os.path.exists(intermediate_file):
            print(f'Intermediate B table kept for diagnosis: {intermediate_file}', file=sys.stderr)
        sys.exit(1)

    if args.keep_excel:
        print(f'Intermediate B table kept: {intermediate_file}')
    elif intermediate_file and os.path.exists(intermediate_file):
        os.remove(intermediate_file)


if __name__ == '__main__':
    main()





