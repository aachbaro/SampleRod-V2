# Plan final d’implémentation — refonte de la Réserve

## 0. Décisions structurantes

1. Les trois vues restent distinctes : **Dossiers = disque**, **Récents = ajouts DB récents**, **Indexé = interrogation analytique DB**.
2. `ReserveEntry` reste une projection/DTO. `SampleService`, la DB et le filesystem restent les autorités.
3. `MaterialStatus` et `ReserveTechnicalStatus` sont deux axes séparés dans le code, les filtres et les badges.
4. Le moteur audio reste exclusivement `AppContext.audio_player`. La refonte ajoute un contrôleur UI, jamais un second player.
5. Désindexation et suppression physique deviennent deux commandes, libellés et confirmations différents.
6. Les anciens MIME restent décodés. Tous les chemins convergent progressivement vers un seul service d’import.
7. `QTableWidget` est conservé pour la première refonte d’Indexé. Sa migration vers modèle virtualisable est une phase conditionnelle précédant seulement le responsive.
8. Aucun scan récursif décoratif n’est ajouté. Les compteurs de sous-dossiers restent absents tant qu’ils ne peuvent pas provenir d’un cache existant.
9. Les mises à jour incrémentales existantes sont préservées; les nouveaux contrôleurs ne doivent pas transformer chaque signal en reconstruction complète.

## 1. Architecture cible

```text
ReservePane
├── ReserveFilterController (recherche debouncée + état technique + compatibilité)
├── ReservePreviewController ──────────────→ AppContext.audio_player (unique)
├── ReserveSelectionState (contrat léger par vue)
├── ReserveInspector (ReserveEntry + capacités + preview)
├── Dossiers: DirectoryWidget / filesystem
├── Récents: SampleListWidget / cache DB récent paginé
└── Indexé: LibraryWidget / cache DB analytique
              └── [conditionnel] ReserveIndexModel → table + liste compacte

ReserveEntry (DTO)
├── ReserveTechnicalStatus
└── ReserveCapabilities (calcul pur, aucune mutation)

Commandes métier
├── ReserveMutationService
│   ├── unindex
│   ├── delete_file_and_record
│   ├── rename
│   └── move
└── ReserveImportService
    ├── import_source
    ├── import_derived_as_source
    └── copy_into_directory

Adaptateurs MIME historiques / nouveau DragPayload
→ décodage seulement
→ ReserveImportRequest
→ ReserveImportService
```

### 1.1 Responsabilités

#### `ReserveTechnicalStatus`

Enum ou `StrEnum` : `NORMAL`, `NON_INDEXED`, `NEEDS_ANALYSIS`, `MISSING`. Les sérialisations/valeurs restent `normal`, `non_indexed`, `needs_analysis`, `missing` pour ne pas casser filtres et tests. Les états transitoires « analyse en cours » et « erreur » restent des feedbacks UI séparés.

#### `ReserveEntry`

Projection commune d’un fichier ou d’un `Sample`. Elle ne lit ni n’écrit la DB et n’effectue aucune mutation. Elle expose les données disponibles et un objet de capacités calculées à partir de `indexed`, `missing`, `path`, `sample_id` et des métadonnées déjà connues.

#### `ReserveMutationService`

Façade métier étroite. Elle orchestre player, filesystem et méthodes existantes de `SampleService`. Elle retourne un résultat structuré; les dialogues restent dans l’UI. Elle ne reprend pas l’indexation, l’analyse ou l’import.

#### `ReserveImportService`

Contrat final unique d’import. Les adaptateurs MIME résolvent leurs payloads en requêtes typées puis délèguent. Le service réutilise `SampleService.add()` et `promote_to_source()` dans une première étape, avant de déplacer éventuellement la mécanique commune hors de ces méthodes.

#### `ReservePreviewController`

État UI commun au-dessus du player existant : entrée active, play/pause, seek, stop, interruption avant mutation, notification des renderers. Il accepte les entrées sans ID grâce à un identifiant stable de session dérivé du chemin.

#### `ReserveInspector`

Rendu fondé sur `ReserveEntry`, avec sections conditionnelles. Il n’instancie pas une `SampleCard` et n’invente aucune donnée absente. Il utilise le contrôleur de preview et les capacités pour afficher les actions disponibles.

#### `ReserveSelectionState`

Petit contrat signalant entrée courante et IDs cochés. Dossiers et Indexé restent en sélection simple; Récents conserve ses checkboxes. La future table/liste Indexé partage le même état.

## 2. Composants existants réutilisés

- `ReservePane` comme composition et propriétaire des services UI communs.
- `ReserveEntry` et ses constructeurs depuis `Sample`/`DirectoryAudioEntry`.
- `ReserveActions` comme façade transitoire; ses méthodes migrent progressivement vers preview/mutations.
- `SampleService` pour cache, DB, normalisation, analyse et signaux.
- `DirectoryService` pour listing et indexation récursive.
- `LibraryService` pour scopes racine/dossier/Externes.
- `AppContext.audio_player` comme moteur unique.
- `SampleListPagination`, `SampleListSelection` et les mécanismes de concaténation.
- `reserve_entry_matches_query()` et le matching AND actuel.
- Les clés de tri numériques de `LibraryWidget`.
- Les payloads `DragKind`, `MaterialStatus`, `MaterialOperation`, `DragProvenance`, `DropAction`.

