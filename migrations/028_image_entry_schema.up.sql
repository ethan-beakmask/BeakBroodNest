-- 028: 圖片 entry schema (;;image)
-- 在卡片內以「圖片」版型呈現：縮圖 + 說明文字 (caption)
-- 適用場景：章節插圖、流程截圖、相片等需要嵌入卡片的圖
-- 與 ;;idcard 差異：image 沒有四列文字、沒有 is_primary，是輕量的「圖+說明」物件
-- 圖檔來源：uploaded_files（從相簿挑選 image_token）
-- 為日後心智圖節點「圖+文」渲染預作準備：心智圖節點將從 Card 內的 ;;image entry 取圖與說明

INSERT INTO entry_schemas (code, name, icon, color, slash_alias, is_system, sort_order, created_at, updated_at)
VALUES ('image', '圖片', 'bi-image', '#14b8a6', 'image', TRUE, 81, now(), now())
ON CONFLICT (code) DO NOTHING;

INSERT INTO entry_schema_fields (schema_id, name, label, field_type, options, required, sort_order, dimension)
SELECT s.id, v.name, v.label, v.field_type, v.options, v.required, v.sort_order, v.dimension
FROM entry_schemas s
CROSS JOIN (VALUES
    ('image_token', '圖檔', 'text', '', FALSE, 0, NULL),
    ('caption',     '說明', 'text', '', FALSE, 1, NULL)
) AS v(name, label, field_type, options, required, sort_order, dimension)
WHERE s.code = 'image'
  AND NOT EXISTS (
      SELECT 1 FROM entry_schema_fields f
      WHERE f.schema_id = s.id AND f.name = v.name
  );
