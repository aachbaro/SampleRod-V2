# Recherche préalable — refonte de la Réserve

## 0. Conclusion exécutive

La Réserve possède déjà une base de mutualisation utile : `ReservePane`, `ReserveEntry`, `ReserveActions`, les quatre statuts de disponibilité/analyse et le lecteur global `AppContext.audio_player`. Elle n'est toutefois pas encore une architecture à modèle de vue partagé : les trois onglets construisent et sélectionnent leurs données différemment.

- **Dossiers** est un navigateur du disque, enrichi à la volée par le cache DB.
- **Historique** est en réalité la liste complète des samples de la DB/cache, triée par ID décroissant. Ce n'est ni un journal d'écoute ni un historique de modifications.
- **Indexé** est une vue tabulaire de la même population DB, organisée par racines/dossiers et métadonnées.

Le point sémantique le plus fragile est `Retirer de l'historique` : cette action supprime la fiche `Sample` de la DB et du cache, mais conserve le fichier. Le fichier devient donc « non indexé » dans Dossiers et disparaît également d'Indexé. Le terme « historique » masque une véritable désindexation.

La distinction suivante est confirmée et doit rester explicite :

```text
MaterialStatus = statut conceptuel de la matière dans le workflow
SOURCE / DERIVED / ARTIFACT

ReserveEntry.status = état technique de disponibilité/indexation/analyse
normal / non_indexed / needs_analysis / missing
```

Ces deux axes sont orthogonaux. Un sample `MaterialStatus.SOURCE` peut être `needs_analysis` ou `missing`.

## 1. Architecture actuelle

### 1.1 Autorités et flux

```text
ReservePane
├── barre partagée : recherche + état + analyse + compatibilité de gamme
├── Dossiers   → DirectoryWidget → DirectoryService → disque + cache SampleService
├── Historique → SampleListWidget → SampleService → cache mémoire + table samples
└── Indexé     → LibraryWidget → LibraryService → cache SampleService + settings.libraries

Sélection UI
→ ReserveEntry (langage commun partiel)
→ ReserveActions
→ AppContext.audio_player / SampleService / ouverture Labo

SampleService
→ table SQLite samples
→ normalisation asynchrone
→ ScaleAnalysisService (file + QThread)
→ signaux incrémentaux vers les trois vues
```

### 1.2 État faisant autorité

| État | Autorité réelle |
|---|---|
| Fichiers et dossiers | système de fichiers |
| Samples connus | table SQLAlchemy `samples` |
| Copie active des samples | `SampleService._samples` |
| Navigation Dossiers | `DirectoryWidget.current_dir/root_dir` + `QSettings` |
| Sélection Dossiers | chemins dans `DirectoryWidget` |
| Sélection Historique | ID courant + `selected_ids` de checkboxes |
| Sélection Indexé | ligne `QTableWidget` + `_selected_sample_id` |
| Lecture | unique `AppContext.audio_player` |
| Filtre commun | `ReservePane`, propagé dans chaque vue |
| Filtre de gamme propre à Indexé | `LibraryWidget.scale_filter` |
| Résultats d'analyse | colonnes de `Sample` |
| Provenance matière | JSON `Sample.material_metadata` |

### 1.3 Fichiers et classes principaux

**EXISTE ACTUELLEMENT**

