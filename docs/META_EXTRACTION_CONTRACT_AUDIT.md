# Audit hors ligne du contrat d'extraction Meta v3

2026-11-02. Audit complémentaire au diagnostic `UNKNOWN_FIELD_INVALID`.
Périmètre : schéma effectivement sérialisé par `MetaPolicyReasoningProvider`,
prompt système, tâche d'extraction du worker, `JsonContract`,
`EvidenceValidator`, insertion et reprise des checkpoints. Aucun accès à la
production, appel Meta réel, job réel, commande Git, SSH ou déploiement.

## Conclusion et corrections

Un schéma valide n'implique pas une extraction publiable. Les validations de
preuve et de couverture sont indispensables après le schéma. Aucune consigne
directement incompatible avec les contrôles de dates ou de citations n'a été
trouvée. En revanche, les limites et plusieurs invariants n'étaient pas assez
explicites dans les instructions.

Corrections appliquées à la v3 encore non publiée :

- `obligation` : le prompt imposait quatre modalités, alors que schéma et Java
  acceptaient n'importe quelle chaîne. Le schéma devient un enum nullable
  `MUST`, `MUST_NOT`, `SHOULD`, `MAY`, JSON `null`. C'est un renforcement explicite,
  pas un cas de rejet Java caché préexistant.
- `processedSourceIds` : maximum ramené de 30 à 20, égal au nombre maximal de
  sources admises par extraction. Aucune liste distincte de sources autorisées
  n'est exclue par cette réduction. L'appartenance et l'unicité restent en Java.
- Un contrat commun décrit les bornes, la copie des identifiants de chunks,
  les citations non blanches/littérales, la couverture exacte et la possibilité
  de rendre `complete=false` lorsqu'une extraction fidèle ne tient pas dans les
  bornes. Ce texte est présent dans la description du schéma, le système et la
  tâche. Il interdit de tronquer des exigences ou exceptions pour annoncer une
  couverture complète.
- `JsonContract` rejette explicitement U+0000 et les surrogates isolés dans les
  chaînes : ces valeurs représentables dans une chaîne JSON ne sont pas
  compatibles avec les checkpoints PostgreSQL `jsonb`. Le code sûr
  `UNPERSISTABLE_MODEL_TEXT` remplace un échec SQL tardif et générique. Aucun
  caractère n'est supprimé ou remplacé. La vérification s'applique également
  aux sorties d'assessment validées par ce même composant.
- Les bornes UTF-16 existantes sont conservées et annoncées. Passer silencieusement
  à un comptage par points de code augmenterait les volumes actuellement admis.

Ni migration, ni modification du chemin de reprise, des dates, des citations,
de l'accès, du consentement, des quotas ou des leases. Les versions restent
`requirements-v3` / `policy-investigator-2026-11-02-v3`, puisqu'il s'agit de
l'audit avant publication de cette même v3.

## Comparaison champ par champ après corrections

Tous les objets du modèle interdisent les propriétés supplémentaires et exigent
toutes leurs propriétés déclarées. Le validateur applique les types sans
coercition avant les appels à `asString`/`asBoolean`.