## 3. Nouveaux fichiers envisagés

```text
frontend/reserve/
├── reserve_status.py
├── reserve_capabilities.py
├── reserve_formatters.py
├── reserve_preview.py
├── reserve_inspector.py
├── reserve_selection.py
├── reserve_filters.py
└── reserve_action_policy.py

backend/services/
├── reserve_mutation_service.py
└── reserve_import_service.py

frontend/library_gui/                 # phase responsive conditionnelle
├── reserve_index_model.py
├── reserve_index_table.py
└── reserve_index_compact_list.py
```

Les noms pourront être ajustés, mais pas les séparations de responsabilité.

## 4. Rétrocompatibilité

- Les chaînes de statut historiques restent identiques.
- Les fonctions exportées par `frontend.reserve.__init__` restent disponibles pendant la migration.
- `SampleService.removeFromHistory()` reste temporairement comme alias déprécié vers `unindex`, pour ne pas casser les signaux/anciens appels durant les commits intermédiaires.
- Les signaux `sampleRemovedFromHistory` restent émis pendant une période de transition; un nouveau signal `sampleUnindexed` peut être ajouté, puis les consommateurs migrés.
- URL locales, `application/x-sample-card`, `application/x-sample-slice-data` et payload moderne restent acceptés.
- `ReserveActions` conserve une API adaptatrice jusqu’à migration des trois vues.
- Les clés `QSettings` existantes de navigation, pagination et préférence de gamme sont conservées.
- La colonne DB `material_metadata` et son schéma de provenance légère ne changent pas.

---

# Phase A — Verrouillage des comportements

## Objectif

Créer un filet de non-régression avant toute centralisation ou modification visuelle.

## Fichiers créés

- `tests/test_reserve_mutation_semantics.py`
- `tests/test_reserve_shortcuts.py`
- `tests/test_reserve_preview_contract.py`
- `tests/test_reserve_recent_selection.py`
- `tests/test_reserve_index_interactions.py`
- `tests/test_reserve_drag_sources.py`

## Fichiers modifiés

Aucun fichier de production. Les fixtures de tests existantes peuvent être complétées.

## Classes / méthodes touchées

Observation/test uniquement : `SampleService.delete`, `delete_by_path`, `delete_record_by_path`, `removeFromHistory`, `move`, `rename`; `DirectoryNavigationController`; `SampleListSelection`; `LibraryWidget`; sources de drag des trois vues.

## Tests à écrire avant

- Désindexer conserve le fichier et supprime DB/cache.
- Supprimer retire fichier, DB et cache.
- Fichier manquant : désindexation possible, suppression sans erreur, pas de suppression d’un autre chemin.
- Non-indexé : suppression physique possible, désindexation indisponible.
- Arrêt du player avant suppression/déplacement.
- Breadcrumb, parent, sortie de `root_dir`, restauration d’un chemin valide/invalide.
- Raccourcis exacts des trois vues.
- Récents : sélection limitée aux cartes de page, bulk, pagination et concaténation.
- Preview exclusif entre vues et arrêt au changement de page.
- Indexé : tri numérique, gamme, compatibilité, Externes, sélection après refresh.
- Drag de Dossiers/Récents/Indexé : payload moderne + URL + MIME historique.
- Promotion dérivé : copie autonome et provenance légère.

## Implémentation

Construire des tests de service sans UI quand possible, puis des tests Qt `offscreen` ciblés pour raccourcis, sélection, menus et player. Capturer explicitement les comportements historiques discutables au lieu de les « corriger » dans cette phase.

## Tests après

Suite Réserve ciblée + tests existants directory/library/drag/source promotion.

## Critères d’acceptation

- Chaque différence désindexer/supprimer est prouvée.
- Les raccourcis et actions bulk ont au moins un test de routage.
- Aucun changement observable en production.

## Risques

Tests Qt fragiles à cause du focus. Protection : tester d’abord les handlers/controllers, puis un minimum d’intégration widget.

## Ce qui n’est volontairement PAS traité

Vocabulaire, architecture, UI, responsive et performance.

---

# Phase B — Vocabulaire, statuts, capacités et formateurs

## Objectif

Rendre les concepts non ambigus avant les changements visuels.

## Fichiers créés

- `frontend/reserve/reserve_status.py`
- `frontend/reserve/reserve_capabilities.py`
- `frontend/reserve/reserve_formatters.py`
- `frontend/reserve/reserve_action_policy.py`
- tests unitaires associés.

## Fichiers modifiés

- `frontend/reserve/reserve_entry.py`
- `frontend/reserve/__init__.py`
- `frontend/reserve/reserve_pane.py`
- `frontend/sample_gui/sample/sample_list_ui.py`
- `frontend/sample_gui/sample/sample_card_ui.py`
- `frontend/library_gui/library_widget.py`
- `frontend/right_panel/directory/directory_ui.py`

## Classes / méthodes touchées

- `resolve_reserve_status`, `reserve_status_label/tone`, constructeurs de `ReserveEntry`.
- `ReservePane._build_ui()` pour « Historique » → « Récents ».
- Menus/actions contenant « Retirer de l’historique ».
- `_format_created_at`, `_format_duration`, taille/RMS/gamme dans Indexé et détails.

