# Recherche préalable — refonte du module Artefacts

Date de l'audit : 17 août 2026. Aucun code de production n'a été modifié.

## 1. Conclusion fonctionnelle

Le module Artefacts est actuellement un **plateau de transit en mémoire pour fichiers audio**, à mi-chemin entre un staging de résultats du Labo et un presse-papiers audio. Ce n'est ni une collection persistante, ni un historique fiable de transformations.

Une fiche `LabArtifact` peut représenter un résultat temporaire ou un fichier déjà durable. Le registre disparaît au redémarrage, même lorsque les fichiers pointés restent sur disque. La sémantique varie selon l'action : sauvegarder copie et conserve la carte ; glisser-déposer hors du plateau cherche au contraire à déplacer la matière et retire la carte.

L'idée future de **plateau de validation des transformations** est compatible avec une grande partie de l'existant, mais contredit directement la sémantique destructive du drag sortant et exige de clarifier la persistance et la suppression avant une refonte visuelle.

## 2. Architecture actuelle et autorités

| Couche | Fichiers/classes | Autorité réelle |
|---|---|---|
| Modèle | `frontend/labo/lab_artifact.py` — `LabArtifact` | Structure de la fiche uniquement |
| Registre | `frontend/labo/artifact_store.py` — `LabArtifactStore` | Source de vérité de la session courante |
| Vue | `frontend/labo/artifact_tray.py` — `ArtifactTrayWidget`, `ArtifactTrayRow` | Projection du store, plus logique de preview et de drag |
| Module | `frontend/modular/artifact_module.py` — `ArtifactModule` | Adaptateur modulaire autour du plateau |
| Labo classique | `frontend/labo/labo_widget.py` — `LaboWidget` | Orchestration historique autour du même store |
| Cycle modulaire | `frontend/modular/window_manager.py` | Relais des `artifactCreated` vers le store et ouverture automatique du module |
| DnD commun | `frontend/dragdrop/*`, `frontend/labo/audio_drop.py` | Contrat moderne et résolution vers chemins audio |
| Réserve | `reserve_import_adapters.py`, `ReserveImportService` | Autorité sur ARTIFACT → SOURCE |
| Bins | `frontend/labo/bins_panel.py` | Autorité sur le déplacement physique vers un dossier-bin |

Flux principal :

```text
outil de transformation
→ LabArtifact créé par le producteur
→ signal artifactCreated
→ WindowManager ou LaboWidget
→ LabArtifactStore.upsert()
→ artifactUpserted
→ ArtifactTrayWidget.upsert_artifact()
→ ArtifactTrayRow
→ preview / rename / save / open / delete / drag
```

Le store est bien partagé entre le Labo classique et le module modulaire via `ensure_lab_artifact_store(app_context)`. Le module est singleton (`multi=False`), non créable manuellement depuis le workspace, non renommable et non duplicable.

## 3. Modèle de données réel

`LabArtifact` est une dataclass Python `slots=True`, sans table DB et sans sérialisation :

| Champ | Rôle |
|---|---|
| `artifact_id: str` | Identité de session ; UUID le plus souvent, ID déterministe pour certains mixes |
| `kind` | `slice`, `current_file`, `stem`, `break_preview`, `break_pattern` |
| `display_name` | Nom humain de la carte et base du nom d'export |
| `source_path` | Fichier d'origine ou source conceptuelle |
| `temp_path` | Fichier actif prioritaire lorsqu'il existe |
| `start_time`, `end_time` | Bornes uniquement pour certaines sélections Waveform |
| `duration` | Durée stockée dans la fiche |
| `persisted` | Indique qu'une copie a été sauvegardée ; ne signifie pas que la fiche survivra au redémarrage |
| `origin` | Chaîne historique décrivant le producteur |
| `parent_ids` | Lignée légère historique, très peu alimentée |
| `operation` | Opération historique, chaîne non normalisée avec `MaterialOperation` |
| `sample_rate` | Présent selon le producteur |
| `metadata` | Dictionnaire libre propre au type |

