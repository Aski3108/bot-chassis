-- 1. Пользователи (хранение профиля, UTM/трафика и отметки 152-ФЗ)
CREATE TABLE IF NOT EXISTS users (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT NOT NULL DEFAULT 'ru',
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    is_shadow_banned INTEGER NOT NULL DEFAULT 0, -- 1 = тихий сброс спамера (подтверждено архитектором)
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
    sku_code TEXT NOT NULL,                         -- Артикул из BotChassisConfig.skus
    amount INTEGER NOT NULL,                        -- Внимание: INTEGER minor-units (целые Stars, копейки RUB). Никаких REAL!
    currency TEXT NOT NULL DEFAULT 'XTR',           -- 'XTR', 'RUB', 'USDT'
    status TEXT NOT NULL DEFAULT 'paid',            -- 'paid' | 'refunded'
    voucher_id TEXT NOT NULL,                       -- Уникальный UUID талона
    voucher_status TEXT NOT NULL DEFAULT 'issued',  -- 'issued' | 'redeemed' | 'cancelled'
    redeemed_at TEXT,                               -- Дата погашения талона кузовом
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bot_id, provider, payment_id),
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

-- 5. Треды поддержки (схема готова, миграция с JSON позже)
CREATE TABLE IF NOT EXISTS support_threads (
    bot_id TEXT NOT NULL,
    support_chat_id INTEGER NOT NULL,
    support_message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ticket_status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'answered' | 'closed'
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, support_chat_id, support_message_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_support_user ON support_threads(bot_id, user_id, ticket_status);

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
