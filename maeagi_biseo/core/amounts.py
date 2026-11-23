"""Exact Korean large-number formatting for human-readable meso amounts."""


def format_meso(value, signed=False):
    if type(value) is not int:
        raise ValueError('Expected integer meso')
    sign = '-' if value < 0 else '+' if signed and value > 0 else ''
    remainder = abs(value)
    groups = []
    for divisor, unit in ((10**16, '경'), (10**12, '조'), (10**8, '억'), (10**4, '만'), (1, '')):
        number, remainder = divmod(remainder, divisor)
        if number:
            groups.append(str(number) + unit)
    return sign + (' '.join(groups) if groups else '0')


def format_fragments(value, signed=False):
    if value is None:
        return '미기록'
    return (f'{value:+}' if signed else str(value)) + '개'


def with_amount_text(value):
    if isinstance(value, list):
        return [with_amount_text(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: with_amount_text(item) for key, item in value.items()}
    for key in ('meso', 'start_meso', 'end_meso', 'meso_change', 'meso_per_hour'):
        if type(value.get(key)) is int:
            result[key + '_text'] = format_meso(value[key], signed=key == 'meso_change') + ' 메소'
    return result