## Tests à écrire avant

- Valeurs exactes et rétrocompatibles de `ReserveTechnicalStatus`.
- Matrice des capacités pour indexé, non-indexé, manquant, analysé.
- Date/durée/poids/RMS sans notation scientifique et clés de tri inchangées.
- Libellés « Désindexer » et « Supprimer le fichier » présents dans les menus.

## Implémentation

1. Introduire `ReserveTechnicalStatus` avec conversion transparente depuis/vers chaînes.
2. Garder les anciennes constantes comme alias pendant la migration.
3. Ajouter `ReserveCapabilities` pur. Aucun `os.remove`, aucune DB, aucun dialogue.
4. Ajouter `entry.capabilities` ou `capabilities_for(entry)`.
5. Centraliser les formateurs; les valeurs brutes restent attachées aux rôles Qt de tri.
6. Renommer l’onglet en **Récents**, avec sous-titre/tooltip « Samples ajoutés récemment à la Réserve ».
7. Remplacer tout wording « Retirer de l’historique » par **Désindexer** / **Retirer de l’index**.

## Tests après

Tests de formatage, statuts, capacités, menus et suite Phase A.

## Critères d’acceptation

- Aucun badge SOURCE répété dans la Réserve.
- Le badge permanent représente seulement l’état technique.
- `MaterialStatus` n’est importé par aucun module de statut technique.
- Récents ne prétend plus être un historique d’écoute.
- Tri date/durée/poids reste numérique.

## Risques

Comparaisons existantes chaîne/enum. Garde-fou : `StrEnum` ou migration par petites étapes avec alias.

## Ce qui n’est volontairement PAS traité

Sémantique backend de `removeFromHistory`, nouvelle UI des vues, nouveaux statuts persistants.

---

# Phase C1 — `ReserveMutationService`

## Objectif

Unifier la sémantique des mutations sans réécrire les opérations fiables de `SampleService`.

## Fichiers créés

- `backend/services/reserve_mutation_service.py`
- `tests/test_reserve_mutation_service.py`

## Fichiers modifiés

- `backend/models/AppContext.py` ou son bootstrap de services.
- `backend/services/sample_service.py` pour alias/signaux explicites minimaux.
- `frontend/reserve/reserve_actions.py`
- contrôleurs Dossiers, Récents et Indexé appelant directement le store.

## Classes / méthodes touchées

Nouveau :

```python
MutationResult(success, entry_id, old_path, new_path, error_code, message)
ReserveMutationService.unindex(entry)
ReserveMutationService.delete_file_and_record(entry)
ReserveMutationService.rename(entry, new_name)
ReserveMutationService.move(entry, target_folder)
ReserveMutationService.stop_preview_for(entry)
```

Réutilisation : `SampleService.delete`, `delete_by_path`, `delete_record_by_path`, `rename`, `rename_by_path`, `move`.

## Tests à écrire avant

Matrice complète filesystem/DB/cache/player pour chaque méthode et type d’entrée.

## Implémentation

- Pour une entrée indexée, déléguer aux méthodes ID du store.
- Pour une entrée non indexée, renommer/supprimer physiquement via une petite primitive sûre; `unindex` retourne `not_applicable`.
- Pour une entrée manquante, `unindex` retire la fiche; `delete_file_and_record` retire la fiche sans exiger l’existence du fichier.
- Arrêter le player si ID ou chemin correspondent.
- Retourner un résultat; ne jamais afficher `QMessageBox` dans le service.
- L’UI choisit une confirmation selon `ReserveActionPolicy` :
  - Désindexer : « Le fichier sera conservé ».
  - Supprimer : « Le fichier sera supprimé du disque ».

## Tests après

Phase A + tests service + intégration de chaque vue.

## Critères d’acceptation

- Même commande et même résultat depuis les trois vues.
- Désindexer ne peut jamais supprimer un fichier.
- Supprimer distingue clairement échec disque et échec DB.
- Aucun doublon de logique destructive nouveau.

## Risques

Rollback disque/DB et opérations asynchrones de déplacement. Garde-fou : conserver les transactions/rollbacks existants et envelopper, pas réimplémenter.

## Rollback

`ReserveActions` peut revenir temporairement aux appels directs grâce aux alias maintenus.

## Ce qui n’est volontairement PAS traité

Import, indexation, analyse, normalisation, refonte UI.

---

# Phase C2 — `ReserveImportService`

## Objectif

Faire converger tous les imports vers un contrat unique tout en conservant les formats historiques.

## Fichiers créés

- `backend/services/reserve_import_service.py`
- `frontend/reserve/reserve_import_adapters.py`
- `tests/test_reserve_import_service.py`

## Fichiers modifiés

- `backend/services/directory_service.py`
- `backend/services/sample_service.py`
- `frontend/sample_gui/sample/sample_list_dragdrop.py`
- `frontend/right_panel/directory/directory_dnd.py`
- `frontend/right_panel/directory/directory_list_widget.py`
- éventuellement `frontend/labo/audio_drop.py` pour réutiliser les résolveurs sans déplacer leur contrat.

## Classes / méthodes touchées

