"""Generate 32-bit bus windows for wide registers and external RAM entries."""

import re


WIDE_ACCESS = {'RW', 'RO', 'RAM_RW', 'RAM_RO'}
SEPARATOR = '//============================================================================'


def is_wide_register(reg):
    return any(field.bits_size > 32 for field in reg.fields)


def word_count(reg):
    return (reg.fields[0].bits_size + 31) // 32


def word_width(reg, word):
    return min(32, reg.fields[0].bits_size - word * 32)


def address_expr(reg, addr_width, word, index=None):
    address = f"{addr_width}'h{reg.offset}"
    if index is not None:
        address += f" + {addr_width}'h{reg.var_step} * {index}"
    return address + f" + {addr_width}'h4 * {word}"


def section(code, description):
    code.extend([SEPARATOR, '// ' + description, SEPARATOR])


def align_assignments(code, start):
    """Align continuous and clocked assignments within the emitted RTL section."""
    pattern = re.compile(r'^(\s*(?:assign )?)([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])*)\s+(<=|=) (.*)$')
    matches = [(index, pattern.match(line)) for index, line in enumerate(code[start:], start)]
    widths = {}
    for _, match in matches:
        if match:
            key = (match[1], match[3])
            widths[key] = max(widths.get(key, 0), len(match[2]))
    for index, match in matches:
        if match:
            code[index] = f'{match[1]}{match[2]:<{widths[(match[1], match[3])]}} {match[3]} {match[4]}'


def declare(code, kind, width, name, depth=None):
    bit_range = f'[{width - 1:02}:0]' if width > 1 else ''
    array = f'[{depth:02}:0]' if depth is not None else ''
    code.append(f'{kind:<5}{bit_range:<9} {name}{array};')


def default_slice(field, word):
    width = min(32, field.bits_size - word * 32)
    value = str(field.default).strip()
    if value in ("'0", "'1"):
        number = 0 if value == "'0" else (1 << field.bits_size) - 1
    else:
        match = re.fullmatch(r"\d+'([bBdDhHoO])([0-9a-fA-F_]+)", value)
        try:
            number = int(match[2].replace('_', ''), {'b': 2, 'd': 10, 'h': 16, 'o': 8}[match[1].lower()]) if match else int(value, 0)
        except ValueError:
            return f'({value} >> {word * 32})'
    return f"{width}'h{(number >> (word * 32)) & ((1 << width) - 1):x}"


def emit_wide_declarations(code, reg):
    field = reg.fields[0]
    if field.sw_access == 'RW':
        for word in range(word_count(reg)):
            declare(code, 'wire', 1, f'wr_en_{reg.reg_name}_{word}', reg.var_val)
        for word in range(word_count(reg) - 1):
            declare(code, 'reg', 32, f'{field.name}_{word}', reg.var_val)
    else:
        declare(code, 'reg', field.bits_size, f'{field.name}_rd_shadow', reg.var_val)
    if reg.var is not None:
        declare(code, 'reg', 32, f'rd_data_nxt_{reg.reg_name}')


def emit_wide_decode(code, reg, addr_width, name_width=0):
    if reg.fields[0].sw_access != 'RW':
        return
    suffix = '[i]' if reg.var is not None else ''
    indent = '        ' if suffix else ''
    if suffix:
        code.extend(['generate', f'    for(i = 0; i <= {reg.var_val}; i = i + 1) begin: wr_en_gen_{reg.reg_name}'])
    names = [f'wr_en_{reg.reg_name}_{word}{suffix}' for word in range(word_count(reg))]
    for word, name in enumerate(names):
        address = address_expr(reg, addr_width, word, 'i' if suffix else None)
        code.append(f"{indent}assign {name:<{max(name_width, max(map(len, names)))}} = wr_en & (reg_addr[{addr_width-1}:0] == {address} );")
    if suffix:
        code.extend(['    end', 'endgenerate'])


