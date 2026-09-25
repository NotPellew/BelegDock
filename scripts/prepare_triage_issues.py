import json
import sys
from pathlib import Path


def wrapped_body(body: str) -> str:
    lines = []
    for original_line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.extend(original_line[start : start + 160] for start in range(0, len(original_line), 160))
        if not original_line:
            lines.append("")
    return "\n".join(lines)


def main(source: Path, output: Path) -> None:
    issues = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(issues, list):
        raise ValueError("Expected a list of open issues")
    output.mkdir()
    names = []
    for issue in issues:
        number = issue["number"]
        if not isinstance(number, int) or number < 1:
            raise ValueError("Invalid issue number")
        name = f"issue-{number}.md"
        if name in names:
            raise ValueError(f"Duplicate issue number: {number}")
        names.append(name)
        title = issue["title"].replace("\n", " ").replace("\r", " ")
        labels = ", ".join(label["name"] for label in issue["labels"])
        content = (
            f"# Issue #{number}\n"
            f"Title: {title}\n"
            f"URL: {issue['url']}\n"
            f"Updated: {issue['updatedAt']}\n"
            f"Labels: {labels}\n\n"
            f"## Body\n{wrapped_body(issue['body'] or '')}\n"
        )
        (output / name).write_text(content, encoding="utf-8")
    (output / "INDEX.md").write_text("# Open issue files\n\n" + "\n".join(names) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
