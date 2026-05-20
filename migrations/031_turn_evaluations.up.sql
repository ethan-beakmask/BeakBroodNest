-- 031: turn_evaluations 表 (對單一 turn 的評分，含知識分數與幻覺比率)
--
-- 背景：
--   想對 conversation_turns 每一輪做評分（知識分數、幻覺比率等）。
--   P1 signals 是事實萃取「寫一次就定」，所以直接放主表。
--   評分會隨評估器版本/prompt/baseline 反覆重跑，且未來指標可能擴增，
--   所以另建獨立表，UNIQUE(turn_id, evaluator) 保留多版本歷史。
--
-- 指標仍在規劃中（見「AI 幻覺偵測」待辦 atom），先把 schema 與兩個
-- 預設欄位 knowledge_score / hallucination_rate 建出來，其他指標走 details jsonb。

BEGIN;

CREATE TABLE IF NOT EXISTS turn_evaluations (
    id                 BIGSERIAL PRIMARY KEY,
    turn_id            INTEGER NOT NULL REFERENCES conversation_turns(id) ON DELETE CASCADE,
    evaluator          TEXT NOT NULL,
    -- evaluator: 評估器版本識別，例如 'p3-hallucination-v1' / 'sonnet-4-6@2026-05'
    scored_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    knowledge_score    NUMERIC(4,3),
    -- knowledge_score: 0.000 ~ 1.000，本輪對「有用知識」的貢獻度
    hallucination_rate NUMERIC(4,3),
    -- hallucination_rate: 0.000 ~ 1.000，本輪內容捏造/錯誤比率
    details            JSONB,
    -- details: 細項證據、引用、判定理由、子指標等
    UNIQUE (turn_id, evaluator)
);

CREATE INDEX IF NOT EXISTS idx_turn_eval_turn
    ON turn_evaluations (turn_id);
CREATE INDEX IF NOT EXISTS idx_turn_eval_evaluator
    ON turn_evaluations (evaluator, scored_at DESC);

COMMENT ON TABLE turn_evaluations IS
    '單一 turn 的評分結果。多評估器版本共存，UNIQUE(turn_id, evaluator) 約束。';
COMMENT ON COLUMN turn_evaluations.evaluator IS
    '評估器版本識別字串，換版本即新增 row 而非覆寫，可做 A/B 與趨勢比對。';
COMMENT ON COLUMN turn_evaluations.knowledge_score IS
    '0.000~1.000，本輪對「有用知識」的貢獻度。';
COMMENT ON COLUMN turn_evaluations.hallucination_rate IS
    '0.000~1.000，本輪內容的捏造/錯誤比率。';
COMMENT ON COLUMN turn_evaluations.details IS
    '判定細節，jsonb 自由擴充：子指標、證據引用、模型 raw output 等。';

COMMIT;