def emit_wide_storage(code, reg, addr_width, write_allowed):
    section_start = len(code)
    field = reg.fields[0]
    width = field.bits_size
    last = word_count(reg) - 1
    high_width = word_width(reg, last)
    suffix = '[i]' if reg.var is not None else ''
    value = field.name + suffix
    shadow = field.name + '_rd_shadow' + suffix
    end_address = int(reg.offset, 16) + last * 4
    section(code, f"{field.name} addr:{addr_width}'h{reg.offset}-{addr_width}'h{end_address:x} type:{field.sw_access} bits:[{field.bits}] default:{field.default}")
    if suffix:
        code.extend(['generate', f'    for(i = 0; i <= {reg.var_val}; i = i + 1) begin: wr_field_{field.name}'])
    start = len(code)
    parity = 'PARITY_GEN' in field.features
    high = f'({value}[{width-1}:{last*32}] & ~msk[{high_width-1}:0]) | (wr_data[{high_width-1}:0] & msk[{high_width-1}:0])'
    lows = ', '.join(f'{field.name}_{word}{suffix}[31:0]' for word in reversed(range(last)))
    if parity:
        code.append(f'assign {field.name}_next{suffix} = {{{high}, {lows}}};')
    code.append('always @(posedge clk or negedge rst_n) begin')
    if field.sw_access == 'RW':
        code.append('    if (!rst_n) begin')
        assignments = [(f'{field.name}_{word}{suffix}[31:0]', default_slice(field, word)) for word in range(last)]
        assignments.append((f'{value}[{width-1}:0]', str(field.default)))
        if parity:
            assignments.append((f'{field.name}_parity{suffix}', f'^({field.default})'))
        align = max(len(lhs) for lhs, _ in assignments)
        code.extend(f'        {lhs:<{align}} <= {rhs};' for lhs, rhs in assignments)
        code.append('    end else begin')
        for word in range(word_count(reg)):
            enable = f'wr_en_{reg.reg_name}_{word}{suffix}'
            if write_allowed:
                enable = f'({enable} & autoreg_write_allowed)'
            if word < last:
                target = f'{field.name}_{word}{suffix}[31:0]'
                code.append(f"        if ({enable} == 1'b1)")
                code.append(f'            {target} <= ({target} & ~msk[31:0]) | (wr_data[31:0] & msk[31:0]);')
            else:
                code.append('        // Commit all words only when the highest address is written')
                code.append(f"        if ({enable} == 1'b1) begin")
                code.append(f'            {value}[{width-1}:{last*32}] <= {high};')
                code.append(f'            {value}[{last*32-1}:0] <= {{{lows}}};')
                if parity:
                    code.append(f'            {field.name}_parity{suffix} <= ^{field.name}_next{suffix};')
                code.append('        end')
        code.append('    end')
    else:
        address = address_expr(reg, addr_width, 0, 'i' if suffix else None)
        code.append('    if (!rst_n)')
        code.append(f"        {shadow} <= {width}'h0;")
        code.append(f"    else if (rd_en && (reg_addr[{addr_width-1}:0] == {address}))")
        code.append(f'        {shadow} <= {value};')
    code.append('end')
    if parity:
        code.extend(['', '// Registered parity covers the committed value, not the write shadows',
                     'always @(posedge clk or negedge rst_n) begin', '    if (!rst_n)',
                     f"        parity_err_{field.name}{suffix} <= 1'b0;", '    else',
                     f'        parity_err_{field.name}{suffix} <= (^{value}) ^ {field.name}_parity{suffix};', 'end'])
    if suffix:
        code[start:] = ['        ' + line if line else '' for line in code[start:]]
        code.extend(['    end', 'endgenerate'])
    code.append('')
    align_assignments(code, section_start)


def read_word(reg, word, index=None, pack_array=False):
    field = reg.fields[0]
    suffix = f'[{index}]' if index is not None else ''
    source = field.name
    if field.sw_access == 'RO' and word > 0:
        source += '_rd_shadow'
    source += suffix
    if index is not None and pack_array and not (field.sw_access == 'RO' and word > 0):
        return f'({source} >> {word * 32})'
    return f'{source}[{word*32+word_width(reg, word)-1}:{word*32}]'


def emit_wide_read_cases(code, reg, addr_width):
    for word in range(word_count(reg)):
        address = int(reg.offset, 16) + word * 4
        code.append(f"    {addr_width}'h{address:x}: begin")
        code.append(f'        rd_data_nxt[{word_width(reg, word)-1}:0] = {read_word(reg, word)};')
        code.append('    end')


def emit_wide_array_read(code, reg, addr_width, pack_array):
    section(code, f'rd_data_nxt_{reg.reg_name}')
    code.extend(['always @(*) begin', f"    rd_data_nxt_{reg.reg_name}[31:0] = 32'h0;",
                 f'    for(j = 0; j <= {reg.var_val}; j = j + 1) begin:rdata_loop_{reg.reg_name}'])
    for word in range(word_count(reg)):
        code.append(f'        if (reg_addr[{addr_width-1}:0] == {address_expr(reg, addr_width, word, "j")}) begin')
        code.append(f'            rd_data_nxt_{reg.reg_name}[{word_width(reg, word)-1}:0] = {read_word(reg, word, "j", pack_array)};')
        code.append('        end')
    code.extend(['    end', 'end', ''])