```python
ReserveImportRequest(paths, status, operation, provenance, destination, copy_policy)
ReserveImportResult(imported_samples, copied_paths, skipped, errors)
ReserveImportService.import_request(request)
ReserveImportService.import_source(...)
ReserveImportService.import_derived_as_source(...)
ReserveImportService.copy_into_directory(...)
```

## Tests à écrire avant

- URL externe, source existante, ancien sample-card, ancienne slice, sélection moderne, stem, artefact.
- Collision de nom.
- Dérivé copié sans mutation de l’original.
- Provenance légère inchangée.
- Réimport d’un chemin déjà indexé selon politique explicite.

## Implémentation

1. Les adaptateurs MIME ne font que résoudre des fichiers/payloads.
2. `SampleListDragDrop` délègue promotion et import standard au service.
3. `DirectoryService.handle_drop` devient adaptateur de compatibilité et délègue la copie finale.
4. Conserver `SampleService.promote_to_source()` comme primitive initiale; le nouveau service en devient l’appelant unique.
5. Une source déposée dans la Réserve sans destination physique explicite est indexée sur place; un dérivé est matérialisé dans le stockage durable.
6. Un drop dans Dossiers copie vers le dossier courant puis indexe le résultat.

## Tests après

Tous les tests DnD existants, promotion, import Dossiers et tests des destinations principales.

## Critères d’acceptation

- Un seul point décide copie/indexation/provenance.
- Les anciens MIME fonctionnent sans connaître le nouveau service côté source.
- Le nouveau sample apparaît dans Récents et Indexé; Dossiers reflète son dossier réel.
- Analyse et normalisation continuent via `SampleService.add()`.

## Risques

Double copie/double ajout. Garde-fou : identifiant de requête, normalisation de chemin et résultats explicites; tests de collision.

## Rollback

Conserver les anciens handlers derrière un feature flag interne le temps d’une version de validation.

## Ce qui n’est volontairement PAS traité

Nouvelle DB de provenance, parent IDs, suppression immédiate des MIME historiques.

---

# Phase D1 — Contrôleur de preview commun

## Objectif

Unifier l’état UI de lecture sans remplacer le moteur audio.

## Fichiers créés

- `frontend/reserve/reserve_preview.py`
- `tests/test_reserve_preview_controller.py`

## Fichiers modifiés

- `frontend/reserve/reserve_pane.py`
- `frontend/reserve/reserve_actions.py`
- `directory_item_widget.py`, `directory_selection.py`
- `sample_card_playback.py`, `sample_list_pagination.py`
- `library_widget.py`, `library_detail.py`

## Classes / méthodes touchées

```python
ReservePreviewController.play_pause(entry)
seek(entry, milliseconds)
restart(entry)
stop(entry=None)
interrupt_for_mutation(entry)
detach_renderer(owner_id)
activeEntryChanged
positionChanged
playbackStateChanged
```

## Tests à écrire avant

ID DB et entrée sans ID, exclusivité, changement de vue, page, suppression, déplacement, fichier manquant, renderer détruit.

## Implémentation

- Le contrôleur utilise `audio_player.toggle_play/seek_position/clear_audio`.
- Il génère un ID de session de chemin seulement pour les non-indexés.
- Les renderers s’abonnent par signal et déterminent s’ils représentent l’entrée active.
- `SampleListPagination` demande au contrôleur de stopper si l’entrée active sort de page.
- Les mutations appellent `interrupt_for_mutation`.

## Tests après

Preview des trois vues + raccourcis + mutations.

## Critères d’acceptation

- Une seule lecture globale.
- Aucun pointeur vers widget détruit.
- Seek et raccourcis inchangés.
- Non-indexés toujours lisibles.

## Risques

Boucles de synchronisation visuelle et IDs hash instables. Utiliser une clé normalisée explicite `(sample_id, path)` au lieu d’un lien permanent au widget.

## Ce qui n’est volontairement PAS traité

Waveform editing, changement de moteur, mixage simultané.

---

# Phase D2 — Inspecteur commun `ReserveEntry`

## Objectif

Fournir un inspecteur commun capable d’afficher indexé, non-indexé et manquant.

## Fichiers créés

- `frontend/reserve/reserve_inspector.py`
- `tests/test_reserve_inspector.py`

## Fichiers modifiés

- `reserve_pane.py`
- `directory_detail.py`
- `library_detail.py`
- `sample_list.py`

## Classes / méthodes touchées

`ReserveInspector.set_entry`, `clear_entry`, `set_mode(compact|expanded)`, actions par capacités; signaux `reserveEntrySelected` des trois vues.

## Tests à écrire avant

Rendu conditionnel pour non-indexé, analysé, manquant, provenance présente/absente; aucune création de `Sample` lors de l’inspection.

## Implémentation

Prendre `DirectoryDetailWidget` comme base conceptuelle, car il accepte déjà `ReserveEntry`. Réutiliser les formateurs et le contrôleur preview. Ne pas embarquer `SampleCard`. Brancher l’inspecteur au niveau `ReservePane`; les anciens détails restent adaptateurs pendant la migration puis sont retirés dans un commit séparé.

## Tests après

Sélection dans chaque vue, changements rapides, suppression de l’entrée active, layout étroit.

## Critères d’acceptation

- Non-indexé inspectable sans DB.
- Données absentes masquées, jamais inventées.
- Provenance légère visible en tooltip/section secondaire.
- Actions identiques aux capacités.