- `frontend/reserve/reserve_pane.py` — composition des trois vues et filtres communs.
- `frontend/reserve/reserve_entry.py` — `ReserveEntry`, statuts et fonctions de filtrage.
- `frontend/reserve/reserve_actions.py` — preview, seek, renommage, révélation, envoi au Labo.
- `frontend/right_panel/directory/directory_widget.py` — façade Dossiers.
- `directory_navigation.py`, `directory_list_builder.py`, `directory_selection.py`, `directory_filter.py`, `directory_index.py`, `directory_store_sync.py`, `directory_item_widget.py`, `directory_list_widget.py`, `directory_detail.py` — contrôleurs et UI de Dossiers.
- `frontend/sample_gui/sample/sample_list.py` — Historique.
- `sample_list_cards.py`, `sample_list_selection.py`, `sample_list_pagination.py`, `sample_list_dragdrop.py`, `sample_card*.py` — cartes et opérations Historique.
- `frontend/library_gui/library_widget.py` — Indexé.
- `library_ui.py`, `library_detail.py` — tableau, navigation et inspecteur.
- `backend/services/directory_service.py` — scan, description et indexation disque/DB.
- `backend/services/library_service.py` — scopes par racine/dossier et filtres DB en mémoire.
- `backend/services/sample_service.py` — CRUD, cache, normalisation, analyse et promotion en SOURCE.
- `backend/services/scale_analysis_service.py` — analyse musicale asynchrone.
- `backend/models/sample.py` — modèle ORM.
- `backend/models/AppContext.py` — lecteur audio global.

## 2. Modèle de données

### 2.1 `Sample`

La table `samples` stocke : `id`, `path` unique, `name`, `duration` en secondes, `created_at` en `DateTime`, `missing`, `rms_level`, `analyzed_at`, `dominant_note`, `detected_scale_label`, `detected_scale_kind`, `scale_confidence`, `compatible_scales` JSON texte et `material_metadata` JSON texte.

Le poids n'est pas stocké. Indexé le calcule avec `os.path.getsize()` dans un thread dédié et garde un cache mémoire.

### 2.2 `ReserveEntry`

`ReserveEntry` est une projection commune, pas une autorité persistante. Il contient source, chemin, ID DB éventuel, dossier/racine, durée, RMS, analyse et état technique. Dossiers le construit depuis `DirectoryAudioEntry`; Historique et Indexé depuis `Sample`.

### 2.3 États techniques réels

| État | Condition | Persisté directement ? | Transition |
|---|---|---|---|
| `normal` | indexé, présent, `needs_analysis=False` | dérivé des colonnes | analyse réussie |
| `non_indexed` | fichier disque sans fiche DB | non | indexation/import |
| `needs_analysis` | indexé, présent, `analyzed_at is None` | `analyzed_at` | analyse réussie |
| `missing` | `Sample.missing=True` | oui | réindexation/recovery ou suppression fiche |
| « analyse en cours » | seulement feedback UI/file d'attente | non | succès/échec |
| erreur d'analyse | log et signal d'échec | non | nouvelle tentative manuelle |
| erreur d'indexation | message UI et compteur d'erreurs | non comme statut d'entrée | relance |

Il n'existe pas de cinquième statut persistant `error` ou `analyzing` dans `ReserveEntry`.

## 3. Dossiers

### 3.1 Fonction réelle

Dossiers est **disque d'abord**. La liste visible est reconstruite à partir de `os.listdir()` et `DirectoryService.list_audio_entries()`, puis enrichie par correspondance normalisée avec le cache de `SampleService`.

### 3.2 Navigation

- `current_dir` et `root_dir` sont des chemins absolus normalisés.
- Le breadcrumb est interactif et reconstruit à chaque navigation; il affiche au plus quatre segments avec une ellipse.
- Le parent remonte réellement jusqu'à la racine du volume. Il n'est pas borné à `root_dir`.
- Il n'existe pas de pile précédent/suivant.
- `DirectoryHistory` persiste dernier dossier, dernière racine, nœuds développés (200) et dossiers récents (10), mais pas une navigation avant/arrière.
- Plusieurs racines configurées existent dans `settings.libraries`, mais un `DirectoryWidget` n'a qu'une racine active. On peut choisir n'importe quel dossier et sortir de l'ancienne racine.
- L'arbre `QFileSystemModel` existe encore mais est caché; plusieurs attributs UI sont conservés comme stubs de compatibilité.
- Si le dossier restauré a disparu, il est ignoré. Si le dossier courant disparaît pendant l'usage, un refresh produit une liste vide; aucune récupération guidée n'est prévue.

