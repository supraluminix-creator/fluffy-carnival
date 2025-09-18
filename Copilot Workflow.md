# 🚀 GitHub Copilot Workflow – ProdSafe Methodology

## 🎯 Objectif
Garantir que **GPT-5** et **Copilot Agent** soient utilisés ensemble de manière **autonome, performante et sécurisée** dans VS Code pour toutes les évolutions du projet.

- **GPT-5** → moteur d’écriture, refactor et tests du code.  
- **Copilot Agent** → orchestrateur GitHub (branches, commits, Pull Requests, issues).  

---

## 📐 Méthodologie : ProdSafe

### 1. Exploration
- Analyser le besoin ou la modification à apporter.  
- Produire un plan clair et documenté avant toute modification de code.  

### 2. Implémentation
- Créer une **branche dédiée** (`feature/<sujet>`).  
- Implémenter les changements par **commits atomiques et cohérents**.  
- Respecter les bonnes pratiques (lisibilité, modularité, robustesse).  

### 3. Validation
- Résumer les impacts de la modification.  
- Générer ou adapter des **tests unitaires et/ou d’intégration**.  
- Vérifier compatibilité, logs et monitoring.  

### 4. Pull Request
- Ouvrir une **Pull Request** vers `main` avec :  
  - un **résumé clair des changements**,  
  - la **justification** (perf, sécurité, refactor, etc.),  
  - une **checklist de revue** pour faciliter la validation.  

---

## ⚙️ Instructions pratiques dans VS Code

- Toujours exécuter les commandes via **Copilot Chat** avec :  
  - **@workspace** → pour gérer le code localement (analyse, création de branches, commits).  
  - **@github** → pour gérer le dépôt distant (PR, issues).  

- Exemple de séquence (sans préciser de tâche ici) :  
  1. `@workspace analyse le repo et propose un plan clair`  
  2. `@workspace crée une branche feature/<sujet>`  
  3. `@workspace implémente les changements par commits propres`  
  4. `@workspace valide les tests et compatibilités`  
  5. `@github ouvre une Pull Request vers main`  

---

## ✅ Règle d’or
**Toujours appliquer cette méthodologie ProdSafe** pour toute contribution :  
➡️ Cela garantit que **GPT-5 écrit le code** et que **Copilot Agent orchestre GitHub** de manière **autonome, performante et sécurisée**.  