## Risques

Double inspecteur pendant transition. Garde-fou : un seul inspecteur visible dans `ReservePane`; anciens composants derrière adaptateurs.

## Ce qui n’est volontairement PAS traité

Historique graphique, édition de métadonnées, analyse embarquée complète.

---

# Phase E — Refonte Dossiers

## Objectif

Améliorer densité et lisibilité sans changer la nature filesystem de la vue.

## Fichiers créés

Éventuellement `frontend/right_panel/directory/directory_index_summary.py` pour isoler le composant de résumé.

## Fichiers modifiés

- `directory_ui.py`
- `directory_widget.py`
- `directory_navigation.py`
- `directory_list_builder.py`
- `directory_item_widget.py`
- `directory_list_widget.py`
- `directory_index.py`

## Classes / méthodes touchées

Breadcrumb, `update_index_chip`, `_refresh_index_status`, construction des lignes, menus et raccourcis.

## Tests à écrire avant

Snapshots structurels/visuels étroits, breadcrumb cliquable, parent, statut non-indexé, résumé exact, raccourcis sans barre permanente.

## Implémentation

- En-tête : bouton parent visible + breadcrumb compact.
- Ne pas ajouter précédent/suivant.
- Résumé : `8 934 fichiers audio · 680 indexés · 1 manquant` + bouton **Synchroniser**.
- Pendant indexation : `Synchronisation… 2 430 / 8 934`.
- Retirer `shortcuts_bar` permanent; ajouter bouton `?`/menu d’aide et tooltips.
- Garder sous-dossiers puis fichiers dans la même liste, avec séparateurs légers « Dossiers »/« Fichiers » qui ne sont pas sélectionnables.
- Lignes compactes : play, nom, gamme éventuelle, état technique, durée; commandes secondaires au menu.
- Aucun compteur de dossier nécessitant un scan récursif.
- Conserver sélection simple et construction actuelle; ne pas ajouter de cartes lourdes.

## Tests après

Navigation/indexation/non-indexé/drag/preview/menus/performance sur dossier synthétique important.

## Critères d’acceptation

- Non-indexé conserve toutes ses actions.
- Sortie de root possible.
- Aucun libellé « Continuer ».
- Aucun scan nouveau pour rendre la vue.
- La liste ne devient pas plus lourde qu’avant.

## Risques

Les séparateurs peuvent casser navigation clavier. Les créer sans flag `ItemIsSelectable` et tester Haut/Bas.

## Ce qui n’est volontairement PAS traité

Virtualisation, multi-sélection Dossiers, historique précédent/suivant.

---

# Phase F — Refonte Historique en Récents

## Objectif

Créer une liste récente compacte tout en conservant pagination, bulk et concaténation.

## Fichiers créés

Éventuellement `frontend/sample_gui/sample/recent_card_layout.py` pour le layout compact.

## Fichiers modifiés

- `sample_list.py`
- `sample_list_ui.py`
- `sample_list_cards.py`
- `sample_card.py`
- `sample_card_ui.py`
- `sample_card_playback.py`
- `sample_list_selection.py`

## Classes / méthodes touchées

Construction de carte, barre bulk, pagination, focus/raccourcis, slider actif.

## Tests à écrire avant

Checkbox, 50/page, sélection de page, bulk, concaténation, raccourcis et état du player actif.

## Implémentation

- Carte sur une ou deux lignes : checkbox, play, nom, gamme, durée, état, menu.
- Slider caché sur cartes inactives; pour l’entrée active, afficher une ligne minimale ou utiliser l’inspecteur. Choix retenu : **slider principal dans l’inspecteur, progression discrète uniquement sur la carte active**. Cela réduit la hauteur sans supprimer le seek global ni les raccourcis.
- Barre contextuelle visible si sélection : compteur + Normaliser/Déplacer/Désindexer/Supprimer.
- Texte « sélection de cette page » dans tooltip/aide.
- Pagination inchangée.
- Séparateurs Aujourd’hui/Hier/Cette semaine reportés à une sous-phase optionnelle : `created_at` est exploitable, mais ils compliquent pagination et navigation. Ne pas les inclure dans la première livraison.

## Tests après

Tests Phase A, layout étroit/large, pagination et bulk sur plusieurs pages.

## Critères d’acceptation

- 50/page toujours configurable.
- Aucun bulk perdu.
- Concaténation recorder intacte.
- Carte sensiblement moins haute.
- Désindexer et Supprimer impossibles à confondre.

## Risques

La logique `SampleCard` est très découpée. Limiter la phase au renderer et ne pas réécrire les contrôleurs métier.

## Ce qui n’est volontairement PAS traité

Virtualisation, groupement temporel initial, sélection inter-pages.

---

# Phase G — Rationalisation d’Indexé

## Objectif

Moderniser le tableau existant sans migration prématurée de modèle.

## Fichiers créés

Éventuellement `frontend/library_gui/library_columns.py` pour les descripteurs de colonnes.

## Fichiers modifiés

- `library_ui.py`
- `library_widget.py`
- `library_detail.py` (adaptateur vers inspecteur commun)

## Classes / méthodes touchées

`_configure_table`, `_build_row_items`, colonnes, menu de colonnes, sélection, drag et contexte.

## Tests à écrire avant