### 3.3 Scan et formats

- Sous-dossiers immédiats et fichiers audio immédiats seulement pour l'affichage.
- Indexation récursive pour les compteurs et la DB.
- Formats : AIF/AIFF/AU/FLAC/M4A/MP3/OGG/OPUS/WAV/WMA.
- Le listing visible est synchrone sur le thread UI. Les fichiers indexés utilisent le cache; les non indexés évitent le probing audio complet dans la liste.
- Aucun pagination/virtualisation : un widget Qt est créé pour chaque fichier et sous-dossier immédiat.
- `_DirectoryEntriesWorker`, censé charger par lots, est explicitement mort et référence des fonctions supprimées.

### 3.4 Signification des compteurs

```text
Disque: 8934
```

Nombre de fichiers audio sous le dossier, récursivement.

```text
DB: 680
```

Nombre de fiches `Sample` dont le chemin se trouve sous ce dossier, y compris les fiches marquées manquantes.

```text
Manquants: 1
```

Nombre de fiches DB déjà marquées `missing=True`. Le calcul détecte aussi des fiches devenues absentes mais non encore marquées (`stale_present`) sans les inclure dans ce nombre affiché.

```text
680/8934 indexés — Continuer
```

Le chip compare `tracked` à `on_disk`. « Continuer » relance en réalité une synchronisation récursive complète, pas un curseur de reprise stocké.

### 3.5 Indexation

- Un seul `_DirectoryIndexWorker` global peut fonctionner à la fois.
- Le scan est asynchrone, récursif et incrémental au sens « ajoute/met à jour seulement ce qui diffère ».
- Il n'existe ni bouton d'annulation ni checkpoint. Une relance rescane depuis le début.
- Chaque fichier est probé, durée/date/RMS inclus.
- Les inconnus deviennent des `Sample` avec `analyzed_at=None`.
- Les fichiers disparus sont marqués `missing`; ceux qui reviennent sont récupérés.
- Les fichiers illisibles incrémentent `errors`, sont ignorés et n'interrompent pas le lot.
- L'indexation ne lance pas explicitement `ScaleAnalysisService` pour chaque `Sample` créé directement par le worker. Après `load_all()`, ils restent « À analyser » jusqu'au bouton d'analyse par lots ou une autre relance explicite.
- Indexation, normalisation et analyse musicale sont donc trois opérations distinctes.

### 3.6 Fichiers non indexés

- Écoutables avec un ID de lecture dérivé du chemin.
- Draggables comme `AUDIO_FILE / SOURCE / IMPORT`.
- Envoyables au Labo/Waveform via leur chemin.
- Renommables et supprimables physiquement.
- Pas de gamme/compatibilité tant qu'ils n'ont pas de fiche DB.
- Ils deviennent persistants dans la Réserve lors d'une indexation ou d'un import explicite.

### 3.7 Sélection, menus et raccourcis

Sélection simple uniquement; pas de Ctrl/Shift, checkbox ni drag multiple.

| Entrée | Action |
|---|---|
| Haut/Bas | sélection précédente/suivante |
| Espace | preview/pause |
| Droite | avance de 10 %, bornée entre 750 ms et 8 s |
| Entrée | envoi au Labo |
| Gauche | dossier parent |
| F2 | renommage |
| Suppr | suppression |

Menu fichier : preview, renommer, compatibles, envoyer au Labo, ouvrir le dossier, supprimer. Le clic/double-clic des sous-dossiers ouvre le dossier. La suppression d'un fichier indexé passe par `delete_by_path` et enlève disque + DB; celle d'un non-indexé supprime le fichier directement.

## 4. Historique

### 4.1 Sens réel

Historique affiche `SampleService.get_cached()` trié par `id` décroissant. Il correspond donc aux **fichiers ajoutés/indexés récemment selon l'ordre d'insertion DB**, quels que soient leur origine ou leur dernière écoute. Ce n'est pas un historique événementiel.

