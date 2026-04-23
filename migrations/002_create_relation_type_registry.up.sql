-- Migration 002 UP: 建立 relation_type_registry 參照表
-- Phase 1 連線系統：集中管理關係類型的圖族、語意層、顯示屬性
-- 回滾：002_create_relation_type_registry.down.sql

BEGIN;

CREATE TABLE relation_type_registry (
    relation_type       VARCHAR(30) PRIMARY KEY,
    graph_family        VARCHAR(20) NOT NULL
                        CHECK (graph_family IN ('acyclic_tree', 'acyclic_dag', 'free_graph')),
    semantic_layer      VARCHAR(20) NOT NULL
                        CHECK (semantic_layer IN ('structural', 'temporal', 'discourse')),
    affects_scheduling  BOOLEAN NOT NULL DEFAULT FALSE,
    display_name        VARCHAR(100) NOT NULL,
    is_directed         BOOLEAN NOT NULL DEFAULT TRUE,
    description         TEXT DEFAULT '',
    default_color       VARCHAR(20) DEFAULT '#6b7280',
    default_style       VARCHAR(30) DEFAULT 'solid',
    sort_order          INTEGER DEFAULT 0
);

COMMENT ON TABLE relation_type_registry IS
    'Phase 1 連線系統：關係類型參照表，graph_family 決定寫入驗證，semantic_layer 決定下游視圖過濾';

INSERT INTO relation_type_registry
    (relation_type,  graph_family,   semantic_layer, affects_scheduling,
     display_name, is_directed, default_color, default_style, sort_order, description) VALUES
    ('contains',     'acyclic_tree', 'structural',   FALSE,
     '包含',   TRUE, '#8b5cf6', 'solid',  1, '父卡片包含子卡片，構成層級結構'),
    ('blocks',       'acyclic_dag',  'temporal',     TRUE,
     '阻塞',   TRUE, '#dc2626', 'solid',  2, 'A 未完成前 B 無法開始（硬約束）'),
    ('follows',      'acyclic_dag',  'temporal',     TRUE,
     '接續',   TRUE, '#3b82f6', 'dashed', 3, 'B 在 A 之後發生（軟約束）'),
    ('enables',      'acyclic_dag',  'temporal',     FALSE,
     '促成',   TRUE, '#f97316', 'solid',  4, 'A 使 B 成為可能（邏輯前提，不排程）'),
    ('causes',       'acyclic_dag',  'temporal',     FALSE,
     '導致',   TRUE, '#ef4444', 'solid',  5, 'A 是 B 的原因（事實因果，不排程）'),
    ('derives_from', 'acyclic_dag',  'discourse',    FALSE,
     '衍生自', TRUE, '#06b6d4', 'dashed', 6, 'B 衍生自 A（知識演化）'),
    ('supersedes',   'acyclic_dag',  'discourse',    FALSE,
     '取代',   TRUE, '#64748b', 'dotted', 7, 'A 取代 B（新版替換舊版）'),
    ('supports',     'free_graph',   'discourse',    FALSE,
     '支持',   TRUE, '#22c55e', 'solid',  8, '證據 A 支持結論 B'),
    ('contradicts',  'free_graph',   'discourse',    FALSE,
     '矛盾',   TRUE, '#f59e0b', 'solid',  9, 'A 與 B 矛盾'),
    ('references',   'free_graph',   'discourse',    FALSE,
     '參考',   TRUE, '#6b7280', 'dotted', 10, 'A 引用 B 作為參考來源');

COMMIT;