Tri de chaque colonne, rôles bruts, masquage/affichage de Racine/Poids, Externes, drag et menu.

## Implémentation

- Colonnes par défaut : Nom, Gamme, Dossier, Durée, Date, Statut.
- Racine et Poids disponibles via menu de colonnes; Racine reste dans inspecteur/tooltip.
- RMS et note dominante deviennent colonnes secondaires seulement si leurs données justifient l’usage.
- Statut sous forme de badge/délégué discret; ne pas colorer toute la ligne.
- Conserver `QTableWidget`, sélection simple, tri et rôles numériques.
- Persister seulement la visibilité des colonnes et éventuellement leur largeur, sous nouvelles clés versionnées.

## Tests après

Tri, filtres, refresh incrémental, Externes, sélection et gros jeu synthétique.

## Critères d’acceptation

- Tableau plus lisible sans perte de données.
- Tri numérique correct malgré format humain.
- Racine toujours accessible.
- Pas de grosses cartes.

## Risques

Le tri actif pendant les mises à jour incrémentales peut déplacer les lignes. Conserver les gardes existantes et restaurer par `sample_id`.

## Ce qui n’est volontairement PAS traité

Responsive automatique et remplacement par `QTableView`.

---

# Phase H — Modèle Indexé et responsive (conditionnelle)

## Déclencheur

Cette phase n’est engagée que si un benchmark montre un coût inacceptable du `QTableWidget` ou si la liste compacte responsive est validée comme exigence de la livraison suivante.

## Objectif

Partager données, tri, filtre et sélection entre tableau large et liste compacte.

## Fichiers créés

- `frontend/library_gui/reserve_index_model.py`
- `frontend/library_gui/reserve_index_table.py`
- `frontend/library_gui/reserve_index_compact_list.py`
- tests modèle/proxy/renderer.

## Fichiers modifiés

- `library_widget.py`
- `library_ui.py`
- `frontend/reserve/reserve_selection.py`

## Classes / méthodes touchées

`QAbstractTableModel`, éventuellement `QSortFilterProxyModel`, contrôleur de sélection par `sample_id`, bascule de renderer selon largeur avec seuil et marge.

## Tests à écrire avant

Parité table/liste : données, tri, filtre, sélection, drag, menu, clavier, preview; benchmarks 1k/10k lignes.

## Implémentation

- Extraire les données de `filtered_entries` dans un modèle.
- Table large en `QTableView`.
- Liste étroite en `QListView` ou `QTableView` à deux lignes avec délégué léger, jamais un widget par ligne.
- Sélection stockée par `sample_id`; mapper les index des deux vues.
- Bascule responsive avec hystérésis de largeur pour éviter le clignotement.
- N’activer qu’un renderer visible à la fois.

## Tests après

Parité fonctionnelle complète et mesures de temps/mémoire.

## Critères d’acceptation

- Aucune perte de fonction par rapport à Phase G.
- 10k entrées restent navigables sans création de 10k widgets.
- Sélection conservée à la bascule.
- Un seul drag/menu/contrôleur métier partagé.

## Risques

Phase à risque élevé. Développer derrière un feature flag `reserve_index_model_v2`; garder `QTableWidget` comme rollback jusqu’à validation manuelle.

## Ce qui n’est volontairement PAS traité

Multi-sélection Indexé, cartes riches, requêtes SQL serveur.

---

# Phase I — Recherche et filtres

## Objectif

Réduire les rebuilds et clarifier les filtres sans changer leur sémantique de base.

## Fichiers créés

- `frontend/reserve/reserve_filters.py`
- `tests/test_reserve_filter_controller.py`

## Fichiers modifiés

- `reserve_pane.py`
- `reserve_entry.py`
- contrôleurs de filtre des trois vues.

## Classes / méthodes touchées

`ReserveFilterController`, timer 200 ms par défaut, état de filtres, propagation uniquement si valeur effective différente.

## Tests à écrire avant

AND multi-mots, casse, chemins Windows, gamme/compatibilité, statut, un seul refresh après rafale de frappes.

## Implémentation

- Debounce 200 ms pour texte; statuts/chips restent immédiats.
- Conserver exactement le matching actuel dans la première sous-phase.
- Chips : état technique, gamme, compatibilité, scope actif; bouton Tout effacer.
- Ne pas ajouter de filtre `MaterialStatus`.
- Une amélioration Unicode/accents/underscores/tirets est une sous-phase optionnelle versionnée, avec tests de compatibilité.

## Tests après

Tests sémantiques et mesure du nombre de refresh sur rafale.

## Critères d’acceptation

- Résultats identiques à requête égale.
- Une rafale de frappe produit un refresh final par vue.
- Aucun scan/accès DB nouveau.

## Risques

Impression de latence. 200 ms est le compromis initial; rendre la constante centralisée et mesurable.

## Ce qui n’est volontairement PAS traité

FTS SQL, index de recherche, fuzzy search.

---

# Phase J — Nettoyage confirmé

## Objectif

Supprimer uniquement le code rendu inutile et prouvé sans références.

## Fichiers créés

Aucun.

## Fichiers modifiés

Selon audit : `directory_service.py`, `directory_ui.py`, `directory_widget.py`, `directory_preview.py`, anciens détails/player visuels.

## Classes / méthodes touchées