| Champ | Schéma JSON envoyé | Système et tâche | Java / persistance / reprise |
| --- | --- | --- | --- |
| `requirements` | Tableau obligatoire, non nul, 0–16 objets | Toutes les exigences explicites ; aucune invention ; couverture incomplète si les bornes empêchent une restitution fidèle | Tableau vide autorisé, y compris avec `complete=true` si toutes les sources sont traitées. Validation de toute la réponse avant insertion de la version. |
| `actor` | Chaîne ou null, longueur ≤ 2000 | Explicite seulement ; null si inconnu | Null si et seulement si le nom est dans `unknownFields`. Chaîne vide/blanche non normalisée, admise structurellement. |
| `action` | Chaîne ou null, longueur ≤ 2000 | Même règle ; aucune exigence fabriquée | Même équivalence null/liste. La pertinence sémantique du texte n'est pas prouvée par sa seule présence. |
| `obligation` | Enum `MUST`, `MUST_NOT`, `SHOULD`, `MAY`, null | Même enum ; null si la modalité n'est pas explicitement et clairement établie | Enum vérifié par `JsonContract`, puis équivalence null/liste. Aucune conversion de `must`, `MUST NOT`, `REQUIRED`, chaîne vide ou chaîne `"null"`. |
| `condition` | Chaîne ou null, longueur ≤ 2000 | Préserver les conditions ; null si inconnu | Équivalence null/liste ; pas de déduction de condition absente. |
| `scope` | Chaîne ou null, longueur ≤ 2000 | Préserver l'applicabilité ; null si inconnue | Équivalence null/liste ; l'absence de contradiction n'est pas inférée de l'absence de scope. |
| `deadline` | Chaîne ou null, longueur ≤ 2000 | Délai absolu ou relatif ; distinct de la date d'effet | Aucune tentative de parser le délai comme une date. Équivalence null/liste. |
| `effectiveDate` | Chaîne ou null, longueur ≤ 2000 ; description ISO complète | ISO YYYY-MM-DD si explicite et non ambigu ; sinon null ; ne pas utiliser les métadonnées ou la date d'analyse comme substitution | Format ASCII exact puis `LocalDate.parse` strict. Pas d'espaces, date partielle, timestamp ou calendrier impossible. Équivalence null/liste vérifiée avant la date. |
| `exceptions` | Tableau ou null, au plus 20 chaînes de longueur ≤ 2000 ; tableau vide autorisé | Null si inconnu ; `[]` seulement si l'absence d'exceptions est explicitement établie ; préserver toutes les exceptions | `[]` est non nul et ne doit pas être listé comme inconnu. Le texte des exceptions n'est ni dédupliqué ni réécrit. |
| `unknownFields` | Tableau non nul, 0–8 noms dans l'enum des huit champs | Noms exacts, distincts, sensibles à la casse ; correspondance exacte avec JSON null | Unicité et équivalence null/liste vérifiées en Java. L'ordre est libre. Les noms interdits échouent dès le schéma. |
| `sourceReferences` | Tableau non nul de 1–12 objets | Citations courtes mais suffisantes, exactes et non blanches ; aucune reformulation | Chaque référence est vérifiée contre le catalogue fourni. La version attendue doit être citée. Des références répétées sont admises par le schéma et Java ; elles ne prouvent pas une couverture supplémentaire. |
| `sourceReferences[].sourceId` | Chaîne non nulle, longueur ≤ 2000 | Copier un `sourceId` fourni, pas un ID de document, version ou exigence | Égalité exacte avec un UUID canonique du catalogue ; un UUID valide mais inconnu est refusé. Aucune normalisation de casse/espaces. |
| `sourceReferences[].quote` | Chaîne non nulle, longueur 1–2000 | Sous-chaîne contiguë exacte, non blanche, sans nettoyage ; preuve réelle de l'exigence | `isBlank()` puis `source.excerpt().contains(quote)`. Pas de normalisation Unicode, retrait d'espaces, paraphrase ou correction de ponctuation. |
| `processedSourceIds` | Tableau non nul de 0–20 chaînes, longueur ≤ 2000 | Uniquement les sources fournies, sans doublons ; marquer un extrait après traitement de tout son contenu | Sous-ensemble du catalogue ; unicité ; égalité avec tout le catalogue si `complete=true`. Aucune obligation que toutes les sources soient citées si elles ne contiennent pas d'exigence. |
| `complete` | Booléen strict, jamais null ni chaîne | Couverture de traitement, pas certitude ; les champs inconnus peuvent coexister avec true | Si true : égalité des sources traitées/fournies. Si false mais réponse valide : checkpoint enregistré, puis arrêt `PARTIAL / INCOMPLETE_EXTRACTION` ; aucun assessment. |
| `limitations` | Tableau non nul, 0–30 chaînes, longueur ≤ 2000 | Expliquer les inconnues et l'impossibilité d'une couverture fidèle | Conservé tel quel. Java n'exige pas de texte non vide et ne prouve pas l'explication sémantique. Les caractères incompatibles avec `jsonb` sont refusés. |
| `id`, provenance, `confidence` | Absents du schéma du modèle, donc interdits | Ne pas fournir d'identifiants ni de provenance serveur | UUID déterministe attribué par le serveur après validation des exigences. Le payload enrichi est un checkpoint, pas une nouvelle réponse modèle à revalider contre le schéma brut. |

Les champs textuels non enums admettent structurellement la chaîne vide et les
espaces. Cela ne permet pas de les utiliser comme substituts à une inconnue :
les consignes exigent JSON null pour une valeur absente des sources. Il n'existe
pas de rejet Java supplémentaire de ces chaînes, sauf les règles propres aux
citations et aux dates.

## Sorties encore admises structurellement mais refusables ensuite

Ces écarts restent explicites. Les vérifications dépendant des documents ou de
plusieurs champs ne sont pas supprimées pour faire réussir une réponse modèle.
Les descriptions du schéma guident le modèle ; elles ne sont pas des contraintes
structurelles exécutées par `JsonContract`.

