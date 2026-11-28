"""Generate the idempotent D1 seed SQL from the reviewed public knowledge records."""
import json
from pathlib import Path

data = json.loads(Path(__file__).with_name("academy_guidance.json").read_text())
content = json.dumps(data, ensure_ascii=False).replace("'", "''")
print("CREATE TABLE IF NOT EXISTS guides (id TEXT PRIMARY KEY, content TEXT NOT NULL);")
print(f"INSERT INTO guides VALUES ('academy', '{content}') ON CONFLICT(id) DO UPDATE SET content=excluded.content;")