Candidates : `_DirectoryEntriesWorker`, arbre caché/stubs, `DirectoryPreviewController`, inspecteurs remplacés.

## Tests à écrire avant

Recherche de références, tests d’import modules, suite Réserve et démarrage minimal.

## Implémentation

Un commit par famille supprimée. Aucun nettoyage opportuniste mélangé à une phase UI.

## Tests après

Suite complète ciblée + smoke test application.

## Critères d’acceptation

Zéro référence vivante, zéro API externe cassée, réduction mesurable.

## Risques

Références dynamiques. Garde-fou : logs de dépréciation pendant une version avant suppression des adaptateurs.

## Ce qui n’est volontairement PAS traité

Refactor général backend ou renommage de modules sans bénéfice Réserve.

---

## 5. Dépendances et commits atomiques

```text
A tests
↓
B statuts/capacités/formateurs/wording
↓
C1 mutations ─────┐
C2 import ────────┤
                  ↓
D1 preview → D2 inspecteur
                  ↓
E Dossiers   F Récents   G Indexé
                         ↓
                    H responsive conditionnel
                  ↓
I filtres/recherche
↓
J nettoyage
```

Découpage de commits recommandé :

1. tests destruction; 2. tests interactions; 3. enum/alias; 4. capacités; 5. formateurs/wording; 6. service mutations; 7–9. migration de chaque vue; 10. contrat import; 11–12. adaptateurs moderne/historique; 13. preview controller; 14–16. renderers des vues; 17. inspecteur; 18. Dossiers UI; 19. Récents UI; 20. Indexé colonnes; 21. debounce; puis commits H/J séparés si validés.

### Comportement observable après chaque phase

| Phase | Comportement observable |
|---|---|
| A | Aucun changement; davantage de comportements sont verrouillés par tests. |
| B | Onglet « Récents », vocabulaire Désindexer/Supprimer, formats et badges cohérents. |
| C1 | Même résultat de mutation depuis les trois vues, avec confirmations uniformes. |
| C2 | Tous les drops/imports aboutissent par le même contrat, sans perte MIME. |
| D1 | Lecture et progression restent synchronisées lors du passage entre vues. |
| D2 | Un inspecteur commun affiche aussi les fichiers non indexés. |
| E | Dossiers devient plus dense; résumé humain et bouton Synchroniser. |
| F | Récents présente des cartes compactes et une barre bulk contextuelle. |
| G | Indexé montre les colonnes principales et garde les secondaires accessibles. |
| H | Si activée, bascule transparente tableau/liste compacte selon la largeur. |
| I | Recherche identique mais sans rebuild à chaque caractère; filtres plus lisibles. |
| J | Aucun changement fonctionnel; dette confirmée supprimée. |

## 6. Matrice finale des actions

| Type | Preview/drag/Waveform | Renommer | Déplacer | Désindexer | Supprimer fichier | Analyser | Confirmation |
|---|---|---|---|---|---|---|---|
| Filesystem non indexé | oui | filesystem | filesystem | non | fichier | non avant indexation | suppression physique |
| Filesystem indexé | oui | fichier + DB | fichier + DB | DB/cache, fichier conservé | fichier + DB | oui | wording distinct |
| Récents/Indexé normal | oui | fichier + DB | fichier + DB | DB/cache | fichier + DB | si candidat | wording distinct |
| À analyser | oui | fichier + DB | fichier + DB | DB/cache | fichier + DB | oui | wording distinct |
| Manquant | non pour audio; métadonnées visibles | selon recovery, sinon désactivé | désactivé | DB/cache | retire fiche, aucun fichier | non tant qu’absent | explicite |
| Multi Récents | selon entrée active | non en masse | oui | oui | oui | normaliser/analyser selon action | confirmation avec compte |

### Routage exact des commandes

| Action UI | Capacité | Commande cible | Filesystem | DB/cache | Confirmation |
|---|---|---|---|---|---|
| Preview | `can_preview` | `ReservePreviewController.play_pause` | lecture seule | aucun | non |
| Waveform/Labo | `can_open_waveform` | `ReserveActions.open_waveform/send_to_lab` | lecture seule | aucun | non |
| Renommer | `can_rename` | `ReserveMutationService.rename` | renomme | met à jour si indexé | non, erreur explicite |
| Déplacer | `can_move` | `ReserveMutationService.move` | déplace | met à jour si indexé | choix de destination |
| Désindexer | `can_unindex` | `ReserveMutationService.unindex` | conserve | supprime fiche/cache | oui, fichier conservé |
| Supprimer | `can_delete_file` | `ReserveMutationService.delete_file_and_record` | supprime si présent | supprime fiche si présente | oui, danger physique |
| Analyser | `can_analyze` | `SampleService.batch_analyze_*` ou enqueue ciblé | lecture audio | écrit analyse | non |
| Importer comme source | payload dérivé valide | `ReserveImportService.import_derived_as_source` | copie durable | nouvelle fiche | non, résultat visible |

Raccourcis conservés :

- Dossiers : Haut/Bas, Espace, Droite seek, Entrée Labo, Gauche parent, F2, Suppr.
- Récents : Haut/Bas, Gauche/Droite seek, Espace, Shift+Espace, Ctrl+Droite, Ctrl+R, Ctrl+D, Ctrl+Shift+D. Ce dernier devient visuellement/documentairement « Désindexer » sans changer la combinaison dans la première version.
- Indexé : mêmes raccourcis actuels que Récents pour preview/mutations.

