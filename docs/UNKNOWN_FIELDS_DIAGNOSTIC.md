# UNKNOWN_FIELD_INVALID — diagnostic et correctif local

Date : 2026-11-02. Analyse du code local, sans consultation ni modification de
production, sans transport Meta réel, sans relance d'investigation existante.

Complément avant publication : [audit complet du contrat d'extraction v3](META_EXTRACTION_CONTRACT_AUDIT.md),
incluant l'enum nullable de modalité, les limites et la compatibilité de persistance.

## Diagnostic avant correction

`EvidenceValidator.extraction` était le seul endroit levant
`ApiFailure(502, "UNKNOWN_FIELD_INVALID")`, dans deux cas :

1. Un nom de `unknownFields` n'appartient pas aux huit champs autorisés.
2. Pour l'un des huit champs, `value.isNull() != unknown.contains(field)`.
   Cela couvre un champ nul omis de la liste et un champ non nul présent dans
   celle-ci. `exceptions: []` est non nul, donc incompatible avec la présence de
   `exceptions` dans `unknownFields`.

Le schéma `requirements-v2` utilisait `strings()` : tableau obligatoire et non
nul, de 0 à 30 chaînes d'au plus 2000 caractères, sans énumération des noms.
`strict: true` ne couvrait donc pas les contraintes métier manquantes du schéma.
Les doublons étaient refusés séparément par `EvidenceValidator.values`, avec le
code `DUPLICATE_MODEL_REFERENCE` ; les mauvais types relevaient déjà de
`INVALID_MODEL_SCHEMA`.

Les noms métier exacts, sensibles à la casse et sans espaces ni préfixes, sont :

`actor`, `action`, `obligation`, `condition`, `scope`, `deadline`, `exceptions`,
`effectiveDate`.

Les huit propriétés sont obligatoires dans chaque exigence. Toutes acceptent
JSON `null` ; les valeurs connues sont des chaînes, sauf `exceptions`, qui est
un tableau de chaînes. `unknownFields` contient exactement les noms des
propriétés dont la valeur est JSON `null`. L'ordre n'a pas d'importance. Le
tableau vide convient lorsque les huit valeurs sont non nulles. Une chaîne
`"null"` n'est pas JSON `null`.

Exemples d'incohérences auparavant admises par le schéma mais rejetées en Java :

| Valeur du champ | Présence dans `unknownFields` | Résultat métier |
| --- | --- | --- |
| `effectiveDate: null` | `effectiveDate` absent | `UNKNOWN_FIELD_INVALID` |
| `condition: "When approved"` | `condition` présent | `UNKNOWN_FIELD_INVALID` |
| `exceptions: []` | `exceptions` présent | `UNKNOWN_FIELD_INVALID` |
| `effectiveDate: null` | `effective_date` ajouté | `UNKNOWN_FIELD_INVALID` |

Le prompt système et la tâche du worker demandaient déjà de mettre les champs
inconnus à `null` et de les nommer dans `unknownFields`. Le correctif de date
demande explicitement `effectiveDate` dans cette liste lorsque la date est
inconnue : ce nom était déjà autorisé par Java. **Aucune consigne explicitement
contradictoire avec la liste Java n'est démontrée.** En revanche, l'énumération
et la règle « si et seulement si » n'étaient pas explicites dans le contrat
transmis au modèle.

Le message communiqué ne permet pas d'identifier la valeur réellement rejetée,
l'exigence ou la version de Remote Work : les deux branches partageaient le
même code et ne journalisaient aucun sous-motif. La réponse rejetée n'est pas
enregistrée comme checkpoint. Le dépôt ne permet pas d'affirmer quel cas a eu
lieu sur cette instance. Les fixtures reproduisent les classes de défaut,
elles ne constituent pas une copie d'une réponse de production.

## Étape d'échec et conservation

L'ordre est : réception Meta et comptabilisation de l'usage, validation du
schéma dans le provider, validation du schéma dans `EvidenceValidator`,
couverture des sources, citations de l'exigence, `unknownFields`, date, puis
attribution d'un identifiant serveur. Le checkpoint de la version n'est inséré
qu'après validation de **toute** la réponse d'extraction.

Ainsi, `UNKNOWN_FIELD_INVALID` indique un rejet pendant l'extraction d'une
baseline, d'un remplacement ou d'une procédure, avant l'appel d'évaluation
d'impact. Pour l'exigence rejetée, les citations ont passé la validation ; cela
ne prouve pas la validité des exigences suivantes ni de la date, validée après.
Le traitement s'arrête au premier échec. La version invalide n'est pas
sauvegardée, même si des exigences précédentes de cette réponse étaient valides.

- Sans checkpoint rencontré dans la tentative : `FAILED`.
- Après au moins un checkpoint enregistré ou réutilisé : `PARTIAL`.
- Les extractions antérieures restent intactes. Aucun assessment n'est publié.
- Le graphe est une projection des extractions et assessments enregistrés,
  pas un checkpoint séparé. Il peut présenter les versions, exigences et liens
  `CONTAINS` déjà validés, avec `complete=false` et sans constat d'impact.
- Le statut final remplace le stage par `STOPPED` ; ce stage ne permet pas de
  retrouver rétrospectivement la version fautive.
- Le worker ne retente pas une erreur de validation. Les seuls retries du
  provider concernent timeout, indisponibilité et limitation de débit. Les jobs
  `FAILED`/`PARTIAL` ne sont pas repris automatiquement par `claim_investigation`.

La lecture reste soumise aux contrôles d'accès et de citations existants. Aucune
reprise des jobs arrêtés n'est ajoutée par ce correctif.

## Correction préparée

1. `InvestigationSchemas` définit une liste immuable commune aux noms autorisés
   par le schéma et par Java. `unknownFields.items` devient une énumération et
   `maxItems` vaut huit. Le schéma ne prétend pas garantir l'unicité ou la
   dépendance entre valeurs et liste : ces vérifications restent en Java.
2. Une consigne commune, incluse dans le schéma, le prompt système et la tâche
   d'extraction, explicite la casse, l'absence de doublons, la correspondance
   exacte avec JSON `null`, et la différence entre exceptions inconnues et
   absence d'exceptions explicitement établie. Aucune valeur n'est inventée.
3. Le validateur conserve le rejet strict de toute incohérence, sans réparer,
   filtrer, dédupliquer, normaliser ou compléter la réponse. Il fournit un
   sous-motif interne pour les deux directions de l'incohérence. Le worker
   journalise uniquement motif fixe, nom de champ autorisé, stage fixe, UUID
   d'investigation/version et index d'exigence à partir de zéro. Ni contenu de
   document/modèle, ni clé, ni token de lease, ni stack trace ne sont ajoutés.
4. Les nouvelles générations sont identifiées par `requirements-v3` et
   `policy-investigator-2026-11-02-v3`. Un nom interdit est désormais rejeté dès
   le schéma avec `INVALID_MODEL_SCHEMA`. Une incohérence null/liste reste
   `UNKNOWN_FIELD_INVALID` avec le même statut 502. Les doublons de longueur
   admissible restent `DUPLICATE_MODEL_REFERENCE` ; un tableau de plus de huit
   éléments relève du schéma.

Les contrôles de sources, dates, couverture, accès, consentement, leases,
budgets et comptabilisation restent en place. Le nouveau contrat réduit les
sorties incohérentes possibles ; il ne garantit pas qu'un modèle respectera
toutes les contraintes métier. La validation indépendante reste nécessaire.
L'acceptation du nouveau schéma par le service Meta réel n'a pas été testée.

## Compatibilité

Les paires suivantes sont reconnues pour réutiliser une extraction déjà validée :

| Prompt enregistré | Schéma enregistré |
| --- | --- |
| `policy-investigator-2026-10-27-v1` | `requirements-v1` |
| `policy-investigator-2026-11-02-v2` | `requirements-v2` |
| `policy-investigator-2026-11-02-v3` | `requirements-v3` |

L'égalité du modèle et de l'empreinte des sources reste obligatoire. Les paires
croisées ou inconnues restent refusées avec `EXTRACTION_CHECKPOINT_MISMATCH`.
La réutilisation ne revalide ni ne réécrit les payloads historiques enrichis
d'identifiants serveur. Leur structure, leurs identifiants et les projections
de lecture ne changent pas. Aucune migration SQL n'est nécessaire.

Cette compatibilité porte sur des checkpoints déjà validés et persistés ; elle
n'autorise pas de nouvelles réponses avec les anciens schémas. Une réponse
refusée auparavant ne devient pas réutilisable : elle n'a pas de checkpoint.
Les résultats des investigations terminées restent lus avec leurs métadonnées
d'origine, sans régénération. Les tests utilisent des fixtures historiques
synthétiques ; aucun enregistrement de production n'a été inspecté.

## Vérification hors ligne

Commande ciblée (dotenv désactivé, résolution Maven hors ligne) :

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Dtest=StructuredValidationTest,UnknownFieldsContractTest,UnknownFieldsOfflineTest,MetaPolicyReasoningProviderTest,WorkerPollingTest test
```

Les nouvelles suites couvrent : les 256 combinaisons null/non-null ; les deux
directions d'incohérence sur les huit champs ; les noms inconnus, alias, chemins,
espaces et casse ; les doublons, types incorrects, absence de propriété et
bornes ; le schéma réellement sérialisé dans la requête Meta ; le passage du
provider réel au validateur et au worker via un transport simulé ; un échec sur
baseline, remplacement et procédure ; l'absence de retry et d'assessment ; la
comptabilisation de chaque réponse ; la préservation des checkpoints ; les
projections de graphe et de résultats incomplets ; la réutilisation v1/v2 sans
nouvelle extraction ; le rejet des empreintes, modèles et versions incompatibles.

Le transport, le gate de quotas, les autorisations et JDBC sont simulés dans la
suite worker. Ces tests ne qualifient pas une vraie transaction PostgreSQL ou
le service Meta. Les tests existants de dates, citations, couverture et limites
du provider sont également exécutés. Aucun contexte Boot global, réseau,
base de production ou clé réelle n'est nécessaire.

Résultat final local : **134 tests, 0 échec, 0 erreur, 0 test ignoré**,
`BUILD SUCCESS`. Les 256 combinaisons sont parcourues dans un seul test.
Journal : `/private/tmp/unknown-fields-final-verification.log`.
Le premier essai en sandbox a échoué sur l'attachement de l'agent Mockito ;
la vérification finale a été exécutée hors sandbox, avec autorisation, toujours
en mode Maven hors ligne et avec les mêmes simulations.
