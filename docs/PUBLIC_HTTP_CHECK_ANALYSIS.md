# Analyse locale de PUBLIC_HTTP_CHECK_FAILED

Analyse du code local et des observations fournies, sans commande Git, accès VPS,
requête au domaine de production, déploiement ou modification de production.
Les tests remplacent les appels HTTP, les commandes de déploiement et les attentes.

## Contrôle exact

`scripts/simple_deploy.py` utilise la constante `PUBLIC`, sans substitution par une
variable d'environnement. Les requêtes sont des GET anonymes, dans cet ordre :

| URL exacte | Seul statut accepté | Validation supplémentaire |
| --- | --- | --- |
| `https://ai-policy.tewendelabs.com/` | 200 | Les premiers 1 000 000 octets doivent contenir `<app-root` |
| `https://ai-policy.tewendelabs.com/healthz` | 200 | Le corps, après suppression des espaces aux extrémités, doit être exactement `ok` |
| `https://ai-policy.tewendelabs.com/api/auth/me` | 401 | Pas de jeton ni cookie ; le refus anonyme confirme la protection de l'API |

Les trois contrôles sont obligatoires. Une tentative s'arrête au premier échec :
un échec de `/` peut empêcher toute vérification de `/healthz` et de l'API.
Un HTTPError 401 est explicitement traité comme un succès pour `/api/auth/me`.
Un 200 provenant du fallback Angular sur cette route reste un échec.
Les redirections, y compris sur le même hôte, sont refusées. Les certificats et
le nom d'hôte TLS restent vérifiés par la configuration HTTPS standard de Python.

`PUBLIC_HTTP_CHECK_FAILED` signifie exclusivement qu'un statut HTTP diffère du
statut attendu, sur l'une de ces trois URL. Une erreur de connexion ou TLS produit
`PUBLIC_TLS_OR_CONNECTION_FAILED`. Un contenu inattendu produit
`ANGULAR_APPLICATION_MISSING` ou `FRONTEND_HEALTH_BODY_INVALID`.
Le code historique ne conservait ni la route en échec ni le statut reçu.

## Délais : avant et après correction

| Paramètre | Avant | Après |
| --- | --- | --- |
| Timeout urllib par opération réseau bloquante | 5 s | 10 s |
| Précontrôle, avant pull et snapshot | 1 tentative, aucune reprise | Au plus 12 tentatives |
| Vérification après remplacement | Au plus 6 tentatives | Au plus 12 tentatives |
| Vérification pendant restauration | Au plus 6 tentatives | Au plus 12 tentatives |
| Pause entre échecs | 5 s | 5 s |
| Somme maximale des pauses par série | 0 s en précontrôle ; 25 s ensuite | 55 s |
| User-Agent | Python-urllib par défaut | `AI-Policy-Investigator-Deployment/1.0` |

Il n'y a aucune pause après un succès ni après la dernière tentative. Chaque
reprise recommence à `/`. Le dernier échec conserve son code d'origine.
Les 55 secondes sont des pauses, pas une limite globale de durée : les requêtes
prennent également du temps. Le timeout urllib concerne les opérations réseau
bloquantes, pas un chronomètre global pour toute la série.

Le User-Agent explicite reprend la correction déjà présente dans
`scripts/production_release.py:check_url`. Un filtrage du User-Agent Python à
l'entrée publique est une hypothèse cohérente avec le code et les observations,
mais les données fournies ne prouvent pas que le serveur a renvoyé un 403.
Un proxy temporairement indisponible ou une autre route en échec restent possibles.
Il n'y a pas de justification locale pour accepter un 403, une redirection ou un
200 sur l'API protégée : les attentes fonctionnelles sont conservées.

## Ordre d'exécution et dépendances

1. `check_topology()` exige que les conteneurs existants soient déjà running et
   healthy. Le précontrôle public teste donc la version existante, avant les pulls,
   le snapshot et le remplacement. Il est hors du bloc qui déclenche le rollback.
2. Les images sont téléchargées, puis les images et paramètres existants sont
   sauvegardés dans un snapshot et `previous.json`.
3. Le backend puis le frontend sont remplacés avec
   `compose up --wait --wait-timeout 240`, chacun séparément.
4. `verify()` exige que backend, frontend et PostgreSQL soient healthy, vérifie
   les identités des nouvelles images, puis exige `status=UP` sur le GET interne
   `http://127.0.0.1:8080/actuator/health` (curl, max-time 20 s).
5. La série de contrôles publics commence ensuite, en phase `verify`.

