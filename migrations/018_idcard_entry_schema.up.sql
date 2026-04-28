-- 018: 帳卡 entry schema (;;idcard)
-- 在卡片內以「員工識別證」版型呈現：左方正方形圖框 + 右方四列文字
-- 適用於人員通訊錄、設備清單、客戶名片等場景
-- 圖檔來源：uploaded_files（從相簿挑選 image_token）
-- is_primary：白板縮圖時優先以此 entry 取代 thumbnail_url；同卡多個 idcard 只能有一個 primary（前端控制單選）

INSERT INTO entry_schemas (code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at)
VALUES ('idcard', '帳卡', 'bi-person-badge', '#0ea5e9', 'idcard', TRUE, 80, now(), now())
ON CONFLICT (code) DO NOTHING;

INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension)
SELECT s.id, v.name, v.label, v.field_type, v.options, v.required, v.sort_order, v.dimension
FROM entry_schemas s
CROSS JOIN (VALUES
    ('image_token', '圖檔',      'text',     '', FALSE, 0, NULL),
    ('line1',       '主標',      'text',     '', FALSE, 1, 'W'),
    ('line2',       '副標',      'text',     '', FALSE, 2, NULL),
    ('line3',       '第三列',    'text',     '', FALSE, 3, NULL),
    ('line4',       '第四列',    'text',     '', FALSE, 4, NULL),
    ('is_primary',  '白板主帳卡', 'checkbox', '', FALSE, 5, NULL)
) AS v(name, label, field_type, options, required, sort_order, dimension)
WHERE s.code = 'idcard'
  AND NOT EXISTS (
      SELECT 1 FROM entry_schema_fields f
      WHERE f.schema_id = s.id AND f.name = v.name
  );