### 4.2 Cartes, pagination et performances

- Une carte `SampleCard` par élément de la page.
- 50 par page par défaut, paramétrable via `samplesPerPage`.
- Filtrage et tri sur la totalité du cache en mémoire, puis instanciation de la page seulement.
- Les cartes possèdent checkbox, nom, gamme, actions, player/seek et waveform potentiellement instanciable.
- Les vues cachées différencient les mises à jour et signatures inchangées pour éviter les refresh coûteux.

### 4.3 Multi-sélection

Les checkboxes alimentent `selected_ids`. Les actions de masse réelles sont : retirer de l'historique, supprimer, déplacer, normaliser. Les boutons de sélection portent sur les cartes actuellement instanciées, donc la page visible, pas toute la population filtrée. Il n'y a pas de Ctrl+clic/Shift+clic de plage ni de drag multiple.

### 4.4 Actions et effets

| Action | Disque | DB/cache | Confirmation |
|---|---|---|---|
| Normaliser | réécrit le fichier | métadonnées/durée rafraîchies indirectement | non |
| Ouvrir waveform | aucun | aucun | non |
| Renommer | renomme | met à jour path/name | non |
| Déplacer vers | déplace en thread | met à jour path | non |
| Retirer historique | conserve | supprime la fiche DB et cache | carte : non; masse : oui |
| Supprimer | supprime | supprime fiche/cache | la carte délègue sans boîte locale visible; masse : oui |

Le menu contextuel natif de la carte ajoute surtout « Ouvrir l'emplacement » et « Compatibles ». Le menu à trois points contient la liste ci-dessus.

### 4.5 Raccourcis

Haut/Bas, Gauche/Droite seek ±1 s, Espace, Shift+Espace restart, Ctrl+Droite waveform, Ctrl+R renommer, Ctrl+D supprimer, Ctrl+Shift+D retirer de l'historique.

## 5. Indexé

### 5.1 Fonction réelle

Indexé interroge la même liste de `Sample`, mais par scopes construits depuis les bibliothèques configurées : tout, racine, dossier récursif, externes. L'arbre est construit depuis les chemins DB, pas depuis un scan direct du disque.

### 5.2 Tableau et données

`QTableWidget`, huit colonnes, sélection simple, tri Qt activable : Nom, Gamme, Dossier, Racine, Date, Durée, Poids, Statut.

- Date : `DateTime` DB, affiché `jj/mm/aaaa hh:mm`; timestamp numérique seulement comme clé de tri cachée.
- Durée : secondes DB, déjà formatée par la présentation.
- Poids : octets filesystem, calculés dans un thread, affichés en Mo.
- Gamme : `detected_scale_label`, sinon `dominant_note`, sinon `-`.
- Racine : bibliothèque configurée contenant le chemin, sinon `Externes`.

Les captures montrant des valeurs scientifiques correspondent donc à une version antérieure ou à un chemin d'affichage qui n'est plus celui du tableau actuel.

### 5.3 Analyse musicale

`ScaleAnalysisService` maintient une file et un worker QThread. Il appelle le détecteur, puis écrit `analyzed_at`, note dominante, label/kind, confiance et gammes compatibles. `needs_analysis` dépend principalement de l'absence de `analyzed_at`; le batch inclut aussi les anciennes lignes sans `detected_scale_kind` pour backfill.

Un échec n'est pas persisté comme état spécifique : log + signal, puis le sample reste candidat à une relance.

### 5.4 Filtres et navigation

- Recherche et statut partagés quand Indexé est intégré à Réserve.
- Filtre propre « Toutes les gammes / Sans gamme / valeurs distinctes avec compteurs ».
- Filtre de compatibilités par intersection de listes JSON.
- Navigation gauche masquable et état persisté.
- Pas de pagination : toutes les lignes filtrées sont créées dans le `QTableWidget`.
- Largeurs : Nom et Dossier stretch; autres `ResizeToContents`. Pas de persistance des largeurs observée.