Le contrôle final n'est donc pas lancé avant la disponibilité interne déclarée
des services. Cette disponibilité ne prouve pas la disponibilité du chemin public.
Le frontend utilise `deploy/simple/compose.frontend.yaml` : son healthcheck local
vérifie seulement `/healthz` via wget sur `127.0.0.1:8080` (intervalle 10 s,
timeout 3 s, start_period 10 s, 6 échecs). Le backend utilise le contrôle de santé
de `deploy/simple/compose.images.yaml`, incluant les workers et la base
(intervalle 10 s, timeout 20 s, start_period 120 s, 12 échecs).

Le chemin public passe par le proxy existant vers `ai-policy-investigator-web:8080`,
puis, pour l'API, par le frontend vers
`http://backend.ai-policy-investigator_application:8080`. Un cache DNS ou une
transition du proxy peut encore affecter ce chemin après les contrôles internes.
La configuration effective du proxy sur le VPS n'a pas été consultée.

`simple_diagnostics.py` définit les événements autorisés et `simple_ssh.py` les
filtre avant affichage dans Actions. La correction ajoute des étapes fixes
`public.root`, `public.healthz`, `public.auth_me`, un statut HTTP numérique validé
et un numéro de tentative borné. La phase permet de distinguer précontrôle,
vérification et rollback. Aucun corps, en-tête, message d'exception ou URL libre
n'est transmis. Le timeout du transport SSH reste 1 800 s ; le job Actions reste
limité à 35 minutes. Une interruption de transport laisse l'issue distante inconnue.

Le workflow `deploy.yml` exécute les scripts du bundle CI téléchargé, plutôt que
de remplacer ceux-ci par les fichiers du checkout courant. Une future exécution
autorisée devra donc utiliser un nouvel artefact CI contenant la correction.

## Le rollback a-t-il été déclenché et terminé ?

Avec les seules observations fournies, ce n'est pas déterminable.

- Un échec du précontrôle produit directement `PUBLIC_HTTP_CHECK_FAILED`, sans
  pull, remplacement ni rollback. Les anciens tags restent alors naturellement
  en place. Si ce code est bien le **dernier code** des journaux complets et que
  le script exécuté correspond à cette version, ce scénario est celui du code.
- Un échec HTTP en phase `verify` déclenche `ROLLBACK_STARTED`, puis `restore()`.
  La restauration exige une histoire Flyway inchangée, restaure backend et
  frontend depuis les identifiants d'images du snapshot sans pull, attend leurs
  healthchecks, vérifie les images et les trois chemins publics, puis revérifie
  l'histoire Flyway. Le snapshot conserve les healthchecks historiques et met
  `worker_probe=False` : il n'impose pas le nouveau contrôle workers à une ancienne
  image. PostgreSQL n'est pas remplacé.
- Un rollback entièrement validé produit `ROLLBACK_SUCCEEDED`, puis le code final
  `DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED`. Le job demeure en échec.
- Une restauration ou sa vérification en échec produit `ROLLBACK_FAILED`, écrit
  `blocked.json` et termine par
  `DEPLOY_FAILED_ROLLBACK_FAILED_OR_BLOCKED_REVIEW_PRIVATE_STATE`. Les anciens tags
  peuvent déjà avoir été restaurés, malgré cet échec de validation.

Un `/healthz` à 200 mesuré après l'échec ne renseigne ni les deux autres routes,
ni leur réponse au moment du contrôle, ni l'issue du rollback. Les anciens tags
et les conteneurs healthy sont compatibles avec plusieurs scénarios ci-dessus.
Seuls les marqueurs et le code final du journal permettent de conclure ; aucun
journal de l'exécution distante n'a été fourni ou récupéré pour cette analyse.

## Régressions couvertes

Les tests `test_simple_public_http.py` couvrent les GET et le User-Agent explicites,
les statuts exacts sur les trois routes, les contenus, TLS et les redirections,
la fermeture des réponses HTTPError, la reprise après erreur réseau ou HTTP,
le redémarrage complet de la série et l'arrêt après succès. Ils exercent également
le précontrôle sans mutation, la vérification après readiness interne, la vraie
logique de restauration avec commandes simulées, le rollback réussi ou bloqué et
le filtrage des nouveaux diagnostics à travers la couche SSH simulée.

La commande CI locale pour ces tests est :

```sh
python3 -B -m unittest discover -s scripts/tests -p 'test_simple_*.py' -v
```

Résultat local : **68 tests réussis**, dont 15 nouveaux tests. Les 7 tests de
`test_public_routing.py`, relatifs à l'ancien outil et à son User-Agent explicite,
ont également été exécutés avec succès : **75 tests réussis au total**.
