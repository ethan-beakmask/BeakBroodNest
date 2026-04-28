# -*- coding: utf-8 -*-
"""修復 content_json 與 atom_entries 表 desync 的卡片。

掃描指定 atom（或 --all 全部），找 content_json 內 structuredEntry node
但 entryId 在 atom_entries 表已不存在的，重建這些 entries
並更新 content_json 的 entryId。

用法：
    python scripts/repair_idcard_desync.py --atom 3670
    python scripts/repair_idcard_desync.py --all     # 全庫修復（先做 dry-run）
    python scripts/repair_idcard_desync.py --atom 3670 --dry-run

只處理 schemaCode='idcard'（其他 schema 的 desync 場景需先評估再開放）。
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from core.db import session_scope
from core.models import (
    KnowledgeAtom,
    AtomEntry,
    EntrySchema,
    EntrySchemaField,
    EntryFieldValue,
)


def _walk_structured_entries(node, parent_path=()):
    """遞迴 yield (parent_list, index_in_list, node_dict)。"""
    if not isinstance(node, dict):
        return
    if node.get('type') == 'structuredEntry':
        # 由 caller 處理（caller 會用 parent + index 替換）
        pass
    children = node.get('content') or []
    for idx, child in enumerate(children):
        if isinstance(child, dict):
            if child.get('type') == 'structuredEntry':
                yield (children, idx, child)
            yield from _walk_structured_entries(child)


def repair_atom(s, atom: KnowledgeAtom, dry_run: bool):
    cj = atom.content_json
    if not isinstance(cj, dict):
        return 0, 0  # nothing to do
    # 找所有 structuredEntry nodes
    targets = list(_walk_structured_entries(cj))
    if not targets:
        return 0, 0

    # 已存在的 entry id 集合
    existing_ids = {
        row.id
        for row in s.query(AtomEntry.id).filter(AtomEntry.atom_id == atom.id).all()
    }
    schemas = {row.code: row for row in s.query(EntrySchema).all()}

    rebuilt = 0
    skipped = 0
    cj_dirty = False

    for parent_list, idx, snode in targets:
        attrs = snode.get('attrs') or {}
        code = attrs.get('schemaCode') or ''
        if code != 'idcard':
            # 暫時只處理 idcard。其他 schema 若有 desync，先呼叫者用 --schema 擴充
            continue
        entry_id = attrs.get('entryId')
        if entry_id and entry_id in existing_ids:
            continue  # 健康
        # 失效 → 重建
        schema = schemas.get(code)
        if not schema:
            skipped += 1
            print(f'  [skip] atom={atom.id} idx={idx}: schema code={code!r} not found')
            continue
        field_values = attrs.get('fieldValues') or {}
        if dry_run:
            print(
                f'  [dry-run] atom={atom.id} idx={idx} would rebuild entry '
                f'(stale id={entry_id}) schemaCode={code} fields={list(field_values.keys())}'
            )
            rebuilt += 1
            continue

        # 真重建
        entry = AtomEntry(
            atom_id=atom.id,
            schema_id=schema.id,
            sort_order=idx,
            raw_text='',
            summary='',
        )
        s.add(entry)
        s.flush()
        # 寫 field_values
        sf_map = {
            f.name: f
            for f in s.query(EntrySchemaField)
            .filter(EntrySchemaField.schema_id == schema.id)
            .all()
        }
        for fname, fval in field_values.items():
            sf = sf_map.get(fname)
            if not sf:
                continue
            fv = EntryFieldValue(
                entry_id=entry.id,
                field_id=sf.id,
                value=str(fval) if fval is not None else None,
            )
            s.add(fv)
        # 更新 content_json 的 entryId
        new_attrs = copy.deepcopy(attrs)
        new_attrs['entryId'] = entry.id
        new_attrs['schemaId'] = schema.id
        new_node = copy.deepcopy(snode)
        new_node['attrs'] = new_attrs
        parent_list[idx] = new_node
        cj_dirty = True
        rebuilt += 1
        print(
            f'  [rebuilt] atom={atom.id} idx={idx} stale_id={entry_id} '
            f'-> new_id={entry.id} schemaCode={code}'
        )

    if cj_dirty and not dry_run:
        # SQLAlchemy JSONB 對 dict in-place 修改不會自動 dirty
        # reassign + flag_modified 雙保險
        atom.content_json = copy.deepcopy(cj)
        flag_modified(atom, 'content_json')

    return rebuilt, skipped


def main():
    parser = argparse.ArgumentParser(description='修復 idcard structuredEntry 的 entries 表 desync')
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--atom', type=int, help='指定 atom id')
    g.add_argument('--all', action='store_true', help='掃全部 atom（小心使用）')
    parser.add_argument('--dry-run', action='store_true', help='只列出，不寫入')
    args = parser.parse_args()

    with session_scope() as s:
        if args.atom:
            atoms = [s.get(KnowledgeAtom, args.atom)]
            if not atoms[0]:
                print(f'atom {args.atom} 不存在')
                return 1
        else:
            atoms = (
                s.query(KnowledgeAtom)
                .filter(KnowledgeAtom.content_json.isnot(None))
                .filter(KnowledgeAtom.is_deleted == False)
                .all()
            )
        total_rebuilt = 0
        total_skipped = 0
        affected_atoms = 0
        for atom in atoms:
            if not atom:
                continue
            r, k = repair_atom(s, atom, args.dry_run)
            if r or k:
                affected_atoms += 1
            total_rebuilt += r
            total_skipped += k
        print('---')
        print(f'掃描 atom 數: {len(atoms)}')
        print(f'有 desync 的 atom: {affected_atoms}')
        print(f'重建 entries: {total_rebuilt}')
        print(f'跳過 entries: {total_skipped}')
        if args.dry_run:
            print('(dry-run，未寫入)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