| Écart restant | Exemple structurellement admis | Rejet / comportement | Traitement retenu |
| --- | --- | --- | --- |
| Invariant null/liste | `effectiveDate:null` absent de `unknownFields`, ou `exceptions:[]` listé comme inconnu | `UNKNOWN_FIELD_INVALID` | Consigne commune et diagnostics v3 ; Java reste strict. |
| Unicité des listes de noms/IDs | Deux occurrences du même nom autorisé ou du même sourceId | `DUPLICATE_MODEL_REFERENCE` | Consigne explicite ; aucune déduplication automatique. Pas de nouvel ajout de mot-clé Meta non qualifié pour l'unicité. |
| Catalogue et couverture | Source traitée inconnue ; source fournie manquante avec `complete=true` | `INCOMPLETE_SOURCE_COVERAGE` | Appartenance, unicité et égalité contrôlées en Java. |
| Citation et version | ID inconnu, mauvais type d'identifiant, citation blanche/non littérale, version attendue non citée | `UNVERIFIABLE_SOURCE_REFERENCE` ou `INSUFFICIENT_CITATION_COVERAGE` | Consigne précise ; aucune correction de citation ni preuve inventée. |
| Date exacte et calendrier | `2025-02-29`, `2025-01`, date textuelle, timestamp | `INVALID_EFFECTIVE_DATE` | Null demandé en cas d'incertitude ; validation de format et calendrier conservée, sans fallback. |
| Longueur Unicode | 1001 caractères supplémentaires : 1001 points de code mais 2002 unités UTF-16 | `INVALID_MODEL_SCHEMA` dans le validateur local | Différence réelle entre le comptage Unicode de JSON Schema et la borne Java historique. Budget UTF-16 conservé et annoncé ; cet écart machine n'est pas éliminé. |
| Unicode de persistance | U+0000 ou surrogate isolé dans une chaîne JSON | `UNPERSISTABLE_MODEL_TEXT` | Nouveau rejet sûr avant SQL ; aucun nettoyage du contenu. Le schéma structurel seul ne garantit pas la persistance. |
| Limite globale d'une réponse | Plusieurs champs respectant chacun leur borne mais JSON total > 100000 unités UTF-16 | `MALFORMED_MODEL_OUTPUT` au parsing, avant validation du schéma | Plafond existant conservé ; test dédié. Les bornes par champ ne promettent pas que leur produit sera accepté. |
| Couverture déclarée incomplète | `complete=false`, références et valeurs valides | Checkpoint conservé puis `INCOMPLETE_EXTRACTION` | Ce n'est pas une erreur de schéma : l'arrêt protège contre une publication incomplète. Pas de retry ni de nouvelle génération automatique. |
| Budgets/autorisation entre phases | Extraction valide mais contexte d'assessment sérialisé > 32000, source totale > 20000, lease expiré ou consentement révoqué | Codes de budget/accès/lease existants ; pas d'assessment complet | Contrôles intentionnels hors schéma, conservés. Une extraction valide ne réserve pas les droits ou budgets futurs. |

Le transport HTTP conserve aussi son plafond de 262144 octets ; le provider
exige le modèle attendu, un usage cohérent, `finish_reason=stop`, sans refus.
Ces contrôles d'enveloppe ne sont pas décrits par le schéma du contenu. Les
erreurs de validation ne font pas partie des erreurs retentées par le provider.

Il subsiste des limites de preuve, distinctes d'un rejet Java caché : une date
ISO plausible n'est pas automatiquement prouvée par le texte cité ; une citation
littérale n'établit pas à elle seule que tous les champs en découlent ; l'égalité
des IDs traités ne démontre pas l'exhaustivité sémantique de l'extraction. Le
contrat les demande au modèle mais aucun nouveau mécanisme d'inférence ou de
fausse certitude n'est introduit. De même, Java ne refuse pas des `limitations`
vides pour une sortie incomplète ; cette sortie n'est de toute façon pas publiée
comme assessment complet.

## Persistance et reprise

Le worker contrôle le périmètre et les sources avant la génération ou la
réutilisation. Le gate recontrôle autorisation, consentement, identité et texte
des sources avant chaque tentative réelle. L'usage est comptabilisé avant la
validation du contenu. Une réponse rejetée n'est pas un checkpoint.

Après validation de toute la réponse d'extraction et attribution des IDs, le
worker contrôle le lease via `checkpoint_investigation` et insère le JSON enrichi
avec `(investigation_id, version_id)`, empreinte des sources, modèle, prompt et
schéma. La transaction d'acteur enveloppe le contrôle et l'insertion. Les
extractions antérieures restent conservées si une autre version échoue. Un
graphe incomplet est une projection de ces checkpoints, pas un checkpoint
d'assessment supplémentaire.