### 5.5 Inspecteur

`LibraryDetailWidget` est spécifique à Indexé mais réemploie une `SampleCard` et `ReserveActions`. Il affiche chemin, statut, root, dossier, date, durée, RMS, gamme/confiance/compatibles, provenance légère et player. Il peut ouvrir Waveform et le dossier.

Il est techniquement extractible, mais pas directement réutilisable pour un non-indexé : il suppose souvent un `Sample`/ID et une carte Historique. `DirectoryDetailWidget` est une seconde implémentation proche, fondée sur `ReserveEntry` et capable de non-indexé.

## 6. Recherche et filtres

La barre `ReservePane` affecte bien les trois vues. La logique textuelle commune `reserve_entry_matches_query()` cherche tous les mots en AND, sans casse, dans nom, chemin, dossier, racine, source, statut, note, gamme et compatibles.

Limites : pas de normalisation Unicode/accents, pas de tokenisation spéciale underscores/tirets, pas de debounce central. Chaque caractère peut reconstruire la liste/table. La recherche est en mémoire; aucune requête SQL paginée.

Le filtre « Tous les statuts » couvre uniquement les quatre états techniques de `ReserveEntry`, jamais `MaterialStatus`. Le filtre de gamme normalise listes/tuples/JSON, mais les libellés distincts sont triés lexicalement sans canonicalisation musicale ni migration des anciennes variantes.

## 7. Preview audio

### 7.1 Ce qui est commun

Toutes les vues convergent vers l'unique `AppContext.audio_player`, fondé sur `pygame.mixer.music`. Lancer un nouveau sample remplace la lecture précédente. Il expose play/pause, seek, position, chemin, durée et nettoyage.

### 7.2 Ce qui reste dupliqué

- Dossiers : ligne avec slider + timer et `ReserveActions`.
- Historique : `SampleCardPlayback` par carte, timer/état de carte.
- Indexé : inspecteur contenant une `SampleCard`, raccourcis propres.
- Un ancien `DirectoryPreviewController` subsiste mais le flux vivant passe principalement par `ReserveActions`.

Mutualiser le moteur est déjà fait. Mutualiser l'UI/contrôleur de preview est réaliste, à condition de garder un adaptateur pour les fichiers sans ID et de ne jamais créer plusieurs propriétaires concurrents du même player.

## 8. Drag-and-drop et matière

### 8.1 Émissions

| Source | DragKind | MaterialStatus | Operation | Provenance |
|---|---|---|---|---|
| Dossiers indexé | `AUDIO_FILE` | `SOURCE` | `IMPORT` | chemin |
| Dossiers non indexé | `AUDIO_FILE` | `SOURCE` | `IMPORT` | chemin |
| Historique | `AUDIO_FILE` | `SOURCE` | `IMPORT` | chemin |
| Indexé | `AUDIO_FILE` | `SOURCE` | `IMPORT` | chemin |

Chaque source garde aussi URL locale et souvent l'ancien MIME `application/x-sample-card`, donc les destinations URL, Labo, Waveform, Compositeur, Bins, Artefacts et dossiers restent compatibles selon leurs accepteurs. Aucun de ces trois départs n'émet actuellement plusieurs items.

### 8.2 Import `DERIVED → SOURCE`

Le chemin fiable actuel est le drop sur `SampleListWidget` (Historique). `SampleListDragDrop` résout sélection/stem/artefact, détecte `MaterialStatus.DERIVED`, appelle `promote_to_source`, puis :

1. copie le rendu dans `%GenericData%/SampleRod/promoted_sources`;
2. produit un nom humain unique (`_02`, etc.);
3. crée un nouveau `Sample` sans muter le dérivé;
4. stocke provenance légère : ancien statut/kind, opération IMPORT, source connue et bornes;
5. lance normalisation automatique puis analyse de gamme;
6. émet les signaux du store.

