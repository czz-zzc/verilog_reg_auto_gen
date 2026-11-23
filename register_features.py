"""Shared validation for field-level RTL generation features."""

import re


SOFTWARE_WRITABLE = {'RW', 'WO', 'W1P', 'EVENT', 'ONE_SHOT', 'RWW', 'CNT', 'RCNT'}
SUPPORTED_ACCESS = SOFTWARE_WRITABLE | {'RO', 'RC', 'RCI', 'RAM_RW', 'RAM_RO'}
VERSION_FIELD_BITS = {'rtl_version': '31:8', 'reg_version': '7:0'}
INFO_SEPARATORS = r';,；，\s'
INFO_BOUNDARY = rf'(?<![^{INFO_SEPARATORS}])'
INFO_GROUP = rf'[^{INFO_SEPARATORS}]*'
INT_MARKER = re.compile(INFO_BOUNDARY + r'int:', re.IGNORECASE)
COMB_MARKER = re.compile(rf'{INFO_BOUNDARY}comb:({INFO_GROUP})', re.IGNORECASE)
INFO_QUOTE_OR_INT = re.compile(
    r'''(?P<quoted>(?<![A-Za-z0-9_])(?:"[^"]*"|'[^']*'|“[^”]*”|‘[^’]*’))'''
    + rf'|{INT_MARKER.pattern}(?P<interrupt>{INFO_GROUP})', re.IGNORECASE,
)


def normalize_access(value):
    """Use the same access aliases in both Excel formats."""
    access = str(value or '').strip().upper()
    access = {'R/W': 'RW', 'R/O': 'RO', 'R/C': 'RC', 'R/W/W': 'RWW',
              'PULSE': 'W1P', 'W1C': 'EVENT'}.get(access, access)
    if re.fullmatch(r'ONE[-_\s]SHOT', access):
        return 'ONE_SHOT'
    return access


def validate_version_specs(specs):
    """Validate reserved version fields: (name, access, bits, is_array)."""
    seen = set()
    for name, access, bits, is_array in specs:
        if name not in VERSION_FIELD_BITS:
            continue
        if name in seen:
            raise ValueError(f'Duplicate version field {name!r}')
        seen.add(name)
        if access != 'RO' or re.sub(r'\s+', '', str(bits)) != VERSION_FIELD_BITS[name] or is_array:
            raise ValueError(f"Version field {name!r} must be a scalar RO field with bits [{VERSION_FIELD_BITS[name]}]")


def split_info(value):
    """Separate feature text from opaque interrupt names, honoring paired quotes."""
    text = str(value or '')
    features = []
    groups = []
    end = 0
    for item in INFO_QUOTE_OR_INT.finditer(text):
        features.append(text[end:item.start()])
        end = item.end()
        if item.lastgroup == 'interrupt':
            groups.append(item['interrupt'])
            continue

        quoted = item['quoted'][1:-1]
        marker = INT_MARKER.search(quoted)
        if marker is None:
            features.append(quoted)
        else:
            features.append(quoted[:marker.start()])
            groups.append(quoted[marker.end():].strip())
    features.append(text[end:])
    return ' '.join(features), groups


def parse_interrupt_group(value):
    """Read one interrupt group; quote names containing separators."""
    _, groups = split_info(value)
    if not groups:
        return None
    if len(groups) != 1:
        raise ValueError('Info allows one int:<group> marker per field')
    if not groups[0]:
        raise ValueError('Interrupt marker int: requires a non-empty group name')
    return groups[0]


def validate_interrupt_specs(specs):
    """Validate (group, index, name, access, width, array_depth, features) tuples."""
    groups = {}
    for group, index, name, access, width, depth, features in specs:
        if group is None:
            continue
        if access not in {'EVENT', 'W1P', 'RW'}:
            raise ValueError(f'Interrupt group {group!r}: field {name!r} must use EVENT, W1P or RW')
        if 'LOCK_GEN' in features:
            raise ValueError(f'Interrupt group {group!r}: field {name!r} cannot also use LOCK_GEN')
        members = groups.setdefault((group, index), {})
        if access in members:
            raise ValueError(f'Interrupt group {group!r} has duplicate {access} fields')
        members[access] = (name, width, depth)
    for (group, _), members in groups.items():
        missing = {'EVENT', 'W1P', 'RW'} - members.keys()
        if missing:
            raise ValueError(f'Interrupt group {group!r} is missing type(s): ' + ', '.join(sorted(missing)))
        if len({width for _, width, _ in members.values()}) != 1:
            raise ValueError(f'Interrupt group {group!r} fields must have matching bit widths')
        if len({depth for _, _, depth in members.values()}) != 1:
            raise ValueError(f'Interrupt group {group!r} fields must have matching array depths (or all be scalar)')
    return groups


def info_feature_text(value):
    """Exclude the opaque interrupt group name from other feature matching."""
    return split_info(value)[0]


def parse_comb_group(value):
    """Read a named wide-field group from the feature portion of Info."""
    groups = COMB_MARKER.findall(info_feature_text(value))
    if not groups:
        return None
    if len(groups) != 1 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', groups[0]):
        raise ValueError('Info requires one comb:<Verilog identifier> marker per field')
    return groups[0]


def parse_info_features(value):
    """Recognize complete feature tokens without interpreting descriptive text."""
    return frozenset(re.findall(
        r'(?<![A-Z0-9_])(?:LOCK_GEN|PARITY_GEN)(?![A-Z0-9_])',
        info_feature_text(value).upper(),
    ))


def validate_feature_specs(specs):
    """Validate (name, access, width, is_array, features) for one module."""
    locks = []
    for name, access, width, is_array, features in specs:
        if 'LOCK_GEN' in features:
            if access != 'RW' or width != 1 or is_array:
                raise ValueError(f'LOCK_GEN field {name!r} must be a scalar 1-bit RW field')
            locks.append(name)
        if 'PARITY_GEN' in features and access not in {'RW', 'WO'}:
            raise ValueError(f'PARITY_GEN field {name!r} must use RW or WO access')
    if len(locks) > 1:
        raise ValueError('Only one LOCK_GEN field is allowed per register worksheet: '
                         + ', '.join(locks))
