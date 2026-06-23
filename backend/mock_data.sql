-- ============================================================
-- Mock Data for Life Secretary
-- Password for both users: 123456
-- Uses CURDATE() so events always fall in the current week
-- ============================================================

SET @d0 = CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY;  -- Monday
SET @d1 = @d0 + INTERVAL 1 DAY;
SET @d2 = @d0 + INTERVAL 2 DAY;
SET @d3 = @d0 + INTERVAL 3 DAY;
SET @d4 = @d0 + INTERVAL 4 DAY;
SET @d5 = @d0 + INTERVAL 5 DAY;
SET @d6 = @d0 + INTERVAL 6 DAY;

-- Users
INSERT INTO `users` (`id`, `email`, `name`, `hashed_password`, `preferences`, `is_active`, `created_at`, `updated_at`)
VALUES
('u0010000-0000-4000-8000-000000000001', 'alice@example.com', 'Alice',  '4443426ea20f6e13f6f94e3ce0b4e1aa$7a66b0c8ed819c38a792297357a3edc1f2872bef8543f5e7bb0b29bc7edb8ea2', '{"theme":"light","language":"zh"}', 1, NOW(), NOW()),
('u0010000-0000-4000-8000-000000000002', 'bob@example.com',   'Bob',    '4443426ea20f6e13f6f94e3ce0b4e1aa$7a66b0c8ed819c38a792297357a3edc1f2872bef8543f5e7bb0b29bc7edb8ea2', NULL, 1, NOW(), NOW()),
('u0010000-0000-4000-8000-000000000003', 'chen@qq.com',      '小陈',   '4443426ea20f6e13f6f94e3ce0b4e1aa$7a66b0c8ed819c38a792297357a3edc1f2872bef8543f5e7bb0b29bc7edb8ea2', '{"theme":"dark"}', 1, NOW(), NOW());