Le statut moderne `MaterialStatus.ARTIFACT` n'est **pas stocké dans `LabArtifact`**. Il est reconstruit lors du drag. `kind`, `operation`, `origin`, `parent_ids` et `metadata` forment donc un ancien modèle parallèle à `DragKind`, `MaterialOperation` et `DragProvenance`.

`artifact_file_path()` choisit `temp_path` avant `source_path`. La carte représente donc une fiche Python plus une référence vers un fichier audio ; elle ne contient pas l'audio.

## 4. Types et producteurs

| Type réel | Producteur | Fichier | Métadonnées distinctives | Persistance initiale |
|---|---|---|---|---|
| Slice Waveform | `WaveformToolWidget.create_selection_artifact()` | WAV temporaire de la sélection éditée | bornes, sample rate | `False` |
| Capture Waveform | `create_current_file_artifact()` | WAV temporaire de l'état édité complet | sample rate | `False` |
| Mix de stems | `StemSessionWidget._emit_mix_artifact()` | WAV dans `%TEMP%/SampleRod/stem_mix` | `workspace_dir` | `False` |
| Preview quantifiée | `BreakQuantizeController` | rendu temporaire | BPM source/cible, division, force | `False` |
| Pattern Break | `BreakGeneratorExport` | rendu temporaire | BPM, tail, seed, bars, event count | `False` |
| Plage de pattern | même producteur | segment temporaire | ci-dessus + `start_step/end_step` | `False` |
| Fichier déposé | `LabArtifactStore.import_paths()` | fichier original durable | aucune provenance structurée | `True` |

Les stems individuels sont des `StemTile` de statut `DERIVED`, pas des artefacts. Une tuile possède un bouton/signal `artifactRequested`, mais `StemSessionWidget.populate_stems()` ne connecte pas ce signal. Seul le mix final est actuellement converti en `LabArtifact`. C'est soit une fonctionnalité inachevée, soit du code devenu orphelin.

Compositeur ne produit actuellement aucun `LabArtifact`. Réserve, Bins et fichier externe peuvent entrer dans le plateau par drop, mais deviennent des `current_file` persistés, quelle que soit leur sémantique d'origine.

## 5. Création et drop entrant

### Création native

Chaque outil construit directement `LabArtifact`. Il n'existe pas de factory centrale, de validation uniforme ni de normalisation de provenance. Les producteurs choisissent eux-mêmes ID, nom, champs et métadonnées.

### Drop vers Artefacts

Le plateau accepte URL audio, ancien sample-card, ancienne slice matérialisée en WAV, MIME artefact et payload moderne tant que `resolve_audio_drop_paths()` obtient un fichier.

Après résolution, `LabArtifactStore.import_paths()` :

- déduplique par chemin actif normalisé ;
- réutilise la fiche existante si le chemin est déjà présent ;
- sinon crée un `kind="current_file"`, `persisted=True`, `origin="artifact_tray_drop"`, `operation="manual_drop"` ;
- ne copie pas le fichier ;
- ne transfère pas les bornes, le statut, l'opération moderne ou la provenance du payload dans la fiche.

Conséquences par statut :

| Entrée | DropAction annoncé | Résultat réel |
|---|---|---|
| `DERIVED` | `CREATE_ARTIFACT` / « Conserver cette transformation » | Nouveau `current_file` pointant vers le fichier matérialisé ; provenance moderne perdue |
| `SOURCE` | `CREATE_ARTIFACT` | Nouveau `current_file` pointant sur la source elle-même, sans copie |
| `ARTIFACT` différent | `CREATE_ARTIFACT` | Réutilisation si même chemin, sinon nouvelle fiche simplifiée |
| même `ARTIFACT` sur son plateau | refus | No-op ; protège contre la disparition observée auparavant |

