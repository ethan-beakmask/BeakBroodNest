# -*- coding: utf-8 -*-
"""MCP 參數字串形式解析器。"""
import re


FIELD_VALUES_FORMAT = '多行「欄位name=值」，續行直接換行接在上一個欄位值後；例：status=進行中'
RELATIONS_FORMAT = '多行「from_ref -> to_ref : relation_type [: label]」；例：BBN-137 -> BBN-138 : supports : 補充說明'
FIELDS_FORMAT = '多行「name|label|field_type[|required[|options]]」；例：status|狀態|select|required|待辦,完成'
EXTRA_REPLACEMENTS_FORMAT = '多行「原文=>佔位前綴」；例：內部主機=>INTERNAL_HOST'

FIELD_NAME_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)[ \t]*=')
REF_RE = re.compile(r'^([A-Za-z][A-Za-z0-9]{1,7}-\d+|\d+)$')
RELATION_TYPE_RE = re.compile(r'^[a-z_]+$')
SCHEMA_FIELD_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

FIELD_TYPES = {
    'text', 'number', 'date', 'select', 'multiselect', 'checkbox', 'url', 'relation',
}
FALSE_VALUES = {'', 'false', '0', 'no', 'optional'}
TRUE_VALUES = {'required', 'true', '1', 'yes'}


class ParamFormatError(ValueError):
    """參數字串格式錯誤，保留原始行號與格式說明。"""

    def __init__(self, line_no: int, line_text: str, fmt: str, reason: str = ''):
        self.line_no = line_no
        self.line_text = line_text
        self.fmt = fmt
        self.reason = reason
        message = f'第 {line_no} 行格式錯誤: {line_text}'
        if reason:
            message += f'（{reason}）'
        super().__init__(message)


def param_format_error_payload(exc: ParamFormatError) -> dict:
    """將 ParamFormatError 轉成工具回傳用 JSON payload。"""
    return {
        'error': str(exc),
        'format': exc.fmt,
    }


def _unexpected_type(value, fmt: str) -> ParamFormatError:
    return ParamFormatError(1, repr(value), fmt, '型別不合法')


def parse_field_values(value) -> dict[str, str]:
    """解析 note_store field_values 的字串形式。"""
    if value is None:
        return {}
    if not isinstance(value, str):
        raise _unexpected_type(value, FIELD_VALUES_FORMAT)
    if not value.strip():
        return {}

    result = {}
    current_name = None
    current_lines = []

    for line_no, line in enumerate(value.splitlines(), start=1):
        match = FIELD_NAME_RE.match(line)
        if match:
            if current_name is not None:
                result[current_name] = '\n'.join(current_lines).strip()
            name = match.group(1)
            if name in result:
                raise ParamFormatError(line_no, line, FIELD_VALUES_FORMAT, '欄位重複')
            current_name = name
            current_lines = [line[line.find('=') + 1:]]
            continue

        if current_name is None:
            if not line.strip():
                continue
            raise ParamFormatError(line_no, line, FIELD_VALUES_FORMAT)
        current_lines.append(line)

    if current_name is not None:
        result[current_name] = '\n'.join(current_lines).strip()

    return result


def parse_relations(value) -> list[dict]:
    """解析 note_relate_batch relations 的字串形式。"""
    if value is None:
        return []
    if not isinstance(value, str):
        raise _unexpected_type(value, RELATIONS_FORMAT)
    if not value.strip():
        return []

    relations = []
    for line_no, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        if '->' not in line:
            raise ParamFormatError(line_no, line, RELATIONS_FORMAT, '缺少 ->')
        from_part, right = line.split('->', 1)
        from_ref = from_part.strip()
        pieces = [p.strip() for p in right.split(':', 2)]
        if len(pieces) < 2 or not pieces[1]:
            raise ParamFormatError(line_no, line, RELATIONS_FORMAT, '缺少 relation_type')
        to_ref = pieces[0]
        relation_type = pieces[1]
        label = pieces[2] if len(pieces) > 2 else ''
        if not REF_RE.match(from_ref):
            raise ParamFormatError(line_no, line, RELATIONS_FORMAT, 'from_ref 不合法')
        if not REF_RE.match(to_ref):
            raise ParamFormatError(line_no, line, RELATIONS_FORMAT, 'to_ref 不合法')
        if not RELATION_TYPE_RE.match(relation_type):
            raise ParamFormatError(line_no, line, RELATIONS_FORMAT, 'relation_type 不合法')
        relations.append({
            'from_ref': from_ref,
            'to_ref': to_ref,
            'relation_type': relation_type,
            'label': label,
        })
    return relations


def parse_fields(value):
    """解析 schema_create fields 的字串形式。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _unexpected_type(value, FIELDS_FORMAT)
    if not value.strip():
        return []

    fields = []
    seen = set()
    sort_order = 0
    for line_no, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split('|', 4)]
        if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
            raise ParamFormatError(line_no, line, FIELDS_FORMAT)
        name, label, field_type = parts[:3]
        required_text = parts[3] if len(parts) > 3 else ''
        options = parts[4] if len(parts) > 4 else ''
        if not SCHEMA_FIELD_NAME_RE.match(name):
            raise ParamFormatError(line_no, line, FIELDS_FORMAT, 'name 不合法')
        if name in seen:
            raise ParamFormatError(line_no, line, FIELDS_FORMAT, 'name 重複')
        if field_type not in FIELD_TYPES:
            raise ParamFormatError(line_no, line, FIELDS_FORMAT, 'field_type 不合法')
        required_key = required_text.lower()
        if required_key in FALSE_VALUES:
            required = False
        elif required_key in TRUE_VALUES:
            required = True
        else:
            raise ParamFormatError(line_no, line, FIELDS_FORMAT, 'required 不合法')
        seen.add(name)
        fields.append({
            'name': name,
            'label': label,
            'field_type': field_type,
            'options': options,
            'required': required,
            'sort_order': sort_order,
        })
        sort_order += 1
    return fields


def parse_extra_replacements(value) -> dict[str, str]:
    """解析 note_sanitize extra_replacements 的字串形式。"""
    if value is None:
        return {}
    if not isinstance(value, str):
        raise _unexpected_type(value, EXTRA_REPLACEMENTS_FORMAT)
    if not value.strip():
        return {}

    replacements = {}
    for line_no, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            continue
        if '=>' not in line:
            raise ParamFormatError(line_no, line, EXTRA_REPLACEMENTS_FORMAT, '缺少 =>')
        original, prefix = [p.strip() for p in line.split('=>', 1)]
        if not original or not prefix:
            raise ParamFormatError(line_no, line, EXTRA_REPLACEMENTS_FORMAT)
        if original in replacements:
            raise ParamFormatError(line_no, line, EXTRA_REPLACEMENTS_FORMAT, '原文重複')
        replacements[original] = prefix
    return replacements
