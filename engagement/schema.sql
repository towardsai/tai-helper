CREATE TABLE IF NOT EXISTS daily_visitors (
    day TEXT NOT NULL,
    surface TEXT NOT NULL,
    visitor TEXT NOT NULL,
    stage INTEGER NOT NULL CHECK (stage BETWEEN 1 AND 3),
    PRIMARY KEY (day, surface, visitor)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS coverage (
    surface TEXT PRIMARY KEY,
    started_at TEXT NOT NULL
);