La reprise exige le même modèle et la même empreinte des sources ordonnées
sérialisées, ainsi qu'une paire connue de versions :

| Prompt | Schéma |
| --- | --- |
| `policy-investigator-2026-10-27-v1` | `requirements-v1` |
| `policy-investigator-2026-11-02-v2` | `requirements-v2` |
| `policy-investigator-2026-11-02-v3` | `requirements-v3` |

Les anciennes extractions déjà validées sont lues sans réécriture ni validation
contre le nouveau schéma brut. Cela préserve les IDs et les modalités en texte
libre admises par les anciens contrats. Les réponses nouvellement générées
doivent respecter le nouvel enum. Les paires croisées/inconnues, modèles ou
empreintes différents restent `EXTRACTION_CHECKPOINT_MISMATCH`.

Un checkpoint avec `complete=false` reste incomplet : il est conservé puis le
worker s'arrête sans nouvelle extraction ni assessment. Le correctif n'ajoute
ni reprise automatique des jobs terminés en `FAILED`/`PARTIAL`, ni nouvelle
investigation. Le schéma d'impact conserve sa structure ; 16 exigences par
version donnent au maximum 32 alignements et 64 couples remplacement/procédure
pour quatre procédures, ce qui correspond aux bornes des tableaux d'impact.

## Fichiers de cet audit

Production (local uniquement) :

- `src/main/java/com/tewendelabs/investigator/investigation/InvestigationSchemas.java`
- `src/main/java/com/tewendelabs/investigator/investigation/JsonContract.java`
- `src/main/java/com/tewendelabs/investigator/investigation/InvestigationWorker.java`
- `src/main/java/com/tewendelabs/investigator/provider/MetaPolicyReasoningProvider.java`

Tests :

- `src/test/java/com/tewendelabs/investigator/investigation/ExtractionContractAuditTest.java` (nouveau)
- `src/test/java/com/tewendelabs/investigator/investigation/UnknownFieldsContractTest.java`
- `src/test/java/com/tewendelabs/investigator/investigation/UnknownFieldsOfflineTest.java`
- `src/test/java/com/tewendelabs/investigator/provider/MetaPolicyReasoningProviderTest.java`

Documentation : ce rapport et le lien de suivi ajouté dans
`docs/UNKNOWN_FIELDS_DIAGNOSTIC.md`. `EvidenceValidator` et les migrations SQL
n'ont pas changé pendant cet audit.

## Vérification

Les fixtures vérifient notamment les types obligatoires, l'enum nullable, les
bornes des chaînes et tableaux, le vide, les 256 combinaisons de valeurs nulles,
les IDs documentaires, les citations, dates, le contenu non persistable, les
erreurs avant/après checkpoint, l'absence de retry, la comptabilisation et les
reprises v1/v2/v3. Le nouveau schéma et les instructions sont inspectés dans les
requêtes sérialisées d'un transport simulé.

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Dtest=StructuredValidationTest,UnknownFieldsContractTest,UnknownFieldsOfflineTest,MetaPolicyReasoningProviderTest,WorkerPollingTest,ExtractionContractAuditTest test
```

Le transport, les autorisations, les quotas et JDBC sont simulés. Aucun contexte
Boot global n'est démarré. Ces tests ne qualifient ni une vraie transaction SQL,
ni l'acceptation du schéma ou l'obéissance du service Meta. L'attachement de
Mockito nécessite ici une exécution locale autorisée hors sandbox ; Maven reste
hors ligne. Le premier essai en sandbox échoue sur cet attachement, pas sur une
assertion de contrat.

Résultat final : **200 tests, 0 échec, 0 erreur, 0 ignoré — BUILD SUCCESS**.

| Suite | Tests |
| --- | ---: |
| `ExtractionContractAuditTest` | 49 |
| `UnknownFieldsOfflineTest` | 32 |
| `UnknownFieldsContractTest` | 28 |
| `StructuredValidationTest` | 52 |
| `MetaPolicyReasoningProviderTest` | 36 |
| `WorkerPollingTest` | 3 |
| **Total** | **200** |

Les 256 combinaisons null/non-null sont parcourues dans un seul test. Les
modalités historiques hors enum sont couvertes en v1 et v2, sans réécriture.
Journal local final : `/private/tmp/meta-extraction-contract-audit-tests-escalated.log`.
