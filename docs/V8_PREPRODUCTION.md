# Qualification préproduction V7 → V8 — 30 octobre 2026

**Verdict réévalué : GO pour la qualification locale V7 → V8, selon l'option A
explicitement confirmée par le propriétaire du projet.** Les juges peuvent écrire
et importer dans leur département privé. Les documents synthétiques partagés depuis
les autres départements restent strictement en READ, sans modification autorisée.
La création d'investigations sur ces sources reste permise et soumise aux quotas ;
elle ne confère pas WRITE sur les documents.

Le précédent NO-GO provenait uniquement d'une interprétation interdisant également
l'écriture privée. La décision explicite lève ce point ; aucun changement de code,
de migration ou d'artefact n'est nécessaire. Ce GO porte sur l'artefact local qualifié,
pas sur une validation du VPS ni une autorisation de déploiement. Les conditions
opérateur du plan ci-dessous restent à satisfaire avant toute livraison.

Aucun code applicatif ni aucune migration n'ont été modifiés. Aucune commande Git,
connexion VPS/production, livraison ou requête vers les services Meta réels n'a été
effectuée. Les identifiants utilisés sont générés pour des conteneurs jetables et
ne sont pas inclus dans les preuves. Les données sont exclusivement synthétiques.

## Réévaluation selon l'option A

Les preuves existantes ont été réutilisées, sans relancer de tests : les empreintes
des **15 rapports Surefire**, leurs nombres de tests et leurs résultats correspondent
à `v8-qualification.json` (**172 tests Java**, zéro échec/erreur/test ignoré).
Le JAR et les huit migrations correspondent toujours aux SHA-256 archivés dans
`v8-artifact.json`. Les **173 tests Python** réussis de la qualification sont
conservés comme preuve existante. Aucun manque de preuve n'a été identifié.

| Exigence confirmée | Assertions des tests existants réussis |
| --- | --- |
| READ partagé sans WRITE | `judgeReadonlySharedScopeRunsWithAdmissionAndMetaReservationsButWithoutContentWrite` vérifie `can_write_policy=false`, UPDATE policy/version sans ligne modifiée, refus d'ajout de page, de PDF et d'ingestion. `judgeProvisioningPreservesCompletedScenarioAndProvidesOnlyPrivateWriteAndTargetedRead` refuse aussi consentement et revue ; même une appartenance ADMIN supplémentaire et un grant WRITE accidentel ne rendent pas la policy partagée modifiable. |
| Écriture privée autorisée et isolée | Le test de provisioning crée, ingère et versionne un PDF privé, puis termine son investigation. Un second juge ne peut lire ni sa policy, ni son PDF, ni ses preuves, ni son job, ni ses extractions/résultats/graphe. `jdbcJpaAndConnectionReuseDenyOtherDepartment` et `jpaWritesCannotCrossDepartmentBoundary` couvrent aussi l'isolation en JDBC/JPA. |
| Sources non autorisées et révocation | `judgeReadonlyRejectsHiddenScopesEvenThroughDefinerScheduling` refuse les sources cachées, l'organisation incorrecte et l'absence de membership, y compris via planification DEFINER. `judgeReadonlyRevocationStopsReservationsAndAsyncPersistence` et le test de migration couvrent le retrait de droits avant et pendant le traitement. |
| Quotas et budgets Meta protégés | `judgeReadonlyConcurrentSqlAdmissionsKeepQuotaReservations`, `demoMetaIndividualBudgetIsAtomicAndInvalidLeaseDoesNotDebit` et `demoCollectiveMetaBudgetIsAtomicAcrossDifferentJudges` démontrent les limites concurrentes. Les cas d'épuisement et de retry empêchent un appel supplémentaire ; `demoReservationRollsBackWithItsWorkAndRuntimeCannotAlterLimits` refuse l'accès direct runtime aux limites. |
| RLS et droits ordinaires conservés | `judgeAnalysisDefinerIsRestrictedAndUnsafeOwnershipBlocksStartup` et `effectiveRolesFunctionAclsAndForcedRlsAreSafe` vérifient DEFINER/INVOKER, ACL, FORCE RLS et propriétaires NOBYPASSRLS. `ordinaryReadersStillNeedWritePermissionToAnalyze` conserve la distinction READ/WRITE des comptes ordinaires ; `explicitGrantWorksAndRevocationTakesEffectForJpaAndSql` vérifie octroi et révocation. |