-- Events (Alice — 本周数据, 按天分布)
INSERT INTO `events` (`id`, `user_id`, `type`, `content`, `entities`, `sentiment`, `sentiment_score`, `tags`, `voice_source`, `recorded_at`, `created_at`)
VALUES
-- ===== 周一 =====
('e0010000-0000-4000-8000-000000000001', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '昨晚睡了7.5小时，一觉到天亮', '{"duration":7.5,"quality":4,"bedtime":"23:30","wake_time":"07:00","has_dream":false,"nap":false}', 'positive', 0.85, '["睡眠"]', 0, @d0 + INTERVAL '07:15' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000002', 'u0010000-0000-4000-8000-000000000001', 'dietary', '早餐吃了全麦面包和鸡蛋', '{"meal":"breakfast","foods":["全麦面包","鸡蛋"],"calories":350,"water_ml":0,"is_healthy":true}', 'neutral', 0.50, '["饮食"]', 0, @d0 + INTERVAL '08:15' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000003', 'u0010000-0000-4000-8000-000000000001', 'sport',   '早上跑了5公里，花了30分钟', '{"activity":"跑步","duration":30,"distance":5,"calories":280,"intensity":"medium"}', 'positive', 0.92, '["运动"]', 0, @d0 + INTERVAL '07:30' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000004', 'u0010000-0000-4000-8000-000000000001', 'mood',    '今天心情不错，精力充沛', '{"emotion":"happy","score":4,"trigger":"","energy":4}', 'positive', 0.88, '["心情"]', 0, @d0 + INTERVAL '10:00' HOUR_MINUTE, NOW()),

-- ===== 周二 =====
('e0010000-0000-4000-8000-000000000005', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '只睡了6小时，有点困', '{"duration":6,"quality":3,"bedtime":"00:30","wake_time":"06:30","has_dream":true,"nap":false}', 'neutral', 0.45, '["睡眠"]', 0, @d1 + INTERVAL '07:20' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000006', 'u0010000-0000-4000-8000-000000000001', 'dietary', '午餐吃了沙拉和鸡胸肉', '{"meal":"lunch","foods":["沙拉","鸡胸肉"],"calories":420,"water_ml":0,"is_healthy":true}', 'positive', 0.70, '["饮食"]', 0, @d1 + INTERVAL '12:30' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000007', 'u0010000-0000-4000-8000-000000000001', 'health',  '称了一下体重72.5kg', '{"metric_name":"weight","metric_value":72.5,"metric_unit":"kg","symptom":"","body_part":"","severity":0,"hospital":"","medication":""}', 'neutral', 0.50, '["健康","体重"]', 0, @d1 + INTERVAL '09:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000008', 'u0010000-0000-4000-8000-000000000001', 'mood',    '下午有点焦虑，担心项目进度', '{"emotion":"anxious","score":2,"trigger":"项目进度","energy":3}', 'negative', 0.30, '["心情"]', 0, @d1 + INTERVAL '15:00' HOUR_MINUTE, NOW()),

-- ===== 周三 =====
('e0010000-0000-4000-8000-000000000009', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '睡了8小时，质量很好', '{"duration":8,"quality":5,"bedtime":"22:30","wake_time":"06:30","has_dream":false,"nap":false}', 'positive', 0.90, '["睡眠"]', 0, @d2 + INTERVAL '07:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000010', 'u0010000-0000-4000-8000-000000000001', 'sport',   '晚上做了60分钟瑜伽', '{"activity":"瑜伽","duration":60,"distance":0,"calories":200,"intensity":"low"}', 'positive', 0.85, '["运动","健康"]', 0, @d2 + INTERVAL '20:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000011', 'u0010000-0000-4000-8000-000000000001', 'event',   '完成了项目方案初稿', '{"category":"work","title":"完成项目方案初稿","location":"公司","participants":[]}', 'positive', 0.80, '["工作"]', 0, @d2 + INTERVAL '10:30' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000012', 'u0010000-0000-4000-8000-000000000001', 'dietary', '早餐吃了燕麦粥', '{"meal":"breakfast","foods":["燕麦粥"],"calories":280,"water_ml":0,"is_healthy":true}', 'neutral', 0.55, '["饮食"]', 0, @d2 + INTERVAL '08:00' HOUR_MINUTE, NOW()),

-- ===== 周四 =====
('e0010000-0000-4000-8000-000000000013', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '睡了7小时，还行', '{"duration":7,"quality":4,"bedtime":"23:00","wake_time":"06:00","has_dream":false,"nap":false}', 'neutral', 0.60, '["睡眠"]', 0, @d3 + INTERVAL '06:30' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000014', 'u0010000-0000-4000-8000-000000000001', 'dietary', '晚餐吃了牛排和红酒', '{"meal":"dinner","foods":["牛排","红酒"],"calories":650,"water_ml":0,"is_healthy":false}', 'positive', 0.75, '["饮食"]', 0, @d3 + INTERVAL '19:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000015', 'u0010000-0000-4000-8000-000000000001', 'mood',    '心情平静，专注工作', '{"emotion":"calm","score":3,"trigger":"","energy":3}', 'neutral', 0.55, '["心情"]', 0, @d3 + INTERVAL '14:00' HOUR_MINUTE, NOW()),

-- ===== 周五 =====
('e0010000-0000-4000-8000-000000000016', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '只睡了6.5小时，周末要补觉', '{"duration":6.5,"quality":3,"bedtime":"00:00","wake_time":"06:30","has_dream":true,"nap":false}', 'neutral', 0.50, '["睡眠"]', 0, @d4 + INTERVAL '06:45' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000017', 'u0010000-0000-4000-8000-000000000001', 'sport',   '下午游了45分钟泳', '{"activity":"游泳","duration":45,"distance":0,"calories":350,"intensity":"medium"}', 'positive', 0.90, '["运动"]', 0, @d4 + INTERVAL '16:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000018', 'u0010000-0000-4000-8000-000000000001', 'mood',    '周五了，非常开心', '{"emotion":"excited","score":5,"trigger":"周末来了","energy":5}', 'positive', 0.95, '["心情"]', 0, @d4 + INTERVAL '17:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000019', 'u0010000-0000-4000-8000-000000000001', 'dietary', '午餐吃了日料', '{"meal":"lunch","foods":["日料","寿司"],"calories":500,"water_ml":0,"is_healthy":true}', 'positive', 0.75, '["饮食"]', 0, @d4 + INTERVAL '12:00' HOUR_MINUTE, NOW()),

-- ===== 周六 =====
('e0010000-0000-4000-8000-000000000020', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '周末睡了9小时，太舒服了', '{"duration":9,"quality":5,"bedtime":"23:00","wake_time":"08:00","has_dream":false,"nap":true}', 'positive', 0.95, '["睡眠"]', 0, @d5 + INTERVAL '08:30' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000021', 'u0010000-0000-4000-8000-000000000001', 'event',   '和朋友聚餐', '{"category":"social","title":"和朋友聚餐","location":"日料店","participants":["小明","小红"]}', 'positive', 0.85, '["社交"]', 0, @d5 + INTERVAL '18:00' HOUR_MINUTE, NOW()),

-- ===== 周日 =====
('e0010000-0000-4000-8000-000000000022', 'u0010000-0000-4000-8000-000000000001', 'sleep',   '睡了8小时，精神饱满', '{"duration":8,"quality":4,"bedtime":"22:30","wake_time":"06:30","has_dream":false,"nap":false}', 'positive', 0.88, '["睡眠"]', 0, @d6 + INTERVAL '07:00' HOUR_MINUTE, NOW()),

-- Bob 的事件 (本周)
('e0010000-0000-4000-8000-000000000023', 'u0010000-0000-4000-8000-000000000002', 'health',  '今天感冒了，喉咙痛', '{"metric_name":"","metric_value":0,"metric_unit":"","symptom":"喉咙痛","body_part":"喉咙","severity":3,"hospital":"","medication":"感冒灵"}', 'negative', 0.20, '["健康","生病"]', 0, @d0 + INTERVAL '09:00' HOUR_MINUTE, NOW()),
('e0010000-0000-4000-8000-000000000024', 'u0010000-0000-4000-8000-000000000002', 'event',   '请假一天在家休息', '{"category":"work","title":"请假休息","location":"家","participants":[]}', 'neutral', 0.45, '["工作"]', 0, @d0 + INTERVAL '10:00' HOUR_MINUTE, NOW());

-- Finance Transactions (Alice — 本月)
INSERT INTO `finance_txns` (`id`, `user_id`, `type`, `amount`, `currency`, `category`, `counterparty`, `account`, `note`, `voice_source`, `recorded_at`, `created_at`)
VALUES
('f0010000-0000-4000-8000-000000000001', 'u0010000-0000-4000-8000-000000000001', 'expense',  35.00,  'CNY', 'food',      '日料店',        '支付宝', '中午和同事吃饭',        0, @d4 + INTERVAL '12:30' HOUR_MINUTE, NOW()),
('f0010000-0000-4000-8000-000000000002', 'u0010000-0000-4000-8000-000000000001', 'expense',  15.00,  'CNY', 'transport', '滴滴出行',      '支付宝', '打车去公司',            1, @d0 + INTERVAL '08:30' HOUR_MINUTE, NOW()),
('f0010000-0000-4000-8000-000000000003', 'u0010000-0000-4000-8000-000000000001', 'income',   15000,  'CNY', 'salary',    '公司',           '银行卡', '工资',                  0, CURDATE() - INTERVAL 5 DAY, NOW()),
('f0010000-0000-4000-8000-000000000004', 'u0010000-0000-4000-8000-000000000001', 'expense',  5000,   'CNY', 'rent',      '房东',           '银行卡', '房租',                  0, CURDATE() - INTERVAL 10 DAY, NOW()),
('f0010000-0000-4000-8000-000000000005', 'u0010000-0000-4000-8000-000000000001', 'expense',  299,    'CNY', 'shopping',  '京东',           '支付宝', '蓝牙耳机',              0, CURDATE() - INTERVAL 3 DAY, NOW()),
('f0010000-0000-4000-8000-000000000006', 'u0010000-0000-4000-8000-000000000001', 'expense',  18.50,  'CNY', 'food',      '星巴克',         '微信',   '冰美式',               1, @d2 + INTERVAL '14:30' HOUR_MINUTE, NOW()),

-- Bob 的财务
('f0010000-0000-4000-8000-000000000007', 'u0010000-0000-4000-8000-000000000002', 'expense',  45.00,  'CNY', 'food',      '美团外卖',       '微信',   '午餐外卖',             0, @d0 + INTERVAL '12:30' HOUR_MINUTE, NOW()),
('f0010000-0000-4000-8000-000000000008', 'u0010000-0000-4000-8000-000000000002', 'expense',  32.00,  'CNY', 'medical',   '药店',           '支付宝', '买感冒药',             0, @d0 + INTERVAL '10:30' HOUR_MINUTE, NOW());

-- Insights
INSERT INTO `insights` (`id`, `user_id`, `title`, `summary`, `impact`, `category`, `topics`, `importance`, `source_url`, `source_name`, `published_at`, `created_at`)
VALUES
('i0010000-0000-4000-8000-000000000001', 'u0010000-0000-4000-8000-000000000001',
 '每天跑步5公里能显著提升心血管健康',
 '最新研究表明，每天坚持跑步5公里可以将心血管疾病风险降低30%。',
 '可以继续坚持晨跑习惯，对长期健康有益。',
 'health', '["运动","健康","心血管"]', 4,
 'https://example.com/study1', '健康时报', CURDATE() - INTERVAL 5 DAY, NOW()),

('i0010000-0000-4000-8000-000000000002', 'u0010000-0000-4000-8000-000000000001',
 'AIGC 2026发展趋势：多模态成为主流',
 '多模态AI模型正在快速普及，预计年底前80%的企业将采用多模态AI解决方案。',
 '可以关注相关技能学习，提升职场竞争力。',
 'tech', '["AI","多模态","职场"]', 5,
 'https://example.com/ai-trends', '36氪', CURDATE() - INTERVAL 6 DAY, NOW()),

('i0010000-0000-4000-8000-000000000003', 'u0010000-0000-4000-8000-000000000001',
 '投资基金定投策略在震荡市中的表现',
 '2026年二季度市场震荡期间，定投策略相比一次性投资收益率高出5.2%。',
 '可以考虑将每月结余的一部分用于定投指数基金。',
 'finance', '["投资","基金","定投"]', 3,
 'https://example.com/invest', '雪球', CURDATE() - INTERVAL 7 DAY, NOW());

-- Digests (日报)
INSERT INTO `digests` (`id`, `user_id`, `date`, `score`, `highlights`, `problems`, `suggestions`, `trends`, `created_at`)
VALUES
('d0010000-0000-4000-8000-000000000001', 'u0010000-0000-4000-8000-000000000001',
 CURDATE() - INTERVAL 1 DAY, 78,
 '{"morning_run":"早上跑步5公里完成","social":"和同事午餐社交","water":"饮水达标"}',
 '{"afternoon_anxiety":"下午出现焦虑情绪"}',
 '{"meditation":"建议每天增加10分钟冥想"}',
 '{"mood_trend":"最近一周情绪呈上升趋势","exercise_freq":"本周运动4次，良好"}',
 NOW()),

('d0010000-0000-4000-8000-000000000002', 'u0010000-0000-4000-8000-000000000002',
 CURDATE() - INTERVAL 1 DAY, 45,
 '{}',
 '{"sick":"感冒，喉咙痛"}',
 '{"rest":"建议多休息，多喝热水","doctor":"如果明天未好转建议就医"}',
 '{}',
 NOW());