Il apparaît immédiatement dans Historique et Indexé. Dans Dossiers, il n'apparaît que si l'utilisateur navigue jusqu'au dossier `promoted_sources`; il est classé `Externes` dans Indexé sauf si cette zone devient une bibliothèque configurée. Il est normalement très brièvement « À analyser », puis « Normal » au succès.

Dossiers possède parallèlement un ancien chemin d'import/copie (`DirectoryService.handle_drop`) pour URL, slice pickle et sample-card. Il crée aussi des `Sample`, mais il ne constitue pas le même contrat de promotion avec provenance. C'est un chemin concurrent à rationaliser avant une refonte DnD profonde.

## 9. Menus contextuels récapitulatifs

| Objet | Actions principales |
|---|---|
| Sous-dossier Dossiers | ouvrir par clic/double-clic/clavier; peu de menu métier |
| Fichier Dossiers | preview, renommer, compatibles, Labo, révéler, supprimer |
| Carte Historique | emplacement, compatibles; menu options : normaliser, waveform, renommer, déplacer, retirer fiche, supprimer fichier+fiche |
| Ligne Indexé | waveform, renommer, révéler, filtrer par gamme, retirer fiche, supprimer |
| Multi Historique | retirer fiches, supprimer, déplacer, normaliser |
| Multi Dossiers/Indexé | non supporté |

## 10. Fonctionnalités invisibles mais importantes

- Historique : concaténation conditionnelle de prises consécutives de l'enregistreur.
- Normalisation automatique des imports et manuelle/unitaire/de masse.
- Backfill d'analyse pour anciennes lignes incomplètes.
- Filtre « compatibles avec » partagé entre vues.
- Toggle global de visibilité du badge de gamme via `QSettings`.
- Navigation Indexé par racines, dossiers et « Externes ».
- Calcul asynchrone du poids et total visible/indexé.
- Mise à jour incrémentale des trois vues via signaux du store.
- Déplacement physique en thread avec arrêt préventif du player.
- Restauration du dernier dossier, racine et nœuds développés.
- Support des fichiers non indexés dans preview, drag, renommage et Labo.
- Compatibilité MIME historique conservée en parallèle du nouveau payload.
- Waveform inline encore possible dans certaines cartes/composants, avec nettoyage explicite des timers.
- Fichiers manquants conservés en DB et récupérables à la réindexation.

## 11. Fonctionnalités à préserver absolument

- Distinction suppression physique / désindexation.
- Non-indexés pleinement exploitables depuis Dossiers.
- Indexation récursive, incrémentale et récupération des fichiers revenus.
- Filtres communs et filtre de gamme/compatibilités.
- Preview global exclusif, seek et arrêt lors de suppression/déplacement/page.
- Tous les raccourcis répertoriés.
- Multi-actions Historique et pagination.
- Drag URL + anciens MIME + nouveau payload matière.
- Promotion dérivé vers nouvelle source autonome avec provenance légère.
- Navigation physique Dossiers distincte des scopes DB Indexé.
- Accès à `Externes` dans Indexé.
- Tri du tableau et clés numériques cachées.
- Signaux incrémentaux évitant un rebuild systématique.
- Gestion des fichiers manquants sans suppression automatique de la fiche.

## 12. Fonctionnalités probablement obsolètes ou redondantes

On peut l'affirmer uniquement pour :

- `_DirectoryEntriesWorker`, documenté comme code mort et non instancié;
- arbre Dossiers caché et plusieurs widgets stubs conservés pour compatibilité;
- `DirectoryPreviewController`, qui chevauche le flux vivant `ReserveActions` et doit être vérifié avant suppression;
- doubles implémentations d'inspecteur et de player visuel.

Le nom « Historique » est trompeur, mais la fonction n'est pas obsolète.

## 13. Dette technique et duplications

### Nécessaire pour la refonte