La logique conceptuelle `DERIVED → CREATE_ARTIFACT → ARTIFACT` existe au niveau du contrat DnD, mais le modèle stocké ne conserve pas explicitement cette transition.

## 6. Stockage et persistance

`LabArtifactStore._artifacts` est un dictionnaire mémoire. Il n'est sauvegardé ni en DB, ni JSON, ni QSettings. QSettings mémorise seulement le dernier dossier d'export (`labo_last_artifact_dir`).

- Fermer/masquer la fenêtre Artefacts : les fiches restent dans le store.
- Fermer le Labo classique : les fiches restent si l'`AppContext` et son store vivent encore.
- Fermer Samplerod : toutes les fiches sont perdues.
- Redémarrer : aucune reconstruction depuis les fichiers persistés ou temporaires.
- Changer de workspace dans la même session : store global partagé ; pas de collection propre au workspace.

Les fichiers peuvent survivre indépendamment : sources durables, workspace stems configuré, copies sauvegardées, et fichiers `%TEMP%`. Le ménage de démarrage limite certains dossiers temporaires et supprime les fichiers âgés de plus de sept jours ; il ne connaît pas de fiches restaurables à protéger.

`persisted=True` signifie seulement « une sauvegarde a eu lieu » ou « le drop venait déjà d'un fichier », pas « cette entrée est persistée ».

## 7. Carte et preview

Une `ArtifactTrayRow` contient : bouton play, badge de kind, nom, slider, temps et bouton ✕. Le tooltip contient nom, stem éventuel, source, durée, statut temporaire/persisté, matière ARTIFACT, opération, origine et chemin.

Responsive : sous 390 px le slider disparaît ; sous 320 px le temps disparaît. Le bouton play, le kind et la suppression restent. Chaque carte est un QWidget complet avec six widgets principaux.

Preview :

- utilise bien `AppContext.audio_player`, donc pas de second moteur ;
- implémente sa propre couche de contrôle dans `ArtifactTrayWidget`, distincte de `ReservePreviewController` ;
- play/pause via `toggle_play`, seek en direct ;
- exclusivité par comparaison du chemin et `clear_audio()` si un autre fichier joue ;
- ID numérique dérivé de `hash(("artifact", artifact_id))`, instable entre processus mais seulement utilisé en session ;
- un timer par plateau interroge le player toutes les 100 ms et parcourt toutes les cartes ;
- suppression/rename arrête le player si le chemin actif correspond ;
- aucun arrêt explicite au début du drag ; le retrait final passe par le store et arrête si nécessaire.

Le Labo classique et le module modulaire peuvent chacun instancier un plateau et donc chacun son timer, tout en observant le même store/player.

## 8. Sélection et navigation

Il n'existe aucune sélection de cartes : `QListWidget.SelectionMode.NoSelection`.

- pas de checkbox ;
- pas de Ctrl/Shift-clic ;
- pas de multi-sélection ni drag multiple ;
- pas de Ctrl+A ;
- pas de navigation Haut/Bas explicitement gérée ;
- pas d'actions groupées ;
- le clic sert surtout à initier un drag ou à manipuler les contrôles.

Une comparaison A/B ne peut donc pas s'appuyer sur une sélection existante.

## 9. Actions, menus et interactions invisibles

| Interaction | Effet réel |
|---|---|
| Play | lecture/pause avec le player global |
| Slider | seek continu |
| Double-clic carte | ouvre le fichier actif dans Waveform |
| Double-clic nom | dialogue de renommage |
| Clic ✕ | retire la fiche et demande la suppression du `temp_path` sans confirmation |
| Clic droit | lire/stopper, Waveform, renommer, sauvegarder sous, révéler dossier, supprimer |
| Drag | MIME artefact + URL + DragPayload moderne |
| Header ▼ | replie/déplie la liste |
| Drop sur plateau | importe le chemin comme artefact |

