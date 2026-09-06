# Mode IA manuel — Prompts & Bookmarklets

Objectif: exploiter les quotas gratuits en mode manuel, sans consommer vos clés via API.

## 1) Générer un prompt Markdown

Python:

```python
from prompts.generator import generate_template
print(generate_template("ta","analyst", {"max_tokens": 600}))
```

## 2) Lancer l'UI et coller le prompt

- Ouvrez `tools/prompt-launcher.html` dans votre navigateur.
- Collez votre prompt Markdown dans la zone, cliquez « Copier », puis ouvrez l'UI (ChatGPT, Poe, Gemini, OpenRouter) et collez (Ctrl/Cmd+V).

Option bookmarklet (limité):

- Voir `tools/bookmarklets.json` pour des snippets JavaScript. Les UIs évoluent — privilégiez le copier/coller simple.

## 3) Fallback IA côté serveur (optionnel)

Si vous avez des clés et un serveur local, configurez explicitement :

| Variable | Requis | Rôle | Exemple |
| --- | --- | --- | --- |
| `OLLAMA_HOST` | Non | Point d'accès Ollama local (HTTP). Utilisé en priorité si disponible. | `http://127.0.0.1:11434` |
| `OPENROUTER_API_KEY` | Non | Clé OpenRouter si vous utilisez leurs modèles. | `sk-or-xxxx` |
| `HUGGINGFACE_API_KEY` | Non | Jeton HuggingFace Inference pour le fallback. | `hf_xxxxxxxxx` |
| `AI_PRIMARY` | Non | Force le fournisseur par défaut (`openrouter` ou `huggingface`). | `openrouter` |
| `AI_CACHE_TTL` | Non | TTL (secondes) du cache disque des réponses. | `900` |
| `AI_TIMEOUT` | Non | Timeout HTTP global en secondes. | `30` |

Code:

```python
import asyncio
from integrations.ai_provider import AIClient

async def main():
    client = AIClient()
    res = await client.generate("# TL;DR\n- Points clés")
    print(res)

asyncio.run(main())
```

## Sécurité

- Ne mettez jamais vos clés dans le code ou dans Git; utilisez des variables d'environnement.
- Masquez/obfusquez les clés dans les logs.