- Formaliser une interface de modèle/sélection commune autour de `ReserveEntry`.
- Centraliser le contrat des actions destructives avec libellés explicites : désindexer vs supprimer.
- Unifier le contrôleur de preview, tout en gardant des renderers par vue.
- Centraliser les formateurs date/durée/poids/statut.
- Clarifier un seul service d'import SOURCE et faire déléguer Dossiers/Historique vers lui.
- Séparer explicitement `MaterialStatus` et `ReserveTechnicalStatus` dans les noms/types UI.

### Facultatif

- Remplacer `QTableWidget` par `QTableView` + modèle custom.
- Réactiver un loader Dossiers par lots.
- Extraire une abstraction générique d'inspecteur.
- Ajouter un repository SQL séparé du `SampleService`.
- Nettoyer les stubs/arbre caché après vérification de compatibilité.

## 14. Performance

- Historique est le mieux borné visuellement : 50 cartes/page, mais filtre toute la liste en mémoire.
- Indexé crée une ligne `QTableWidget` par résultat : risque principal à plusieurs milliers/dizaines de milliers d'entrées.
- Dossiers crée un widget par entrée immédiate et liste synchroniquement : gros dossiers plats risqués.
- Le statut d'indexation rescane récursivement le disque et charge tous les `Sample` DB; il est debouncé à 180 ms mais reste coûteux.
- La recherche n'est pas debouncée et peut reconstruire sur chaque frappe.
- Le calcul du poids est correctement sorti du thread UI.
- Les refresh cachés et mises à jour rapides limitent déjà plusieurs coûts.
- Une refonte naïve en cartes pour Indexé serait nettement plus coûteuse que le tableau actuel.

## 15. Tests existants

### Bien couverts

- `test_reserve_entry.py` : projections, états et recherche commune.
- `test_directory_browser_service.py` : listing indexé/non indexé et description.
- `test_directory_indexing.py` : ajout, RMS, pending, missing/recovery et statut dossier.
- `test_directory_history.py` : persistance des chemins récents/ouverts.
- `test_library_service.py` : scopes et états.
- `test_reserve_dragdrop.py`, `test_source_promotion.py` : acceptation et promotion légère.
- Tests de layout partiels comme `test_library_detail_layout.py`.

### Critiques peu ou pas couverts

- Menus et raccourcis complets des trois vues.
- Sémantique disque/DB de chaque action destructive unitaire.
- Multi-sélection, sélection limitée à la page et actions bulk.
- Navigation breadcrumb/parent/sortie de racine.
- Gros volumes, recherche et temps de reconstruction.
- Exclusivité du player entre les trois vues.
- Drag sortant de chaque vue et compatibilité des destinations.
- Concurrence entre import Dossiers et promotion Historique.
- États d'échec analyse/indexation.
- Tri des huit colonnes et conservation de sélection lors d'un refresh.
- Affichage responsive futur.

## 16. Compatibilité avec la direction UX

| Proposition | Évaluation |
|---|---|
| Valeurs lisibles | **PEUT ÊTRE RÉUTILISÉ / ADAPTÉ** : le code actuel le fait déjà dans Indexé; centraliser les formateurs suffit. |
| Colonnes rationalisées | **PEUT ÊTRE ADAPTÉ** : tri conservable; masquer Racine/Poids est sûr si l'inspecteur les garde. |
| Index responsive tableau→liste | **DOIT ÊTRE CRÉÉ** : idéalement modèle partagé + deux vues; transformer dynamiquement le même `QTableWidget` serait fragile. |
| Inspecteur commun | **PEUT ÊTRE ADAPTÉ** à partir de `ReserveEntry` et `ReserveActions`, avec adaptateur `Sample` optionnel. |
| Historique compact | **PEUT ÊTRE ADAPTÉ**, mais préserver checkbox, pagination, actions bulk et concaténation. |
| Dossiers unifié | **EXISTE DÉJÀ EN PARTIE** : sous-dossiers et fichiers sont dans la même liste; breadcrumb interactif existe. |
| Badges d'états | **EXISTE ACTUELLEMENT** via `apply_status_badge`; harmonisation possible. |
| Barre de filtres structurée | **PEUT ÊTRE ADAPTÉE**, mais prévoir debounce et garder gamme/compatibilités distinctes. |

