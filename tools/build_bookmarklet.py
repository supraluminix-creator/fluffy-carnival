# ruff: noqa: E501

import argparse
import base64
import pathlib
import platform
import subprocess
import sys
import urllib.parse
import webbrowser


def _prepare_js(js_text: str, *, compact: bool = False) -> str:
    # Retrait basique de commentaires bloc/ligne et espaces inutiles (naïf mais suffisant)
    import re

    # Supprimer commentaires /* ... */
    js_text = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", js_text)
    # Supprimer commentaires // ... fin de ligne
    js_text = re.sub(r"(^|\s)//.*$", "", js_text, flags=re.MULTILINE)
    # Condenser espaces
    js_text = re.sub(r"\s+", " ", js_text).strip()

    if compact:
        # Minification prudente des espaces autour de (){}[],:; sans toucher aux chaînes
        punct = set("(){}[],:;")
        out = []
        in_str = None  # type: ignore[assignment]
        esc = False
        i = 0
        n = len(js_text)
        while i < n:
            ch = js_text[i]
            if in_str:
                out.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
                i += 1
                continue
            if ch in ('"', "'", "`"):
                in_str = ch
                out.append(ch)
                i += 1
                continue
            if ch in punct:
                if out and out[-1] == " ":
                    out.pop()
                out.append(ch)
                j = i + 1
                while j < n and js_text[j] == " ":
                    j += 1
                i = j
                continue
            if ch == " ":
                if not out or out[-1] == " ":
                    i += 1
                    continue
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            i += 1
        js_text = "".join(out)
    return js_text


def to_bookmarklet(js_text: str, *, compact: bool = False) -> str:
    js_min = _prepare_js(js_text, compact=compact)
    return "javascript:" + urllib.parse.quote(js_min, safe="~()*!.'")


def to_bookmarklet_packed(js_text: str, *, compact: bool = False) -> str:
    js_min = _prepare_js(js_text, compact=compact)
    b64 = base64.b64encode(js_min.encode("utf-8")).decode("ascii")
    wrapper = f"(function(){{eval(atob('{b64}'))}})()"
    return "javascript:" + urllib.parse.quote(wrapper, safe="~()*!.'")


