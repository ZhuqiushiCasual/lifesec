-- 本文件由 backend/gen_schema.py 自动生成，请勿手改；改模型后重新生成
CREATE DATABASE IF NOT EXISTS life_secretary;
USE life_secretary;

CREATE TABLE users (
	id VARCHAR(36) NOT NULL COMMENT '用户唯一标识 UUID', 
	email VARCHAR(255) NOT NULL COMMENT '登录邮箱', 
	name VARCHAR(100) COMMENT '用户昵称', 
	hashed_password VARCHAR(255) NOT NULL COMMENT '密码哈希值（SHA-256）', 
	preferences TEXT COMMENT '用户偏好设置（JSON 字符串）', 
	is_active BOOL NOT NULL COMMENT '账号是否启用', 
	created_at DATETIME NOT NULL COMMENT '创建时间' DEFAULT now(), 
	updated_at DATETIME NOT NULL COMMENT '最后更新时间' DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (email)
)COMMENT='用户表——存储用户账号信息';

CREATE TABLE digests (
	id VARCHAR(36) NOT NULL COMMENT '日报唯一标识 UUID', 
	user_id VARCHAR(36) NOT NULL COMMENT '关联用户 ID', 
	date DATE NOT NULL COMMENT '日报日期', 
	score INTEGER COMMENT '当日生活评分（0~100）', 
	highlights JSON COMMENT '今日亮点（JSON 结构体）', 
	problems JSON COMMENT '今日问题（JSON 结构体）', 
	suggestions JSON COMMENT '改进建议（JSON 结构体）', 
	trends JSON COMMENT '趋势分析（JSON 结构体）', 
	created_at DATETIME NOT NULL COMMENT '记录创建时间' DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)COMMENT='日报表——每日自动生成的用户生活总结';

CREATE TABLE events (
	id VARCHAR(36) NOT NULL COMMENT '事件唯一标识 UUID', 
	user_id VARCHAR(36) NOT NULL COMMENT '关联用户 ID', 
	type VARCHAR(50) NOT NULL COMMENT '事件类型（如 life_habit / social / work / health）', 
	content TEXT NOT NULL COMMENT '事件原始内容文本', 
	entities JSON COMMENT '提取的实体信息（JSON）', 
	sentiment VARCHAR(20) COMMENT '情感倾向（positive / neutral / negative）', 
	sentiment_score FLOAT COMMENT '情感得分（0~1）', 
	tags JSON COMMENT '标签列表（JSON 数组）', 
	voice_source BOOL NOT NULL COMMENT '是否来自语音输入', 
	recorded_at DATETIME NOT NULL COMMENT '事件发生时间' DEFAULT now(), 
	created_at DATETIME NOT NULL COMMENT '记录创建时间' DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)COMMENT='事件记录表——记录用户生活事件（语音/文字输入）';

CREATE TABLE finance_txns (
	id VARCHAR(36) NOT NULL COMMENT '交易唯一标识 UUID', 
	user_id VARCHAR(36) NOT NULL COMMENT '关联用户 ID', 
	type VARCHAR(20) NOT NULL COMMENT '收支类型（income / expense）', 
	amount NUMERIC(15, 2) NOT NULL COMMENT '金额', 
	currency VARCHAR(10) NOT NULL COMMENT '币种（默认 CNY）', 
	category VARCHAR(50) NOT NULL COMMENT '分类（如 food / transport / salary）', 
	counterparty VARCHAR(200) COMMENT '交易对手', 
	account VARCHAR(50) COMMENT '账户（如 支付宝 / 微信）', 
	note TEXT COMMENT '备注', 
	voice_source BOOL NOT NULL COMMENT '是否来自语音输入', 
	recorded_at DATETIME NOT NULL COMMENT '交易发生时间' DEFAULT now(), 
	created_at DATETIME NOT NULL COMMENT '记录创建时间' DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)COMMENT='财务记录表——存储每一笔收支';

CREATE TABLE insights (
	id VARCHAR(36) NOT NULL COMMENT '洞察唯一标识 UUID', 
	user_id VARCHAR(36) NOT NULL COMMENT '关联用户 ID', 
	title VARCHAR(500) NOT NULL COMMENT '洞察标题', 
	summary TEXT NOT NULL COMMENT '核心摘要', 
	impact TEXT COMMENT '对我生活/工作的影响分析', 
	category VARCHAR(50) NOT NULL COMMENT '洞察类别（如 tech / finance / health / career）', 
	topics JSON COMMENT '相关主题标签（JSON 数组）', 
	importance INTEGER COMMENT '重要程度（1~5）', 
	source_url VARCHAR(1000) COMMENT '来源链接', 
	source_name VARCHAR(200) COMMENT '来源名称（如 知乎 / 公众号）', 
	published_at DATETIME COMMENT '原文发布时间', 
	created_at DATETIME NOT NULL COMMENT '记录创建时间' DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)COMMENT='信息洞察表——存储 AI 提取的知识、观点、文章摘要';