Il n'y a aucun raccourci clavier propre au module, aucun menu trois-points, aucune toolbar, aucun export direct autre que « Sauvegarder sous… », et aucune action directe Stem Lab/Break/Compositeur/Bins/Réserve. Ces destinations sont atteintes par drag grâce à l'URL locale et au MIME commun.

## 10. Renommage

`LabArtifactStore.rename_artifact()` arrête d'abord la preview.

- si `temp_path` existe : renomme physiquement le fichier temporaire avec `os.rename()` ;
- sinon : appelle `sample_store.rename_by_path()` sur le fichier actif, donc peut renommer une source durable ;
- met à jour `display_name`, `temp_path` ou `source_path`, et parfois `metadata.saved_path` ;
- émet `artifactFileRenamed` pour permettre à des modules ouverts de suivre le chemin.

Risques : pas de validation partagée des caractères, pas de politique de collision explicite (`os.rename` peut échouer/écraser selon plateforme), exceptions filesystem non transformées en résultat structuré, et une simple fiche importée peut renommer le fichier source réel. Les références non connectées à `artifactFileRenamed` peuvent devenir obsolètes.

## 11. Suppression

`remove(id, delete_from_disk)` retire toujours la fiche du dictionnaire puis :

- arrête la preview correspondante ;
- si `delete_from_disk=True`, supprime **uniquement `temp_path`** ;
- ne supprime jamais `source_path` ni `metadata.saved_path` ;
- n'affiche aucune confirmation.

Ainsi, « Supprimer l'artefact » signifie en pratique : retirer la carte et supprimer son rendu temporaire s'il y en a un. Pour un artefact importé/persisté sans `temp_path`, le fichier durable reste. L'UI ne rend pas cette différence visible.

## 12. Drag sortant et destinations

Le payload sortant contient un item, `DragKind.ARTIFACT`, `MaterialStatus.ARTIFACT`, `source_module="artifacts"` et une provenance reconstruite avec `source_path` + `ARTIFACT_CREATION`. Il ne transporte pas `origin`, metadata, bornes, kind réel ni parent_ids.

| Destination | Action | Effet sur destination | Effet sur artefact source |
|---|---|---|---|
| Waveform | `OPEN` | ouvre le même fichier | la carte est ensuite retirée selon le résultat Qt du drag |
| Stem Lab | `SEPARATE_STEMS` | utilise le même fichier comme entrée | idem |
| Break | `LOAD_BREAK` | charge le même fichier | idem |
| Compositeur | `ADD_TO_COMPOSITION` | ajoute/rend un clip selon son propre import | idem |
| Mixer stems | `ADD_TO_MIX` | ajoute le chemin | idem |
| Bin | `MOVE_TO_BIN` | déplace physiquement le fichier vers le dossier | store retiré sans deuxième suppression si MoveAction |
| Réserve | `IMPORT_AS_SOURCE` | indexe sur place ou copie selon cible, nouveau statut SOURCE | le drag CopyAction peut ensuite supprimer le `temp_path` original |
| Explorateur | URL locale | comportement Qt/OS | résultat CopyAction peut supprimer le temporaire |

La source de drag demande `MoveAction | CopyAction`. Si la cible retourne Move, la fiche est retirée sans supprimer à nouveau. Si elle retourne Copy, la fiche est retirée **et son `temp_path` supprimé** pour simuler un déplacement. Ce comportement est le principal conflit avec un plateau de validation/réutilisation.

## 13. Relation avec Bins

Un Bin est un raccourci persistant vers un dossier, pas un stockage logique et pas une collection de références. Les Bins sont persistés en JSON dans QSettings, mais leur contenu est le contenu réel des dossiers.

