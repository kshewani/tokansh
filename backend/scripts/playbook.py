"""Parser for sql/dml_playbook.sql, shared by the test and the reference generator."""
import re
from pathlib import Path

PLAYBOOK = Path(__file__).resolve().parent.parent / "sql" / "dml_playbook.sql"
PARAM = re.compile(r"(?<![:\w]):([a-z_][a-z0-9_]*)")


def load(path: Path = PLAYBOOK) -> list[dict]:
    """Return steps: [{"title", "items": [("note", text) | ("sql", statement)]}]."""
    steps, buf = [], []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("-- ## "):
            steps.append({"title": line[6:], "items": []})
        elif not steps:
            continue  # file header
        elif line.startswith("--"):
            steps[-1]["items"].append(("note", line[2:].strip()))
        elif line:
            buf.append(line)
            if line.endswith(";"):
                steps[-1]["items"].append(("sql", "\n".join(buf)))
                buf = []
    if buf:
        raise ValueError("unterminated statement at end of playbook")
    return steps


def statements(steps: list[dict]) -> list[str]:
    return [text for s in steps for kind, text in s["items"] if kind == "sql"]


def params(sql: str) -> set[str]:
    return set(PARAM.findall(re.sub(r"'[^']*'", "''", sql)))
