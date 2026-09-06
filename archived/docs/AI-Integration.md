# Intégration AI – Rôles, Clés, Limites

- Pré-processing & validation: LLaMA local, petit Claude (local/cheap) – pas de clé pour local.
- Anomalies & triage: Gemini / Claude – API keys nécessaires.
- Synthèse: ChatGPT / Gemini – API keys nécessaires.
- Recherche/exploration: Perplexity / Deepseek – API keys nécessaires.

Clés requises (si utilisées):
- OpenAI: OPENAI_API_KEY
- Google Gemini: GOOGLE_API_KEY
- Anthropic (Claude): ANTHROPIC_API_KEY
- Perplexity: PERPLEXITY_API_KEY
- Deepseek: DEEPSEEK_API_KEY

Limites free (indicatif; vérifier dans les docs):
- Messari AI: 2 req/j (AI endpoints)
- Twelve Data: ≈800/j
- Alpha Vantage: ≈25/j

Politique d’appels: batching, rate-limit centralisé, prompts courts, fréquence contrôlée, fallback sur modèle local si erreurs/quotas.