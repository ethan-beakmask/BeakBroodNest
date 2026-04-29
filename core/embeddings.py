"""
向量嵌入服務 -- 語意搜尋的基礎
模型：paraphrase-multilingual-MiniLM-L12-v2 (384 dim, 支援中文)
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.models import KnowledgeAtom, AtomEmbedding

logger = logging.getLogger('beak_cortex.embeddings')

MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'
EMBEDDING_DIM = 384

# 延遲載入模型（首次呼叫時才載入，約 14 秒）
_model = None


def _get_model():
    """延遲載入 SentenceTransformer 模型"""
    global _model
    if _model is None:
        logger.info(f'Loading embedding model: {MODEL_NAME}')
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
        logger.info(f'Model loaded, dim={_model.get_embedding_dimension()}')
    return _model


def generate_embedding(text_content: str) -> list[float]:
    """生成單一文本的 embedding 向量"""
    model = _get_model()
    embedding = model.encode([text_content])[0]
    return embedding.tolist()


def atom_to_text(atom: KnowledgeAtom) -> str:
    """將原子轉換為嵌入用文本（title + content_plain）。
    優先用 content_plain（HTML stripped），避免 <font> / <span style> 噪音污染向量；
    若 content_plain 為 None（極少見，例如 migration 後尚未回填），fallback 用 content。
    """
    parts = []
    if atom.title:
        parts.append(atom.title)
    body = atom.content_plain if atom.content_plain is not None else atom.content
    if body:
        parts.append(body)
    return '\n'.join(parts) if parts else ''


def embed_atom(session: Session, atom_id: int) -> Optional[AtomEmbedding]:
    """為單一原子生成並儲存 embedding"""
    atom = session.query(KnowledgeAtom).filter(
        KnowledgeAtom.id == atom_id,
        KnowledgeAtom.is_deleted == False,
    ).first()
    if not atom:
        return None

    text_content = atom_to_text(atom)
    if not text_content.strip():
        return None

    vec = generate_embedding(text_content)

    # Upsert: 若已存在則更新
    existing = session.query(AtomEmbedding).filter(
        AtomEmbedding.atom_id == atom_id,
        AtomEmbedding.model_name == MODEL_NAME,
    ).first()

    if existing:
        existing.embedding = vec
        session.flush()
        return existing

    emb = AtomEmbedding(
        atom_id=atom_id,
        embedding=vec,
        model_name=MODEL_NAME,
    )
    session.add(emb)
    session.flush()
    return emb


def embed_all_atoms(session: Session) -> int:
    """批次為所有尚無 embedding 的原子生成 embedding，回傳處理數量"""
    from sqlalchemy import exists

    atoms = (
        session.query(KnowledgeAtom)
        .filter(
            KnowledgeAtom.is_deleted == False,
            ~exists().where(
                (AtomEmbedding.atom_id == KnowledgeAtom.id) &
                (AtomEmbedding.model_name == MODEL_NAME)
            )
        )
        .all()
    )

    if not atoms:
        logger.info('All atoms already have embeddings')
        return 0

    # 批次 encode 效能更好
    model = _get_model()
    texts = []
    valid_atoms = []
    for atom in atoms:
        t = atom_to_text(atom)
        if t.strip():
            texts.append(t)
            valid_atoms.append(atom)

    if not texts:
        return 0

    logger.info(f'Generating embeddings for {len(texts)} atoms...')
    embeddings = model.encode(texts)

    for atom, vec in zip(valid_atoms, embeddings):
        emb = AtomEmbedding(
            atom_id=atom.id,
            embedding=vec.tolist(),
            model_name=MODEL_NAME,
        )
        session.add(emb)

    session.flush()
    logger.info(f'Generated {len(valid_atoms)} embeddings')
    return len(valid_atoms)


def search_similar(
    session: Session,
    query_text: str,
    limit: int = 10,
    lifecycle: str = '',
) -> list[dict]:
    """
    向量相似度搜尋：回傳最相似的原子
    使用 pgvector cosine distance (<=>)
    """
    query_vec = generate_embedding(query_text)

    # 使用原生 SQL 搭配 pgvector 運算符
    sql = text("""
        SELECT
            a.id, a.title, a.content, a.atom_type, a.lifecycle,
            a.vitality_score, a.source,
            1 - (e.embedding <=> :query_vec) AS similarity
        FROM atom_embeddings e
        JOIN knowledge_atoms a ON a.id = e.atom_id
        WHERE a.is_deleted = FALSE
          AND e.model_name = :model_name
          AND (:lifecycle = '' OR a.lifecycle = :lifecycle)
        ORDER BY e.embedding <=> :query_vec
        LIMIT :limit
    """)

    rows = session.execute(sql, {
        'query_vec': str(query_vec),
        'model_name': MODEL_NAME,
        'lifecycle': lifecycle or '',
        'limit': limit,
    }).fetchall()

    results = []
    for row in rows:
        results.append({
            'id': row[0],
            'title': row[1],
            'content': row[2][:200] if row[2] else '',
            'atom_type': row[3],
            'lifecycle': row[4],
            'vitality_score': row[5],
            'source': row[6],
            'similarity': round(row[7], 4),
        })

    return results
