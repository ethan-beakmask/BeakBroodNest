-- 019 down: 移除「資料表總覽」選單項目
-- 註：COMMENT ON TABLE 不還原（不影響功能、保留為佳）。

BEGIN;

DELETE FROM nav_menu WHERE url = '/beakbroodnest/admin/tables';

COMMIT;