## 7. Matrice des fonctionnalités préservées

| Fonction | Phase de verrouillage | Phase propriétaire | Résultat attendu |
|---|---|---|---|
| Non-indexé exploitable | A | E/D | aucun `Sample` requis |
| Désindexation conserve fichier | A | C1 | commande explicite |
| Suppression physique | A | C1 | commande distincte |
| Missing/recovery | A | E | indexation inchangée |
| Indexation incrémentale | A | E | bouton Synchroniser |
| Player exclusif | A | D1 | moteur inchangé |
| Pagination 50 | A | F | conservée |
| Bulk Récents | A | F/C1 | conservé |
| Concat recorder | A | F | conservée |
| Tri Indexé | A | G/H | rôles bruts |
| Externes | A | G/H | conservé |
| Gamme/compatibilité | A | G/I | conservées |
| URL/MIME historiques | A | C2 | adaptateurs |
| Payload moderne | A | C2 | natif |
| DERIVED→SOURCE | A | C2 | provenance légère |
| Recherche AND | A | I | identique + debounce |
| Raccourcis | A | E/F/G | aide déplacée, mapping gardé |
| Refresh incrémental | A | toutes | aucun rebuild global imposé |

## 8. Performance et garde-fous

- Benchmarks avant/après sur : dossier plat 1k/5k; Récents 5k en cache/50 visibles; Indexé 1k/10k.
- Instrumenter temps de construction, filtrage et signal incrémental sans laisser de logs verbeux permanents.
- Recherche : 200 ms et coalescence.
- Dossiers : aucun `os.walk` supplémentaire dans le rendu; statut récursif seulement dans le pipeline existant.
- Récents : 50 cartes maximum et aucune sélection globale implicite.
- Indexé : Phase H obligatoire avant liste responsive si le renderer compact doit coexister; délégués, pas widgets par ligne.
- Taille/poids reste dans le worker existant.
- Les signaux `sampleAdded`, `sampleRenamed`, `sampleMoved`, `sampleScaleAnalyzed` continuent d’emprunter les chemins rapides existants.

## 9. Rollback et feature flags

- C2 : ancien handler d’import disponible temporairement derrière flag interne.
- D1/D2 : `ReserveActions` et anciens détails restent adaptateurs jusqu’à validation des trois vues.
- H : flag explicite `reserve_index_model_v2`, ancien `QTableWidget` conservé jusqu’à parité.
- Les migrations QSettings utilisent de nouvelles clés; absence de clé retombe sur les valeurs actuelles.
- Aucune migration DB irréversible n’est nécessaire dans ce plan.

## 10. Vérification obligatoire

| Question | Réponse |
|---|---|
| Un fichier non indexé reste utilisable sans création de `Sample` ? | **Oui.** `ReserveEntry` et inspecteur fonctionnent sans ID; Dossiers garde preview, drag, rename, delete et Labo. |
| Désindexer conserve toujours le fichier ? | **Oui.** Contrat C1 et tests A l’imposent. |
| Supprimer reste distinct de désindexer ? | **Oui.** Méthodes, libellés, confirmations et résultats séparés. |
| Les fichiers manquants restent récupérables ? | **Oui.** Pipeline d’indexation/recovery inchangé. |
| Le player reste global et exclusif ? | **Oui.** D1 enveloppe uniquement `AppContext.audio_player`. |
| Les trois vues gardent leurs responsabilités distinctes ? | **Oui.** Aucun modèle filesystem/DB n’est fusionné. |
| Les bulk actions de Récents restent disponibles ? | **Oui.** F les rend plus visibles. |
| La pagination reste disponible ? | **Oui, 50/page.** |
| Le tri Indexé reste correct ? | **Oui.** Valeur brute séparée du texte; tests en A/G/H. |
| `Externes` reste disponible ? | **Oui.** Scope et racine dans inspecteur/colonne optionnelle. |
| Les anciens MIME restent supportés ? | **Oui.** Adaptateurs C2. |
| `DERIVED → SOURCE` reste fonctionnel ? | **Oui.** Service commun, copie autonome et provenance légère. |
| Recherche/filtres gardent leur sémantique ? | **Oui.** Matching AND inchangé avant amélioration optionnelle. |
| Les raccourcis sont préservés ? | **Oui.** Mappings verrouillés en A; seule l’aide visuelle change. |
| `MaterialStatus` reste distinct du statut technique ? | **Oui.** Types/modules/filtres séparés. |
| Aucun nouveau scan coûteux sur le thread UI ? | **Oui.** Aucun compteur décoratif récursif; workers existants conservés. |
| Le plan évite les rebuilds complets inutiles ? | **Oui.** Signaux rapides conservés, debounce et modèles conditionnels incrémentaux. |

Toutes les réponses sont positives; aucune dérogation ne nécessite de validation préalable supplémentaire.

## 11. Point d’arrêt

Ce document est le plan final d’implémentation. Aucune phase n’est commencée et aucun fichier de production n’est modifié. L’implémentation doit attendre une validation explicite, idéalement phase par phase, en commençant par A uniquement.
