-- 1. Пользователи (хранение профиля, UTM/трафика и отметки 152-ФЗ)
CREATE TABLE IF NOT EXISTS users (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT NOT NULL DEFAULT 'ru',
    telegram_language_code TEXT,             -- сырой код Telegram, только диагностика
    locale_source TEXT NOT NULL DEFAULT 'legacy', -- 'auto' | 'manual' | 'legacy'
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    is_shadow_banned INTEGER NOT NULL DEFAULT 0, -- 1 = тихий сброс спамера (подтверждено архитектором)
    shadow_ban_reason TEXT,
    consent_at TEXT,                         -- ISO-8601 отметка 152-ФЗ; сбор согласия — в кузове
    traffic_source TEXT,                     -- UTM/реферальный хвост из /start <payload>; first-touch (не перезаписывается)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_bot_banned ON users(bot_id, is_banned);
CREATE INDEX IF NOT EXISTS idx_users_bot_shbanned ON users(bot_id, is_shadow_banned);

-- 2. Роли доступа (строго admin и superadmin)
CREATE TABLE IF NOT EXISTS roles (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,                      -- 'admin' | 'superadmin'
    granted_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, user_id, role),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_roles_lookup ON roles(bot_id, user_id, role);

-- 3. Транзакции и талоны (Мульти-провайдерные поля; v1: Stars)
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'telegram_stars', -- 'telegram_stars' | 'yookassa' | 'cryptobot'
    payment_id TEXT NOT NULL,                       -- charge_id / invoice_id
    telegram_payment_charge_id TEXT,                -- Алиас для совместимости со Stars
    provider_payment_charge_id TEXT,
    merchant_origin_bot_id TEXT NOT NULL DEFAULT '', -- Логическое имя процесса, принявшего платёж
    merchant_telegram_bot_id INTEGER NOT NULL DEFAULT 0, -- Фактический Telegram bot.id
    sku_code TEXT NOT NULL,                         -- Артикул из BotChassisConfig.skus
    amount INTEGER NOT NULL,                        -- Внимание: INTEGER minor-units (целые Stars, копейки RUB). Никаких REAL!
    currency TEXT NOT NULL DEFAULT 'XTR',           -- 'XTR', 'RUB', 'USDT'
    status TEXT NOT NULL DEFAULT 'paid',            -- 'paid' | 'refunded'
    voucher_id TEXT NOT NULL,                       -- Уникальный UUID талона
    voucher_status TEXT NOT NULL DEFAULT 'issued',  -- 'issued' | 'redeemed' | 'cancelled'
    redeemed_at TEXT,                               -- Дата погашения талона кузовом
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bot_id, provider, merchant_telegram_bot_id, payment_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_bot_user ON transactions(bot_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_voucher ON transactions(bot_id, voucher_id);

-- 4. Доступ и подарочные подписки (Access & Gift Grants)
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL DEFAULT 'default',
    is_lifetime INTEGER NOT NULL DEFAULT 0,    -- 1 = бессрочно (навсегда)
    expires_at TEXT,                           -- ISO-8601 дата истечения (NULL если бессрочно)
    granted_by INTEGER NOT NULL,               -- ID суперадмина
    grant_reason TEXT,                         -- Заметка ('gift', 'friend', 'promo')
    status TEXT NOT NULL DEFAULT 'active',     -- 'active' | 'revoked'
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((is_lifetime = 1 AND expires_at IS NULL) OR (is_lifetime = 0 AND expires_at IS NOT NULL)),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_subs_user_active ON subscriptions(bot_id, user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_one_active
    ON subscriptions(bot_id, user_id, plan_code) WHERE status = 'active';

-- 5. Треды поддержки (маршрутизация; текст и медиа не хранятся)
CREATE TABLE IF NOT EXISTS support_threads (
    bot_id TEXT NOT NULL,
    support_chat_id INTEGER NOT NULL,
    support_message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    origin_bot_id TEXT NOT NULL DEFAULT '',
    origin_telegram_bot_id INTEGER NOT NULL DEFAULT 0,
    ticket_id TEXT NOT NULL DEFAULT '',
    message_role TEXT NOT NULL DEFAULT 'header', -- 'header' | 'copy'
    ticket_status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'in_progress' | 'closed'
    message_thread_id INTEGER,
    operator_id INTEGER,
    first_answered_at TEXT,
    closed_at TEXT,
    user_full_name TEXT,
    user_username TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, support_chat_id, support_message_id),
    CHECK (ticket_status IN ('open', 'in_progress', 'closed')),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_support_user ON support_threads(bot_id, user_id, ticket_status);
CREATE INDEX IF NOT EXISTS idx_support_ticket ON support_threads(bot_id, ticket_id);

-- 5b. Метаданные сообщений тикета (без текста и медиа)
CREATE TABLE IF NOT EXISTS support_ticket_messages (
    bot_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    message_thread_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, telegram_chat_id, telegram_message_id),
    CHECK (direction IN ('user_to_support', 'support_to_user'))
);
CREATE INDEX IF NOT EXISTS idx_support_ticket_messages
    ON support_ticket_messages(bot_id, ticket_id);

-- 5c. Очередь отзывов (без текста и медиа)
CREATE TABLE IF NOT EXISTS review_submissions (
    bot_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    origin_bot_id TEXT NOT NULL DEFAULT '',
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    moderation_chat_id INTEGER,
    moderation_message_id INTEGER,
    published_chat_id INTEGER,
    published_message_id INTEGER,
    consent_to_publish INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    published_at TEXT,
    moderation_claim_token TEXT,
    moderation_claimed_at TEXT,
    PRIMARY KEY (bot_id, review_id),
    CHECK (status IN ('pending', 'published', 'rejected')),
    CHECK (consent_to_publish IN (0, 1)),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON review_submissions(bot_id, status);

-- 6. Системные настройки и флаги шасси (Рубильник)
CREATE TABLE IF NOT EXISTS bot_settings (
    bot_id TEXT NOT NULL PRIMARY KEY,
    is_maintenance INTEGER NOT NULL DEFAULT 0, -- 1 = рубильник опущен, приём задач остановлен
    maintenance_reason TEXT,                  -- Причина сервисного режима для пользователей
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Реферальные связи (1-уровневая виральная система)
CREATE TABLE IF NOT EXISTS referrals (
    bot_id TEXT NOT NULL,
    referrer_id INTEGER NOT NULL,            -- Кто пригласил
    referee_id INTEGER NOT NULL,             -- Кого пригласили
    rewarded INTEGER NOT NULL DEFAULT 0,     -- 1 = бонус выдан (аудит-флаг)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, referee_id),
    CHECK (referrer_id != referee_id),       -- Запрет реферала на самого себя
    FOREIGN KEY (bot_id, referrer_id) REFERENCES users(bot_id, user_id),
    FOREIGN KEY (bot_id, referee_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(bot_id, referrer_id);

-- 8. Telegram-статус пользователя в конкретном боте.
-- unknown в базу не пишется: это отсутствие ряда.
CREATE TABLE IF NOT EXISTS user_bot_statuses (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    origin_bot_id TEXT NOT NULL,
    telegram_bot_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status_changed_at TEXT NOT NULL,
    last_error_code TEXT,
    first_launch_notified_at TEXT,
    PRIMARY KEY (bot_id, user_id, telegram_bot_id),
    CHECK (status IN ('active', 'stopped', 'deleted')),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_bot_statuses_user
    ON user_bot_statuses(bot_id, user_id);

-- 9. Claim фоновых заданий сети (Gate 7 использует строки; книга Gate 6 уже выгружает таблицу)
CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    bot_id TEXT NOT NULL,
    job_key TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    claimed_by TEXT,
    started_at TEXT,
    completed_at TEXT,
    status TEXT,
    details TEXT,
    PRIMARY KEY (bot_id, job_key, scheduled_for)
);

-- 10. Неизменяемые операционные события для периодических отчётов рамы
CREATE TABLE IF NOT EXISTS chassis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    origin_bot_id TEXT NOT NULL DEFAULT '',
    telegram_bot_id INTEGER NOT NULL DEFAULT 0,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chassis_events_period
    ON chassis_events(bot_id, event_type, created_at);