def _copy_to_clipboard(text: str) -> bool:
    """Copie le texte dans le presse-papiers si possible (Windows/macOS/Linux)."""
    try:
        system = platform.system().lower()
        if "windows" in system:
            # Utilitaire 'clip' intégré
            subprocess.run(["clip"], input=text.encode("utf-8"), check=True)
            return True
        if "darwin" in system:
            # macOS
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        # Linux: essayer xclip, sinon xsel
        try:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)
            return True
        except Exception:
            subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True)
            return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Génère le bookmarklet inject_prompt encodé.")
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Chemin de sortie (par défaut: bookmarklets/inject_prompt.bookmarklet.txt)",
    )
    parser.add_argument("--clip", action="store_true", help="Copier le bookmarklet dans le presse-papiers")
    parser.add_argument(
        "--compact", action="store_true", help="Réduire davantage la taille (minification prudente des espaces)"
    )
    parser.add_argument(
        "--pack",
        action="store_true",
        help="Encoder le JS en base64 et l'exécuter via eval(atob(...)) (peut contourner l'URL encoding coûteux, mais peut être bloqué par certaines CSP)",
    )
    parser.add_argument(
        "--auto-pack",
        action="store_true",
        help="Si la version encodée dépasse ~4000 caractères, génère aussi une variante packée (.packed) et la privilégie pour le presse-papiers",
    )
    parser.add_argument(
        "--use-mapping",
        action="store_true",
        help="Générer un snippet console pour charger window.__PRODSAFE_SITE_MAP à partir de bookmarklets/mapping_selectors.json",
    )
    parser.add_argument(
        "--page", type=str, default=None, help="Chemin d'une page HTML à générer avec liens bookmarklet (plain/packed)"
    )
    parser.add_argument(
        "--open-page", action="store_true", help="Ouvrir la page HTML générée dans le navigateur par défaut"
    )
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    js_path = repo_root / "bookmarklets" / "inject_prompt.js"
    out_path = pathlib.Path(args.out) if args.out else (repo_root / "bookmarklets" / "inject_prompt.bookmarklet.txt")
    try:
        text = js_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"File not found: {js_path}")
        return 1
    if args.use_mapping:
        mapping_path = repo_root / "bookmarklets" / "mapping_selectors.json"
        try:
            mapping_json = mapping_path.read_text(encoding="utf-8")
            snippet = (
                "// Exécuter ceci dans la console avant le bookmarklet (ou coller en tant que favori séparé)\n"
                "window.__PRODSAFE_SITE_MAP = " + mapping_json + ";\n"
                "console.log('PRODSAFE: site mapping chargé', window.__PRODSAFE_SITE_MAP);\n"
            )
            map_out = repo_root / "bookmarklets" / "load_site_mapping.console.txt"
            map_out.write_text(snippet, encoding="utf-8")
            print(f"Snippet mapping écrit dans: {map_out}")
        except Exception as e:
            print(f"Impossible de charger le mapping: {e}")

    if args.pack:
        bm_plain = to_bookmarklet(text, compact=args.compact)
        bm = to_bookmarklet_packed(text, compact=args.compact)
        out_path.write_text(bm, encoding="utf-8")
        print(f"Bookmarklet généré: {out_path}")
        try:
            delta = len(bm_plain) - len(bm)
            pct = (delta / max(1, len(bm_plain))) * 100.0
            print(f"Taille encodée (pack): {len(bm)} caractères (non pack: {len(bm_plain)}, gain ~{pct:.1f}%)")
        except Exception:
            pass
        if args.page:
            html = f"""<!DOCTYPE html><html lang=fr><meta charset=utf-8><title>Bookmarklet PRODSAFE</title><style>body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;line-height:1.5;padding:24px;max-width:860px;margin:auto}} a.btn{{display:inline-block;margin:8px 0;padding:8px 12px;background:#7c3aed;color:#fff;text-decoration:none;border-radius:6px}} code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}} .hint{{background:#eef2ff;padding:12px;border-left:4px solid #7c3aed;border-radius:6px;margin:10px 0}} textarea,.cedit{{width:100%;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:6px;padding:10px;font:inherit}} .cedit{{min-height:100px}} h2{{margin-top:24px}}</style><h1>Bookmarklet PRODSAFE</h1><div class=hint><strong>Important:</strong> ajoutez d'abord un lien à vos favoris, puis utilisez-le sur la page cible (ChatGPT, Claude, Gemini, Perplexity, etc.). Vous pouvez tester ici dans la zone ci‑dessous. Si un message indique « Zone de saisie introuvable », cliquez dans la zone de test, puis relancez ou utilisez <code>/sel:textarea</code>.</div><p>Faites glisser un lien vers votre barre de favoris :</p><p><a class=btn href="{bm_plain}">Bookmarklet (plain)</a></p><p><a class=btn href="{bm}">Bookmarklet (packed)</a></p><h2>Zone de test (textarea)</h2><textarea aria-label="message" placeholder="Zone de test…"></textarea><h2>Zone de test (contentEditable)</h2><div class="cedit" contenteditable="true" role="textbox" aria-multiline="true" aria-label="message" placeholder="Zone de test…"></div><hr><p>Taille plain: <code>{len(bm_plain)}</code> | Taille packed: <code>{len(bm)}</code></p></html>"""
            pathlib.Path(args.page).write_text(html, encoding="utf-8")
            print(f"Page HTML générée: {args.page}")
            if args.open_page:
                from contextlib import suppress
                with suppress(Exception):
                    webbrowser.open_new_tab(str(pathlib.Path(args.page).resolve().as_uri()))
    else:
        bm_plain = to_bookmarklet(text, compact=args.compact)
        out_path.write_text(bm_plain, encoding="utf-8")
        print(f"Bookmarklet généré: {out_path}")
        print(f"Taille encodée: {len(bm_plain)} caractères")

        bm_for_clip = bm_plain
        if args.auto_pack and len(bm_plain) > 4000:
            # Générer aussi la version packée
            bm_packed = to_bookmarklet_packed(text, compact=args.compact)
            packed_out = out_path.with_name(out_path.stem + ".packed" + out_path.suffix)
            packed_out.write_text(bm_packed, encoding="utf-8")
            try:
                delta = len(bm_plain) - len(bm_packed)
                pct = (delta / max(1, len(bm_plain))) * 100.0
                print(f"Auto-pack: fichier packé généré: {packed_out}")
                print(
                    f"Taille encodée (pack): {len(bm_packed)} caractères (non pack: {len(bm_plain)}, gain ~{pct:.1f}%)"
                )
            except Exception:
                print(f"Auto-pack: fichier packé généré: {packed_out}")
                print(f"Taille encodée (pack): {len(bm_packed)} caractères")
            bm_for_clip = bm_packed
            if args.page:
                html = f"""<!DOCTYPE html><html lang=fr><meta charset=utf-8><title>Bookmarklet PRODSAFE</title><style>body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;line-height:1.5;padding:24px;max-width:860px;margin:auto}} a.btn{{display:inline-block;margin:8px 0;padding:8px 12px;background:#7c3aed;color:#fff;text-decoration:none;border-radius:6px}} code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}} .hint{{background:#eef2ff;padding:12px;border-left:4px solid #7c3aed;border-radius:6px;margin:10px 0}} textarea,.cedit{{width:100%;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:6px;padding:10px;font:inherit}} .cedit{{min-height:100px}} h2{{margin-top:24px}}</style><h1>Bookmarklet PRODSAFE</h1><div class=hint><strong>Important:</strong> ajoutez d'abord un lien à vos favoris, puis utilisez-le sur la page cible (ChatGPT, Claude, Gemini, Perplexity, etc.). Vous pouvez tester ici dans la zone ci‑dessous. Si un message indique « Zone de saisie introuvable », cliquez dans la zone de test, puis relancez ou utilisez <code>/sel:textarea</code>.</div><p>Faites glisser un lien vers votre barre de favoris :</p><p><a class=btn href="{bm_plain}">Bookmarklet (plain)</a></p><p><a class=btn href="{bm_packed}">Bookmarklet (packed)</a></p><h2>Zone de test (textarea)</h2><textarea aria-label="message" placeholder="Zone de test…"></textarea><h2>Zone de test (contentEditable)</h2><div class="cedit" contenteditable="true" role="textbox" aria-multiline="true" aria-label="message" placeholder="Zone de test…"></div><hr><p>Taille plain: <code>{len(bm_plain)}</code> | Taille packed: <code>{len(bm_packed)}</code></p></html>"""
                pathlib.Path(args.page).write_text(html, encoding="utf-8")
                print(f"Page HTML générée: {args.page}")
                if args.open_page:
                    from contextlib import suppress
                    with suppress(Exception):
                        webbrowser.open_new_tab(str(pathlib.Path(args.page).resolve().as_uri()))

        # Avertissements de longueur (sur la version principale)
        if len(bm_plain) > 4000:
            print("Avertissement: la longueur du bookmarklet dépasse 4000 caractères. ")
            print("Certains navigateurs/anciens favoris peuvent tronquer des URLs très longues.")

        if args.clip:
            if _copy_to_clipboard(bm_for_clip):
                print("Bookmarklet copié dans le presse-papiers.")
            else:
                print("Copie dans le presse-papiers non disponible sur ce système.")
    print("Astuce: copiez toute la ligne dans l'URL d'un favori.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