def emit_wide_ram_declarations(code, reg, addr_width, pending):
    field = reg.fields[0]
    name = field.name
    entry_width = max(1, reg.var_val.bit_length())
    index_width = max(1, (word_count(reg)-1).bit_length())
    declare(code, 'wire', 1, name + '_sel')
    for word in range(word_count(reg)):
        declare(code, 'wire', 1, f'{name}_sel_{word}')
    declare(code, 'wire', entry_width, name + '_entry')
    declare(code, 'wire', index_width, name + '_word')
    declare(code, 'wire', 1, name + '_rd_start')
    declare(code, 'reg', field.bits_size, name + '_rd_shadow')
    declare(code, 'reg', entry_width, name + '_rd_entry')
    declare(code, 'reg', 1, name + '_rd_valid')
    if not pending:
        for suffix, width in [('rd_first_d', 1), ('sel_d', 1), ('rd_word_d', index_width),
                              ('rd_entry_d', entry_width), ('rd_request_entry', entry_width)]:
            declare(code, 'reg', width, name + '_' + suffix)
    declare(code, 'reg', 32, name + '_rdata_final')
    if field.sw_access == 'RAM_RW':
        declare(code, 'reg', 1, name + '_wr_active')
        declare(code, 'reg', entry_width, name + '_wr_entry')
        declare(code, 'wire', 1, name + '_wr_commit')
        for word in range(word_count(reg)-1):
            declare(code, 'reg', 32, f'{name}_{word}')
            declare(code, 'reg', 32, f'{name}_wmask_{word}')