Les cas et résultats archivés figurent dans
[v8-qualification.json](verification/v8-qualification.json), avec les motifs de
réévaluation et les conditions restantes. Les assertions sont consultables dans
[SecurityDatabaseTest](../src/test/java/com/tewendelabs/investigator/SecurityDatabaseTest.java)
et [V8MigrationDatabaseTest](../src/test/java/com/tewendelabs/investigator/V8MigrationDatabaseTest.java).
Cette réévaluation modifie seulement le présent rapport et `v8-qualification.json` ;
`v8-artifact.json`, les tests, le code applicatif et les migrations sont inchangés.

## Résultats et preuves

Environnement : Java 21, PostgreSQL **16.10**, image `pgvector/pgvector:0.8.0-pg16`.
Les migrations sont exécutées avec le login `investigator_owner`, les opérations
applicatives avec le login `investigator_app`, membre de `investigator_runtime`.
Le superutilisateur ne sert qu'à créer les rôles/extensions, préparer des données,
observer les assertions et injecter les anomalies de test.

| Vérification | Résultat et preuve |
| --- | --- |
| Régression existante | **166 tests Java**, dont **93** dans `SecurityDatabaseTest`, zéro échec/erreur/test ignoré. |
| Migration réelle | **6 tests supplémentaires** dans [V8MigrationDatabaseTest](../src/test/java/com/tewendelabs/investigator/V8MigrationDatabaseTest.java), zéro échec/erreur/test ignoré. Flyway est ciblé sur V7, les données sont créées, puis Spring Boot applique seulement V8. |
| Conservation | Comparaison des nombres et empreintes de toutes les lignes de toutes les tables publiques, hors historique Flyway, avant/après migration. Historique V1–V7 comparé intégralement. PDF réels synthétiques, 21 versions, 7 investigations, extractions, résultat et revue CONFIRM préexistants conservés. |
| Sauvegarde/retour arrière | `pg_dump -Fc` en V7, `pg_restore --exit-on-error` dans une **base vierge** du même cluster, égalité des données et de l'historique V7, validation Flyway. Les rôles et ACL sont conservés. |
| Échec de migration | Suppression simulée de la policy attendue par renommage : échec V8 après création des helpers, rollback transactionnel constaté, aucune fonction V8 ni ligne V8 résiduelle. Après restauration de la policy, une seule migration appliquée ; exécution suivante : zéro migration. Aucun `repair`. |
| Fonctions et rôles | `can_analyze_policy` DEFINER ; scope et runnable INVOKER ; propriétaire `investigator_owner` non superutilisateur et NOBYPASSRLS ; EXECUTE runtime autorisé, PUBLIC refusé ; `search_path` fixé ; aucune appartenance app → owner. Huit tables avec ENABLE et FORCE RLS ; connexion propriétaire sans acteur : zéro policy visible. |
| Précontrôle SQL | Le [script opérateur](../scripts/qualification_v8_preflight.sql) passe en V7 et V8 ; refuse FORCE RLS désactivée et propriétaire BYPASSRLS. Vérifie également historique/checksums, propriétaires, accès au plan de contrôle et fonctions V8. |
| Travaux V7 en attente | Comptes ordinaires et juges privés/READ partagé : achèvement dans un thread asynchrone, quatre tentatives comptées. Une ancienne demande dont WRITE a été retiré au profit de READ devient analysable pour le juge en V8. |
| Travail V7 RUNNING | Bail non expiré non volé ; après expiration, nouveau token, même deadline, checkpoint réutilisé sans modification ; trois nouveaux appels au lieu de quatre ; ancien token refusé. |
| Révocation | Demande V7 privée de membership : FAILED avant transport. Révocation d'une source partagée pendant un appel simulé bloqué dans un autre thread : un seul appel réservé, aucune extraction ni aucun résultat persisté, FAILED. La régression couvre aussi consentement, expiration, suppression des droits entre retries et invisibilité des résultats. |
| Comptes ordinaires | Writer/ANALYST conservé, VIEWER et simple READ refusés pour l'analyse ; READ → WRITE explicite rétablit la capacité ordinaire. Isolation département/organisation, JPA/JDBC et JWT existant après révocation testés. |
| Juges partagés | Analyse permise sans `can_write_policy` ; UPDATE policy/version, ingestion, nouveau PDF, changement de consentement et revue refusés sur les documents partagés. Cas UUID inconnus/NULL/doublons, mauvais lignage, source future/non indexée/non consentie refusés en Java, RLS et planification DEFINER. |
| Quotas/budgets | Admissions SQL concurrentes : maximum deux succès sur six pour limites investigation/pending ; budget personnel : deux réservations sur six ; collectif : une sur six entre juges. Limites persistantes, rejeu idempotent, transaction annulée, bail invalide, expiration après attente de verrou et chaque retry contrôlés. Runtime sans accès aux tables de quota ni à `reserve_demo_work`. |
| Outillage livraison | **173 tests Python**, dont cinq nouveaux tests d'intégrité d'artefact. Contrôles de déploiement/rollback et refus de dérive SQL inclus. Aucun script de livraison exécuté. |
| JAR final | Huit migrations V1–V8, octets identiques aux sources. SHA-256 JAR : `1ce613cc96861e9c41f5a3cf9a9bd47f5035aa629df561770070a783d93d4008`. Inventaire et checksums dans [v8-artifact.json](verification/v8-artifact.json). |

