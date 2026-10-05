-- 时间戳精度迁移：DATETIME（精度 0，只到秒）→ DATETIME(6)（微秒）
--
-- 为什么需要：
--   一次 /api/chat 会先落一条 events（用户原话）、再落一条 messages（它的回应），
--   两者时间只差几毫秒。MySQL 的 DATETIME 默认精度是「秒」（precision=0），
--   截断后这两条记录的 created_at 完全相等，ORDER BY 就定不出先后。
--   （线上 selfsec 库实测：所有对话对都是同秒并列。）
--
--   即使不做这次迁移，代码也已经能处理并列（窗口流按 (时间, 轮次) 归并），
--   但游标翻页仍会因为「同一秒里有多条」而可能漏记，所以老库建议迁移。
--
-- 为什么必须手动跑：
--   表由 SQLAlchemy 的 create_all 创建，它只建缺失的表、不会 ALTER 已有表，
--   所以老库要执行一次本脚本。首次部署的新库会直接用 DATETIME(6) 建表，无需处理。
--
-- 执行（在服务器上，容器名/账号按实际情况替换）：
--   docker exec -i mysql-8.0.32 sh -c 'mysql -u<user> -p"$MYSQL_PASSWORD" selfsec' < docs/alter-datetime6.sql
--
-- 校验（precision 应该是 6）：
--   SELECT table_name, column_name, datetime_precision FROM information_schema.columns
--    WHERE table_schema='selfsec' AND column_name IN ('created_at','recorded_at','updated_at');

USE selfsec;

ALTER TABLE users
  MODIFY created_at DATETIME(6) NOT NULL COMMENT '创建时间';

ALTER TABLE events
  MODIFY recorded_at DATETIME(6) NOT NULL COMMENT '事件发生时间',
  MODIFY created_at  DATETIME(6) NOT NULL COMMENT '记录创建时间';

ALTER TABLE messages
  MODIFY read_at    DATETIME(6) DEFAULT NULL COMMENT '已读时间',
  MODIFY created_at DATETIME(6) NOT NULL;

ALTER TABLE plans
  MODIFY created_at DATETIME(6) NOT NULL,
  MODIFY updated_at DATETIME(6) NOT NULL;

ALTER TABLE memory_profile
  MODIFY updated_at DATETIME(6) NOT NULL;