Artefact → Bin déplace le fichier physique avec `shutil.move`. L'artefact n'est pas copié, ne peut pas être dans plusieurs Bins et disparaît du store après le drag. Le Bin ne stocke aucune metadata/provenance et ne connaît pas la notion « classé ». Si le fichier était indexé, le chemin moderne devrait passer par `SampleService`; la branche artefact non trackée déplace directement et signale seulement les anciens chemins.

## 14. Relation avec Réserve

Le chemin moderne est confirmé :

```text
ARTIFACT
→ import_request_from_mime()
→ ReserveImportRequest(status="artifact")
→ ReserveImportService
→ Sample avec material_status=SOURCE
```

Sans destination, un fichier durable est indexé sur place sans copie. Avec destination Dossiers, il est copié avec suffixe `_1`, `_2`, etc., puis indexé. Le nouvel objet reçoit une provenance légère : `previous_status=artifact`, `previous_kind=artifact`, `operation=import`, `source_path`.

L'objet `LabArtifact` n'est pas muté par le service. Cependant, le protocole de drag de la carte retire ensuite l'artefact et peut supprimer son fichier temporaire. La promotion conceptuelle et la conservation de la carte ne sont donc pas indépendantes aujourd'hui.

## 15. Provenance

Standardisé dans le drag : statut ARTIFACT et provenance légère. Historique dans la fiche : `origin`, `operation`, `parent_ids`, metadata et parfois bornes.

Pertes constatées :

- drop entrant vers Artefacts aplatit tout en `current_file` ;
- drag sortant n'exporte pas kind réel, metadata, bornes, origin ou parents ;
- rename conserve la fiche mais ne réécrit pas `source_path` de provenance dans metadata ;
- sauvegarde conserve la fiche et ajoute seulement `saved_path` ;
- Réserve conserve la provenance du DragPayload, qui est plus pauvre que la fiche originale.

Il existe donc deux provenances parallèles et aucune conversion complète entre elles.

## 16. Performance mesurée

Mesure offscreen locale, widgets réels, fichiers manquants :

| Volume | Construction d'un plateau complet | Synchronisation preview (un passage) |
|---:|---:|---:|
| 10 | 0,017 s | 0,02 ms |
| 100 | 0,157 s | 0,14 ms |
| 500 | 0,965 s | 0,66 ms |
| 1000 | 2,548 s | 1,42 ms |

La création est linéaire et non virtualisée. Le timer à 10 Hz est également O(n), soit environ 14 ms/s à 1000 cartes dans ce test, hors peinture et accès audio. À 10–100, l'architecture est acceptable. À 500, l'ouverture devient perceptible. À 1000, widgets, layout, scroll et refresh complet deviennent inadaptés. `set_artifacts()` détruit et recrée toute la liste ; les upserts unitaires restent moins coûteux.

## 17. Tests existants

55 tests ciblés liés à ce périmètre sont verts.

Bien couvert : labels/modèle de base, choix `temp_path`, badge/tooltip minimal, responsive étroit, statut/payload moderne, descriptions de DropAction, rejet d'un auto-drop, promotion ARTIFACT → SOURCE, collisions Réserve, export de plage Break et priorité de rendu.

Critique mais peu ou pas couvert : store complet, persistance de session, save, rename filesystem et collisions, suppression temp/source, drag Copy/Move destructif, drop entrant et perte de provenance, ouverture Waveform, preview/seek/exclusivité, deux plateaux simultanés, artefact → Bin, artefact → Composer/Stem/Break, fermeture, fichiers manquants, nettoyage temporaire, gros volumes et signal stem individuel non connecté.

## 18. Duplications et dette

### À résoudre avant refonte

- création de `LabArtifact` dispersée entre producteurs ;
- modèle de provenance historique parallèle au modèle matière moderne ;
- sémantique destructive dans la vue (`ArtifactTrayRow._start_drag`) ;
- preview contrôlée par le widget plutôt que par un contrôleur commun ;
- rename/suppression sans résultat structuré ni politique explicite ;
- statut `persisted` ambigu ;
- drop entrant qui perd le type et la provenance ;
- aucune persistance du registre.

