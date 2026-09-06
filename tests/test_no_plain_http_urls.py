import ast
import pathlib


def iter_string_literals_excluding_docstrings(py_path: pathlib.Path):
    """
    Yield all string literal nodes (values) from a Python file, excluding module/class/function docstrings.
    """
    src = py_path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError:
        # If file can't be parsed, skip it (tests should catch syntax errors elsewhere)
        return

    # Collect docstring nodes to exclude (module, classes, functions)
    docstring_nodes = set()

    def mark_docstring(node):
        if getattr(node, "body", None):
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_nodes.add(first.value)

    mark_docstring(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            mark_docstring(n)

    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n in docstring_nodes:
                continue
            yield n.value


def test_no_literal_http_urls_in_pipeline():
    root = pathlib.Path(__file__).resolve().parents[1]
    pipeline_dir = root / "pipeline"
    assert pipeline_dir.is_dir(), f"Missing pipeline dir at {pipeline_dir}"

    offenders = []
    for py in pipeline_dir.rglob("*.py"):
        # Skip tests or generated files inside pipeline if any
        if "__pycache__" in str(py):
            continue
        for s in iter_string_literals_excluding_docstrings(py):
            # Detect plain http scheme at string start or after whitespace
            if "http://" in s:
                # Allow localhost-only URLs for development if explicitly marked
                if s.strip().startswith("http://localhost") or s.strip().startswith("http://127.0.0.1"):
                    continue
                offenders.append((str(py), s))

    assert not offenders, (
        "Literal 'http://' URLs detected in pipeline code (use https or build URL dynamically).\n"
        + "\n".join(f"{p}: {val!r}" for p, val in offenders)
    )
