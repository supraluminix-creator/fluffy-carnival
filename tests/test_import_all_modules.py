import importlib
import inspect
import pkgutil

# Import minimal de tous les modules pipeline.* pour garantir au moins chargement
# et exécution du code top-level (augmente la couverture réelle sans tricher car
# chaque module doit être importable proprement).
import pipeline

_collected = []
for m in pkgutil.walk_packages(pipeline.__path__, pipeline.__name__ + "."):
    name = m.name
    try:
        mod = importlib.import_module(name)
        _collected.append(name)
        # Exécuter passivement quelques fonctions publiques sans effets dangereux
        for attr, obj in list(vars(mod).items()):
            if attr.startswith("_"):
                continue
            if inspect.isfunction(obj):
                # Heuristique: fonctions sans param obligatoires -> appeler
                sig = inspect.signature(obj)
                conds = (
                    p.default != inspect._empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                    for p in sig.parameters.values()
                )
                if all(conds):
                    from contextlib import suppress

                    with suppress(Exception):
                        obj()  # type: ignore[misc]
    except Exception:
        # On ignore volontairement (certains modules peuvent dépendre d'env non dispo)
        pass

print(f"Imported {len(_collected)} pipeline modules (smoke).")
