#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 背景 Embedding Worker
掃描 needs_embedding=True 的原子，批次生成向量嵌入。

用法:
  python scripts/embed_worker.py                一次性處理所有待嵌入原子
  python scripts/embed_worker.py --daemon       持續監聽模式（每 30 秒掃描）
  python scripts/embed_worker.py --interval 10  自訂掃描間隔（秒）

搭配 crontab 使用（每分鐘執行一次）:
  * * * * * cd /opt/BeakBroodNest && venv/bin/python scripts/embed_worker.py >> /opt/tmp/BeakBroodNest-embed_worker.log 2>&1
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom, AtomEmbedding
from core import embeddings as embed_service

logger = logging.getLogger('beak_broodnest.embed_worker')

HEARTBEAT_PATH = '/opt/tmp/heartbeat/embed_worker'


def _write_heartbeat():
    """寫入 heartbeat 檔案"""
    try:
        Path(HEARTBEAT_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(HEARTBEAT_PATH).write_text(
            time.strftime('%Y-%m-%d %H:%M:%S')
        )
    except Exception:
        pass


def process_pending():
    """處理所有 needs_embedding=True 的原子，回傳處理數量"""
    with session_scope() as s:
        atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.needs_embedding == True,
                KnowledgeAtom.is_deleted == False,
            )
            .order_by(KnowledgeAtom.id)
            .limit(100)  # 每批最多 100 筆
            .all()
        )

        if not atoms:
            return 0

        # 批次 encode 效率更高
        model = embed_service._get_model()
        texts = []
        valid_atoms = []
        for atom in atoms:
            t = embed_service.atom_to_text(atom)
            if t.strip():
                texts.append(t)
                valid_atoms.append(atom)
            else:
                atom.needs_embedding = False

        if texts:
            embeddings = model.encode(texts)
            for atom, vec in zip(valid_atoms, embeddings):
                vec_list = vec.tolist()
                existing = s.query(AtomEmbedding).filter(
                    AtomEmbedding.atom_id == atom.id,
                    AtomEmbedding.model_name == embed_service.MODEL_NAME,
                ).first()
                if existing:
                    existing.embedding = vec_list
                else:
                    s.add(AtomEmbedding(
                        atom_id=atom.id,
                        embedding=vec_list,
                        model_name=embed_service.MODEL_NAME,
                    ))
                atom.needs_embedding = False

        # 清除無內容原子的 flag
        s.flush()
        count = len(valid_atoms)
        if count:
            logger.info(f'Embedded {count} atoms')
        return count


def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest 背景 Embedding Worker'
    )
    parser.add_argument('--daemon', action='store_true',
                        help='持續監聽模式')
    parser.add_argument('--interval', type=int, default=30,
                        help='掃描間隔秒數（預設 30）')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='組態檔路徑')

    if len(sys.argv) == 1:
        # 無參數：一次性處理
        pass

    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [embed_worker] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    init_engine(config_path)

    if args.daemon:
        logger.info(f'Daemon mode, interval={args.interval}s')
        while True:
            try:
                process_pending()
                _write_heartbeat()
            except Exception as e:
                logger.error(f'Error: {e}')
            time.sleep(args.interval)
    else:
        count = process_pending()
        # heartbeat 表示「worker 跑過且未拋異常」，與是否有 pending 無關。
        # 舊版只在 count>0 寫 heartbeat 會讓 heartbeat_monitor 誤判長時間無新
        # 原子的情形為「embed_worker 壞了」。
        _write_heartbeat()
        if count:
            print(f'Processed {count} atoms')
        else:
            print('No pending atoms')


if __name__ == '__main__':
    main()