## 17. Contradictions et risques

| Problème | Pourquoi | Gravité | Solution possible |
|---|---|---:|---|
| « Historique » n'est pas un historique | retirer une entrée désindexe globalement | Haute | renommer ou expliciter l'action et son impact |
| Responsive Index avec deux widgets | sélection/tri/drag peuvent diverger | Haute | modèle et contrôleur de sélection partagés |
| Inspecteur commun | non-indexés n'ont pas de `Sample`/ID | Haute | inspecteur fondé sur `ReserveEntry`, actions selon capacités |
| Cartes partout | coût élevé pour milliers d'entrées | Haute | garder table/vue virtualisée pour Indexé |
| Retirer les players de cartes | peut casser seek/raccourcis/page | Moyenne | contrôleur global + mini-commandes par vue |
| Masquer Racine | information indispensable aux externes | Moyenne | conserver dans inspecteur/tooltip et colonne optionnelle |
| Fusionner Dossiers et Indexé | l'un reflète le disque, l'autre la DB | Critique | ne jamais fusionner leurs responsabilités |
| Statut ambigu | SOURCE n'est pas Normal | Critique | vocabulaire et composants visuels séparés |
| « Continuer » suggère une reprise | aucun checkpoint réel | Moyenne | libellé « Synchroniser » ou implémenter reprise |
| Import concurrent | provenance différente selon la zone | Haute | service unique d'import matériel |
| Recherche instantanée | rebuild à chaque frappe | Moyenne | debounce et modèles filtrables |

## 18. Architecture recommandée pour permettre la refonte

### EXISTE ACTUELLEMENT

- `ReserveEntry` comme DTO commun.
- `ReserveActions` comme début de façade d'actions.
- `SampleService` comme autorité DB/cache.
- lecteur global.
- statuts et formateurs partiellement communs.

### PEUT ÊTRE RÉUTILISÉ / ADAPTÉ

- Étendre `ReserveEntry` avec capacités calculées (`can_delete_file`, `can_unindex`, `can_analyze`, etc.), sans y mettre la logique.
- Transformer `ReserveActions` en façade explicite preview/navigation/actions non destructives.
- Ajouter un contrôleur de sélection par vue exposant un contrat commun, sans imposer la multi-sélection à Dossiers.
- Faire consommer un composant inspecteur par `ReserveEntry` et un fournisseur d'actions.
- Garder les renderers distincts : navigateur filesystem, timeline récente paginée, table/index.

### DOIT ÊTRE CRÉÉ

- `ReserveImportService` unique pour copier/promouvoir/indexer et persister la provenance.
- `ReserveMutationService` ou commandes explicites pour `unindex`, `delete_file_and_record`, `move`, `rename`.
- Un modèle Index virtualisable si le responsive et les gros volumes deviennent prioritaires.
- Un contrôleur de preview UI commun, au-dessus du player existant.
- Une nomenclature claire des deux axes de statut.

## 19. Ordre de travail recommandé avant le plan final

1. Verrouiller par tests la sémantique des suppressions, imports, raccourcis et sélections.
2. Renommer/documenter les concepts « Historique », « retirer » et les deux familles de statut.
3. Centraliser formateurs, capacités et commandes destructives sans changement visuel.
4. Unifier l'import et la promotion SOURCE.
5. Extraire le contrôleur de preview/inspecteur fondé sur `ReserveEntry`.
6. Refaire visuellement Dossiers et Historique en conservant leurs modèles.
7. Remplacer ou encapsuler le tableau Indexé par un modèle partageable avant le responsive.
8. Seulement ensuite établir le plan final de refonte visuelle et ses phases.

Ce document est une recherche préalable. Il ne constitue pas encore le plan final de refonte et aucune modification de production n'a été effectuée.