### Dette facultative

- formatteurs type/durée propres au module ;
- deux orchestrateurs minces (LaboWidget et ArtifactModule) ;
- timer de polling plutôt que signaux du player ;
- anciens commentaires disant qu'un artefact « ne vit qu'à un seul endroit ».

## 19. Fonctionnalités à préserver absolument

- store central partagé entre vues classique et modulaire ;
- upsert par ID et signaux d'ajout/retrait/rename ;
- fichiers édités réellement matérialisés, pas simple référence à la source ;
- preview globale exclusive, play/pause et seek ;
- ouverture Waveform ;
- sauvegarde avec collision sûre et indexation ;
- renommage avec suivi du chemin dans les modules connectés ;
- drag moderne + MIME artefact + URL locale + anciens formats ;
- auto-drop refusé ;
- support des cinq kinds actuels et de leurs metadata ;
- responsive minimal ;
- tooltip riche ;
- ARTIFACT → Réserve → SOURCE avec provenance légère ;
- Bins comme dossiers réels ;
- ouverture automatique du singleton Artefacts lorsqu'un producteur modulaire crée un résultat.

## 20. Code ou comportement probablement obsolète/inachevé

- `parent_ids` existe mais aucun chaînage réel n'a été trouvé dans les producteurs audités.
- Le signal/bouton `StemTile.artifactRequested` n'est pas connecté dans `StemSessionWidget.populate_stems()` ; l'intention « envoyer un stem aux artefacts » n'aboutit pas par ce chemin.
- `persisted` et le libellé « Persiste » suggèrent une persistance de fiche inexistante.
- La doctrine « un artefact ne vit qu'à un seul endroit » dans le drag est en contradiction avec les nouveaux statuts matière et avec la Réserve.

À confirmer par tests avant toute suppression.

## 21. Compatibilité avec le plateau de validation

| Idée future | Évaluation |
|---|---|
| Écoute rapide | EXISTE DÉJÀ |
| Nommage | EXISTE, À SÉCURISER |
| Metadata utiles | EXISTENT MAIS DISPERSÉES |
| Provenance légère | PEUT ÊTRE ADAPTÉE |
| Comparaison de résultats | DOIT ÊTRE CRÉÉE |
| Drag vers modules | EXISTE, SÉMANTIQUE À CORRIGER |
| Rangement Bins | EXISTE COMME DÉPLACEMENT PHYSIQUE |
| Promotion Réserve | EXISTE DÉJÀ |
| Suppression claire | DOIT ÊTRE CRÉÉE |
| Collection persistante | DOIT ÊTRE CRÉÉE si souhaitée |

La carte compacte proposée est faisable : nom, kind, durée et source sont disponibles ; origine/opération peuvent aller en tooltip. Il faut toutefois définir une nomenclature humaine pour les kinds et opérations, et ne pas prétendre afficher une provenance fiable après un drop entrant tant que celle-ci est aplatie.

## 22. Comparaison A/B

Utile pour choisir entre stems, patterns ou rendus. Techniquement réaliste avec le player global, mais aucune sélection n'existe. Une première version pourrait conserver une `comparison_set` d'IDs de session, un index actif et une commande « suivant/précédent », sans second player. L'exclusivité actuelle est compatible. Il faudrait un contrôleur de preview hors du widget, des identités stables en session, et des règles sur seek commun, normalisation de niveau éventuelle et disparition d'un candidat. Un vrai A/B synchronisé temporellement serait nettement plus complexe et n'est pas justifié en première étape.

## 23. Contradictions et risques