def emit_wide_ram(code, reg, addr_width, pending, write_allowed):
    section_start = len(code)
    field = reg.fields[0]
    name = field.name
    width = field.bits_size
    count = word_count(reg)
    last = count - 1
    high_width = word_width(reg, last)
    step = int(reg.var_step, 16)
    entry_width = max(1, reg.var_val.bit_length())
    index_width = max(1, last.bit_length())
    section(code, f"{name} addr:{addr_width}'h{reg.offset} type:{field.sw_access} bits:[{field.bits}] depth:{reg.var_val + 1}")
    code.append('// Decode entry and word separately; unused stride padding is not selected')
    for word in range(count):
        first = int(reg.offset, 16) + word * 4
        end = first + reg.var_val * step
        code.append(f"assign {name}_sel_{word} = (reg_addr >= {addr_width}'h{first:x}) && (reg_addr <= {addr_width}'h{end:x}) && (((reg_addr - {addr_width}'h{reg.offset}) & {addr_width}'h{step-1:x}) == {addr_width}'h{word*4:x});")
    code.append(f'assign {name}_sel = ' + ' | '.join(f'{name}_sel_{word}' for word in range(count)) + ';')
    code.append(f"assign {name}_entry = (reg_addr - {addr_width}'h{reg.offset}) >> {step.bit_length()-1};")
    code.append(f"assign {name}_word = ((reg_addr - {addr_width}'h{reg.offset}) & {addr_width}'h{step-1:x}) >> 2;")
    code.append(f'assign {name}_rd_start = {name}_sel_0 & {"table_rd_en" if pending else "rd_en"};')
    code.append(f'assign {name}_addr = {name}_entry;')
    if field.sw_access == 'RAM_RW':
        wr_enable = '(wr_en & autoreg_write_allowed)' if write_allowed else 'wr_en'
        code.append(f'assign {name}_wr_commit = {name}_sel_{last} & {wr_enable} & {name}_wr_active & ({name}_entry == {name}_wr_entry);')
        code.append(f'assign {name}_en = {name}_rd_start | {name}_wr_commit;')
        code.append(f'assign {name}_we = {name}_wr_commit;')
        data = [f'wr_data[{high_width-1}:0]'] + [f'{name}_{word}[31:0]' for word in reversed(range(last))]
        masks = [f'msk[{high_width-1}:0]'] + [f'{name}_wmask_{word}[31:0]' for word in reversed(range(last))]
        code.append(f'assign {name}_wdata = {{{", ".join(data)}}};')
        code.append(f'assign {name}_wmask = {{{", ".join(masks)}}};')
        code.append('')
        section(code, f'{name} write shadows and per-bit masks')
        code.extend(['always @(posedge clk or negedge rst_n) begin', '    if (!rst_n) begin',
                     f"        {name}_wr_active <= 1'b0;", f"        {name}_wr_entry <= {entry_width}'h0;"])
        for word in range(last):
            code.extend([f"        {name}_{word}[31:0] <= 32'h0;", f"        {name}_wmask_{word}[31:0] <= 32'h0;"])
        code.append('    end else begin')
        code.append('        // The lowest address starts a new entry and clears previous masks')
        code.append(f'        if ({name}_sel_0 & {wr_enable}) begin')
        code.extend([f"            {name}_wr_active <= 1'b1;", f'            {name}_wr_entry <= {name}_entry;',
                     f'            {name}_0[31:0] <= wr_data[31:0] & msk[31:0];', f'            {name}_wmask_0[31:0] <= msk[31:0];'])
        for word in range(1, last):
            code.append(f"            {name}_wmask_{word}[31:0] <= 32'h0;")
        code.append('        end')
        for word in range(1, last):
            code.append(f'        if ({name}_sel_{word} & {wr_enable} & {name}_wr_active & ({name}_entry == {name}_wr_entry)) begin')
            code.append(f'            {name}_{word}[31:0] <= ({name}_{word}[31:0] & ~msk[31:0]) | (wr_data[31:0] & msk[31:0]);')
            code.append(f'            {name}_wmask_{word}[31:0] <= {name}_wmask_{word}[31:0] | msk[31:0];')
            code.append('        end')
        complete = f'{name}_wr_commit' + (f' & {name}_ready' if pending else '')
        code.extend([f'        if ({complete})', f"            {name}_wr_active <= 1'b0;", '    end', 'end', ''])
    else:
        code.extend([f'assign {name}_en = {name}_rd_start;', ''])

    section(code, f'{name} read snapshot (refresh only on the lowest address)')
    if not pending:
        code.extend(['always @(posedge clk or negedge rst_n) begin', '    if (!rst_n) begin',
                     f"        {name}_rd_first_d <= 1'b0;", f"        {name}_sel_d <= 1'b0;",
                     f"        {name}_rd_word_d <= {index_width}'h0;", f"        {name}_rd_entry_d <= {entry_width}'h0;",
                     f"        {name}_rd_request_entry <= {entry_width}'h0;", '    end else begin',
                     f'        {name}_rd_first_d <= {name}_rd_start;', f'        {name}_sel_d <= rd_en & {name}_sel;',
                     f'        if (rd_en & {name}_sel) begin', f'            {name}_rd_word_d <= {name}_word;',
                     f'            {name}_rd_entry_d <= {name}_entry;', '        end',
                     f'        if ({name}_rd_start)', f'            {name}_rd_request_entry <= {name}_entry;', '    end', 'end', ''])
    capture = f'{name}_rd_start & penable & {name}_ready' if pending else f'{name}_rd_first_d'
    entry = f'{name}_entry' if pending else f'{name}_rd_request_entry'
    code.extend(['always @(posedge clk or negedge rst_n) begin', '    if (!rst_n) begin',
                 f"        {name}_rd_shadow <= {width}'h0;", f"        {name}_rd_entry <= {entry_width}'h0;",
                 f"        {name}_rd_valid <= 1'b0;", f'    end else if ({capture}) begin',
                 f'        {name}_rd_shadow <= {name}_rdata;', f'        {name}_rd_entry <= {entry};',
                 f"        {name}_rd_valid <= 1'b1;", '    end', 'end', ''])
    section(code, f'{name} read word selection')
    selected = f'{name}_sel & table_rd_en' if pending else f'{name}_sel_d'
    word_signal = f'{name}_word' if pending else f'{name}_rd_word_d'
    read_entry = f'{name}_entry' if pending else f'{name}_rd_entry_d'
    code.extend(['always @(*) begin', f"    {name}_rdata_final[31:0] = 32'h0;", f'    if ({selected}) begin',
                 f'        case ({word_signal})'])
    for word in range(count):
        bits = word_width(reg, word)
        code.append(f"        {index_width}'d{word}: begin")
        if word == 0:
            code.append(f'            {name}_rdata_final[31:0] = {name}_rdata[31:0];')
        else:
            code.append(f'            if ({name}_rd_valid && ({read_entry} == {name}_rd_entry))')
            code.append(f'                {name}_rdata_final[{bits-1}:0] = {name}_rd_shadow[{word*32+bits-1}:{word*32}];')
        code.append('        end')
    code.extend(['        default:', f"            {name}_rdata_final[31:0] = 32'h0;", '        endcase', '    end', 'end', ''])
    align_assignments(code, section_start)
