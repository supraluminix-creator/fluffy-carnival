# Local Typings / Stubs

This directory hosts local type stubs (``.pyi``) or light-weight typed shims that are **not** provided by upstream libraries or third-party types distributions.

## Goals
- Allow enabling stricter mypy settings (`disallow_untyped_defs`, eventually reducing `ignore_missing_imports`) without being blocked by missing annotations in third-party deps.
- Keep the public surface area we *actually use* small, to minimize maintenance.
- Provide a documented, discoverable place for future contributors to extend stub coverage safely.

## Layout & Configuration
- All stub packages live under `typings/` mirroring their import name, e.g. `typings/diskcache/__init__.pyi` for `import diskcache`.
- `pyproject.toml` sets `mypy_path = ["typings"]` and `namespace_packages = true` so mypy finds these first.
- Prefer a single `__init__.pyi` unless you need deeper module structure.

## Conventions
1. **Only stub what we use**: Expose the minimal set of classes / functions actually referenced in our code.
2. **Concrete over Protocol unless needed**: A small concrete class (as with `diskcache.Cache`) can be simpler than designing a Protocol—avoid over-abstraction early.
3. **Runtime Compatibility**: Avoid generics that the real runtime object does not support (e.g. *do not* write `Cache[str, Any]` if the library class is non-generic at runtime) to prevent `TypeError: 'Cache' object is not subscriptable`.
4. **Mark TODOs for partial coverage**: If you intentionally omit parts of an API, add a `# TODO: extend if needed` comment.
5. **No behavior, only signatures**: Stubs should not implement logic—return `...` (ellipsis) in function bodies for clarity when using `.pyi`.
6. **Prefer external stub packages first**: Before adding a local stub, search for maintained `types-<pkg>` (e.g. `types-requests`, `types-PyYAML`). Local stubs are a last resort.

## Workflow for Adding a New Stub
1. Run a temporary mypy audit config (example: `mypy_audit.ini`) with `ignore_missing_imports = false` scoped to the module you want to tighten.
2. Identify missing third-party types that block you.
3. Check PyPI / `typeshed` for existing stubs. If found, add to `requirements.txt`.
4. If none exist, create `typings/<package>/__init__.pyi` (and submodules if required) with just the members we touch.
5. Re-run mypy and iterate until clean.
6. Add a brief note here if the stub has caveats.

## Example: diskcache
We rely on a tiny subset of `diskcache.Cache` (constructor, `get`, `set`). The upstream package lacks type hints and there is no `types-diskcache` on PyPI, so we introduced:

```
# typings/diskcache/__init__.pyi
class Cache:
    def __init__(self, directory: str = ..., timeout: float | None = ...) -> None: ...
    def get(self, key: str, default: object | None = ...) -> object | None: ...
    def set(self, key: str, value: object, expire: int | float | None = ...) -> bool: ...
```

If we later need eviction, iteration, or other advanced features, we can extend this stub incrementally.

## Roadmap Towards Reducing `ignore_missing_imports`
We apply stricter import checking one module at a time by adding an override with `ignore_missing_imports = false`. Once all critical collectors are clean (and their third-party edges stubbed), we can consider flipping the global default.

| Phase | Action | Scope |
|-------|--------|-------|
| 1 | Local stubs + strict per-module overrides | `scheduler.*`, `api.*`, `defillama`, `txcount`, `hashrate` |
| 2 | Extend strict set | Additional collectors (e.g. `altme`, others) |
| 3 | Turn off global `ignore_missing_imports` | Entire pipeline |

## When NOT to Add a Stub
- The library already distributes type hints (`py.typed` present).
- A typeshed / `types-` wheel exists (add dependency instead).
- The code path is experimental / likely to be removed soon.

## Questions / Extensions
Open a small PR expanding the stub with a one-line justification in the PR description. Keep diffs tight; avoid drive-by unrelated refactors in the same commit.