Les rapports synthétiques et noms de cas sont conservés dans
[v8-qualification.json](verification/v8-qualification.json). Les rapports Surefire
originaux restent dans `target/surefire-reports/`. Les journaux locaux sont dans
`/tmp/v8-qualification/` ; le premier essai Maven en sandbox a échoué à joindre
Docker, puis la suite complète autorisée hors sandbox a réussi.

La référence [v7-migrations.sha256](verification/v7-migrations.sha256) reproduit
le relevé local antérieur `/tmp/judge-v8-original-migrations.sha256`. V1–V7 lui
correspondent, ainsi qu'au JAR et à l'historique Flyway local. Cette preuve ne
certifie pas l'historique d'une production qui n'a pas été consultée. L'opérateur
doit comparer cet historique et le manifeste de la dernière release avant livraison.

La sémantique SQL a été vérifiée via Context7 dans la documentation PostgreSQL 16 :
[RLS forcée et BYPASSRLS](https://www.postgresql.org/docs/16/ddl-rowsecurity.html),
[privilèges du propriétaire de fonction, PUBLIC EXECUTE et search_path](https://www.postgresql.org/docs/16/sql-createfunction.html).
La configuration réellement présente sur un VPS n'est pas attestée par ces tests.
La boucle de traitement est exécutée en asynchrone dans les tests ; les déclencheurs
planifiés Spring sont désactivés pour maîtriser l'ordre, puis les workers réels sont appelés.
Les délais de quelques millisecondes mesurés sur ce petit jeu de données ne sont pas
une estimation du temps de migration ou du RTO avec les volumes de production.

## Rejouer la qualification locale

Ces commandes nécessitent Java 21, Maven avec dépendances déjà en cache, Docker local
et l'image PostgreSQL indiquée. Elles ne consultent pas les fichiers de secrets :
le chargement dotenv est désactivé et les tests fournissent leurs propres connexions.

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests verify
python3 -B -m unittest discover -s scripts/tests -v
python3 -B scripts/qualify_v8_artifact.py --output /tmp/v8-artifact.json
```

Le test de migration seul :

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests -Dtest=V8MigrationDatabaseTest test
```

L'audit JAR refuse une migration absente, une différence JAR/source et toute dérive
V1–V7 par rapport à la référence. Il ne lance ni conteneur ni accès réseau.

## Plan VPS à exécuter ultérieurement par l'opérateur

1. **Préparer selon l'option A confirmée.** Conserver l'écriture privée des juges et
   READ strict sur les documents partagés. Conserver l'application et les images V7 validées avec leurs manifestes,
   préparer la release V8 immuable et son inventaire issu du JAR de l'image
   linux/amd64 exacte. Garder bloquée l'application automatique de migrations
   tant que les précontrôles opérateur et la sauvegarde restaurable ne sont pas validés. Ne pas
   mettre à niveau PostgreSQL/pgvector pendant cette livraison. Vérifier espace
   disque, topologie et volume existants, permissions des secrets sans les afficher,
   rôles/extensions et historique V7 exact. Conserver un verrou de livraison unique.
2. **Maintenance et sauvegarde V7.** Bloquer les nouvelles demandes à l'entrée de
   l'application, terminer si possible les appels RUNNING, puis arrêter seulement
   frontend/backend de ce projet. Laisser PostgreSQL et les autres services en place.
   Relever compteurs, états, deadlines et versions sans contenu de document. Suivre
   la [procédure privée de sauvegarde](DEPLOYMENT.md#postgresql-backup) : `pg_dump -Fc`
   avec le rôle d'administration, fichier privé hors dépôt, checksum SHA-256, archive
   lisible et **restauration répétée dans une base isolée**. Préserver séparément les
   éléments nécessaires aux rôles/authentifiants ; un dump de base n'inclut pas les
   rôles de cluster. Sans sauvegarde restaurable, arrêt de la livraison.
3. **Précontrôle V7.** Exécuter `qualification_v8_preflight.sql` en lecture seule,
   avec `expected_database=investigator` et `target_version=7`, par le canal
   d'administration local au conteneur. Conserver sa sortie privée. Refuser tout
   écart de rôle, RLS, checksum ou historique, sans désactiver la validation ni
   utiliser `flyway repair`. Comparer également les empreintes V1–V7 aux artefacts V7.
4. **Appliquer V8.** Configurer dans le fichier privé de l'opérateur les deux flags
   `APP_WORKER_ENABLED=false` et `APP_INVESTIGATION_WORKER_ENABLED=false`, déjà
   transmis par Compose. Conserver l'entrée publique en maintenance. Activer
   explicitement les migrations pour cette release, via les outils existants ;
   charger les images validées et démarrer V8. Le contrôleur existant garde
   PostgreSQL sans recréation et n'effectue pas de restauration automatique.
5. **Contrôler avant réouverture.** Précontrôle SQL avec `target_version=8`, huit
   migrations réussies, V1–V7 identiques, compteurs et données conservés, rôles/RLS/ACL
   inchangés. Vérifier health interne, modèle local, HTTP 200 sur health et racine,
   401 anonyme sur auth, puis login autorisé, lecture d'anciens PDF/résultats/revues,
   refus des sources non autorisées. Aucun nouveau traitement Meta réel n'est
   nécessaire pour ces contrôles. Une réponse health positive ne suffit pas.
6. **Reprendre et surveiller.** Après validation, réactiver les flags puis recréer
   uniquement le backend avec les mêmes images/configurations ; contrôler la santé
   puis rouvrir le trafic. Surveiller QUEUED/RUNNING, leases, FAILED/PARTIAL et codes
   de révocation/budget. Ne pas remettre les quotas à zéro ou prolonger artificiellement
   les deadlines : une longue maintenance peut expirer un travail. Une requête déjà
   transmise avant arrêt peut avoir été facturée ; sa réservation reste consommée.
   Conserver sauvegarde, manifestes et preuves ; terminer l'état de release uniquement
   après tous les contrôles du contrôleur et les vérifications métier.

Exemple de précontrôle **à préparer pour l'opérateur, non exécuté sur VPS ici**,
avec `backend_compose` défini selon [DEPLOYMENT.md](DEPLOYMENT.md) :

```sh
backend_compose exec -T --user postgres postgres psql -X -U postgres -d investigator \
  -v expected_database=investigator -v target_version=7 < scripts/qualification_v8_preflight.sql
```

Pour le contrôle après migration, utiliser `target_version=8`. Le script termine
par `V8_QUALIFICATION_PREFLIGHT_PASS` et un ROLLBACK de sa transaction en lecture seule.
Il n'affiche ni comptes, ni documents, ni mots de passe. Ses checksums sont ceux du
JAR qualifié ; une autre migration V8 impose une nouvelle qualification.

## Retour arrière réaliste

- **V8 non appliquée ou transaction échouée :** confirmer que l'historique et les
  fonctions sont encore en V7, puis redémarrer la release V7 validée. Si l'état SQL
  est incertain, maintenir l'arrêt et restaurer ; ne pas supprimer une ligne Flyway.
- **V8 validée en base :** un simple remplacement de JAR n'est pas qualifié. Le
  contrôleur refuse une release V7 sur un historique V8 ; ne pas contourner ce refus.
  Aucune annulation automatique de V8 n'est fournie par Flyway ou par cette qualification.
- **Restauration :** arrêter le trafic et les workers, conserver un instantané de
  l'état V8 pour diagnostic, restaurer le dump V7 vérifié dans une **nouvelle base
  vierge**, avec les rôles/extensions/propriétaires/ACL corrects. Contrôler données,
  historique et précontrôle V7 avant toute bascule. Un `pg_restore --clean` contre
  V8 ne garantit pas l'élimination des fonctions introduites uniquement en V8.
  Dans ce Compose, DB_URL désigne explicitement `investigator` : depuis une connexion
  à la base administrative `postgres`, sans connexion applicative active, l'opérateur
  peut renommer l'ancienne base pour la conserver puis donner le nom `investigator`
  à la restauration validée. Cette bascule destructive pour la disponibilité requiert
  sa décision explicite ; elle n'est pas automatisée ici. Redémarrer seulement les
  images V7 correspondantes, contrôler santé, login, isolation et anciens résultats,
  puis rouvrir. Ne supprimer aucun volume et ne réinitialiser aucun rôle.
- **Perte possible :** toutes les écritures depuis le dump peuvent être perdues.
  Ni une restauration ni un rollback applicatif n'annulent une requête Meta déjà
  envoyée ou son coût. Si des travaux ont repris après sauvegarde, sauvegarder aussi
  l'état V8 avant retour et rapprocher les compteurs ; ne pas promettre de reprise
  exacte des appels externes. Mesurer le RTO sur une restauration de taille réelle.

## Automatisation disponible et restante

Disponible sans livraison : test V7 → V8/restore/rollback transactionnel découvert
par le profil Maven `database-tests`, tests de concurrence/quota/révocation, audit
JAR et précontrôle SQL paramétrable en V7/V8. Le contrôleur existant vérifie déjà
archives/digests, compatibilité Flyway, verrou, santé et routage ; il refuse un
rollback incompatible. Les cinq tests de l'audit font désormais partie de la
découverte Python existante. Aucun workflow ni configuration de production modifié.

À intégrer après revue dans une étape de qualification séparée : appeler l'audit
JAR après `verify`, conserver les rapports synthétiques, puis rendre obligatoires
une preuve de sauvegarde restaurable, le précontrôle SQL avant/après et la comparaison
des compteurs. L'archivage privé du dump, son empreinte et une répétition périodique
de restauration sont automatisables ; le stockage des secrets reste privé.
Le périmètre WRITE est confirmé par l'option A. L'autorisation de livraison et une
restauration de production restent des décisions opérateur. La chaîne existante n'apporte pas à elle
seule la preuve d'une sauvegarde restaurable avant migration.

## Fichiers ajoutés

- `src/test/java/com/tewendelabs/investigator/V8MigrationDatabaseTest.java`
- `scripts/qualify_v8_artifact.py`
- `scripts/qualification_v8_preflight.sql`
- `scripts/tests/test_qualify_v8_artifact.py`
- `docs/verification/v7-migrations.sha256`
- `docs/verification/v8-artifact.json`
- `docs/verification/v8-qualification.json`
- `docs/V8_PREPRODUCTION.md`

Les seuls autres fichiers produits sont les sorties Maven usuelles dans `target/`
et les preuves locales dans `/tmp/v8-qualification/`. Aucun fichier applicatif
préexistant ni aucune migration V1–V8 n'ont été modifiés.