| Problème | Pourquoi | Gravité | Solution possible |
|---|---|---:|---|
| Fiche temporaire mais statut « Persiste » | fichier et collection sont confondus | Haute | séparer durabilité du fichier et présence dans le plateau |
| Drag Copy détruit le temporaire | réutiliser devient déplacer | Critique | drag non destructif par défaut, action « ranger/déplacer » explicite |
| Suppression ambiguë | varie selon `temp_path` | Critique | deux commandes nommées et confirmation selon impact |
| Rename d'un import renomme la source | la carte paraît locale | Haute | rename fiche vs rename fichier séparés |
| Provenance aplatie au drop | perte de statut/kind/bornes | Haute | factory/import métier conservant DragPayload |
| Store non persistant | collection perdue au restart | Haute si « conservé » | store de session sérialisé et validation des chemins |
| Bins perdent metadata | déplacement de fichier brut | Moyenne | sidecar/DB ou promotion Réserve avant classement |
| Player dans la vue | double timer et couplage | Moyenne | `ArtifactPreviewController` partagé |
| Widgets non virtualisés | 2,5 s à 1000 | Moyenne | modèle/vue ou pagination si volume attendu |
| Collisions rename | politique absente | Haute | primitive structurée avec suffixe/refus explicite |
| Temp cleanup sans registre restauré | fichiers peuvent disparaître | Moyenne | ownership et protection explicites |

## 24. Architecture recommandée, sans plan d'implémentation

### Existe actuellement

- `LabArtifactStore` central ;
- `LabArtifact` ;
- contrats DnD modernes ;
- `ReserveImportService` ;
- player global ;
- plateau réutilisé dans deux hôtes.

### Peut être réutilisé/adapté

- `LabArtifactStore` comme façade publique, en séparant registre et stockage ;
- `LabArtifact` avec migration compatible ou adaptateur vers un modèle canonique ;
- `ArtifactTrayWidget` comme renderer temporaire ;
- `ReserveImportService` inchangé comme autorité de promotion ;
- `DragPayload` comme format d'échange canonique.

### Devrait être créé

- une factory/service de création/import d'artefacts, seul endroit convertissant `DragPayload` et producteurs ;
- un contrat explicite de durabilité (`temporary_file`, `durable_file`) distinct de la présence dans la collection ;
- un service de mutation avec résultats structurés pour rename/remove/save ;
- un `ArtifactPreviewController` au-dessus du player existant ;
- si la collection doit survivre : un store sérialisé versionné, séparé des layouts et validant les chemins au chargement.

### Facultatif

- sélection/comparaison A/B ;
- virtualisation ou pagination ;
- sidecars de provenance pour fichiers déplacés hors Réserve ;
- nettoyage/recovery avancé des temporaires.

## 25. Ordre de travail recommandé

Sans constituer encore un plan final :

1. décider la sémantique du plateau (conserver après drag, durabilité, session ou redémarrage) ;
2. verrouiller par tests rename, suppression, save, drag Copy/Move, Bins et Réserve ;
3. centraliser création/import et conversion de provenance ;
4. séparer mutations métier de la carte ;
5. centraliser la preview ;
6. seulement ensuite refaire les cartes et ajouter sélection/comparaison ;
7. ajouter une persistance versionnée uniquement si « conserver » doit survivre au redémarrage ;
8. traiter la virtualisation si le volume cible dépasse environ 100–200 artefacts.

## 26. Décisions nécessaires avant un plan final

1. Un artefact doit-il survivre au redémarrage, ou seulement à la session ?
2. Un drag sortant doit-il toujours conserver la carte ? Recommandation : oui.
3. « Supprimer » doit-il supprimer un rendu temporaire, un fichier durable, ou demander lequel ?
4. Renommer doit-il renommer seulement la fiche ou aussi le fichier ?
5. Ranger dans un Bin est-il un déplacement destructif ou une copie/classification ?
6. Les fichiers déjà durables déposés dans Artefacts doivent-ils devenir des artefacts ou rester des sources référencées ?
7. Faut-il restaurer les artefacts persistés dans le plateau au lancement ?
8. La comparaison vise-t-elle une écoute successive simple ou un A/B synchronisé ?

