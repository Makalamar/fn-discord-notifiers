# Option A - Obtenir un token avec droits CloudStorage via Exchange Code

## Étape 1 : Générer un exchange_code avec Legendary

Puisque tu es déjà authentifié avec Legendary, la commande la plus simple est :

```bash
legendary auth --code
```

Cette commande va :
- Ouvrir ton navigateur (ou te donner un lien)
- Générer un exchange_code frais lié à ton compte

**Important** : L'exchange_code est valable seulement quelques minutes. Copie-le immédiatement.

Si la commande `--code` n'existe pas dans ta version, essaie :

```bash
legendary auth
```

Puis suis les instructions pour générer un code.

---

## Étape 2 : Échanger le code avec le PC Game Client

Une fois que tu as l'exchange_code, utilise le script `exchange_code_to_token.py` que j'ai créé :

```bash
python3 exchange_code_to_token.py
```

Colle le code quand il te le demande.

Ce script utilise le `fortnitePCGameClient`, qui est celui qui a normalement les meilleurs droits sur CloudStorage système.

---

## Étape 3 : Tester le token

Si tu obtiens un nouveau refresh_token ou access_token, on le testera immédiatement sur :

- La liste des fichiers CloudStorage système
- Les fichiers spécifiques (DefaultEngine.ini, etc.)

Si on arrive à lister sans 403 → on a gagné. On pourra alors utiliser ce token (ou son refresh) dans le notifier.

---

## Si ça ne marche toujours pas

On passera à l'Option B (clients plus internes / flux avancés).

Dis-moi ce que Legendary te donne comme code, et on enchaîne.
