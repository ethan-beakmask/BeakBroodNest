#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜尋前置詞典管理 CLI

用法：
  list                        列出所有詞條
  add <alias> <canonical>     新增 alias → canonical（可選 --source / --note / --disabled）
  remove <alias>              依 alias 刪除
  toggle <alias>              切換 enabled
  test <query>                測試 normalize 結果
  seed                        植入內建基本詞條（覆盤→復盤）

範例：
  python3 scripts/term_dict_cli.py add 覆盤 復盤 --source variant --note "正異體字"
  python3 scripts/term_dict_cli.py test "今天的覆盤"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope  # noqa: E402
from core.models import TermAlias  # noqa: E402
from core import term_dict  # noqa: E402


def cmd_list(args):
    with session_scope() as s:
        rows = s.query(TermAlias).order_by(TermAlias.canonical, TermAlias.alias).all()
        if not rows:
            print('（無詞條）')
            return
        print(f'{"ID":<4} {"alias":<20} {"canonical":<20} {"source":<10} {"on":<3} note')
        print('-' * 80)
        for r in rows:
            on = 'Y' if r.enabled else 'N'
            print(f'{r.id:<4} {r.alias:<20} {r.canonical:<20} {r.source:<10} {on:<3} {r.note}')


def cmd_add(args):
    with session_scope() as s:
        exists = s.query(TermAlias).filter(TermAlias.alias == args.alias).first()
        if exists:
            print(f'已存在：{args.alias} → {exists.canonical}（id={exists.id}）')
            return
        ta = TermAlias(
            alias=args.alias,
            canonical=args.canonical,
            source=args.source,
            note=args.note or '',
            enabled=not args.disabled,
        )
        s.add(ta)
        s.flush()
        print(f'已新增 id={ta.id}: {ta.alias} → {ta.canonical} (source={ta.source})')
    term_dict.invalidate_cache()


def cmd_remove(args):
    with session_scope() as s:
        r = s.query(TermAlias).filter(TermAlias.alias == args.alias).first()
        if not r:
            print(f'找不到 alias: {args.alias}')
            return
        s.delete(r)
        print(f'已刪除：{args.alias}')
    term_dict.invalidate_cache()


def cmd_toggle(args):
    with session_scope() as s:
        r = s.query(TermAlias).filter(TermAlias.alias == args.alias).first()
        if not r:
            print(f'找不到 alias: {args.alias}')
            return
        r.enabled = not r.enabled
        print(f'{args.alias} → enabled={r.enabled}')
    term_dict.invalidate_cache()


def cmd_test(args):
    out, applied = term_dict.normalize(args.query)
    print(f'input : {args.query!r}')
    print(f'output: {out!r}')
    if applied:
        print('applied:')
        for a, c in applied:
            print(f'  {a} → {c}')
    else:
        print('（未命中任何詞條）')


def cmd_seed(args):
    seeds = [
        ('覆盤', '復盤', 'variant', '正異體字'),
    ]
    added = 0
    with session_scope() as s:
        for alias, canonical, src, note in seeds:
            if s.query(TermAlias).filter(TermAlias.alias == alias).first():
                continue
            s.add(TermAlias(alias=alias, canonical=canonical, source=src, note=note))
            added += 1
    print(f'seed 完成，新增 {added} 筆')
    term_dict.invalidate_cache()


def main():
    init_engine()
    p = argparse.ArgumentParser(description='term_dict CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list')

    p_add = sub.add_parser('add')
    p_add.add_argument('alias')
    p_add.add_argument('canonical')
    p_add.add_argument('--source', default='variant',
                       choices=['variant', 'typo', 'slang', 'personal'])
    p_add.add_argument('--note', default='')
    p_add.add_argument('--disabled', action='store_true')

    p_rm = sub.add_parser('remove')
    p_rm.add_argument('alias')

    p_tg = sub.add_parser('toggle')
    p_tg.add_argument('alias')

    p_test = sub.add_parser('test')
    p_test.add_argument('query')

    sub.add_parser('seed')

    args = p.parse_args()
    {
        'list': cmd_list,
        'add': cmd_add,
        'remove': cmd_remove,
        'toggle': cmd_toggle,
        'test': cmd_test,
        'seed': cmd_seed,
    }[args.cmd](args)


if __name__ == '__main__':
    main()
