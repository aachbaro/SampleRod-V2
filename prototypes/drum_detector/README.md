# Drum Detector / Break Generator

Ce document sert de vue d'ensemble du proto `drum_detector`.
L'idee n'est pas seulement de dire "comment le lancer", mais surtout
"comment il fonctionne", afin de pouvoir l'ameliorer plus facilement.

Le systeme couvre 4 blocs relies entre eux :

1. detection globale du sample (`one_shot`, `loop`, `drum`, `fx`, `break`, etc.)
2. detection / classification des hits individuels
3. extraction de sequences de hits reutilisables
4. generation d'un nouveau break a partir des hits et sequences detectes

## Objectif du proto

Le proto essaie de repondre a cette boucle de travail :

1. charger un sample ou un break
2. detecter des markers / slices pertinents
3. attribuer a chaque slice un type de hit exploitable
4. corriger manuellement si besoin
5. reutiliser ces slices pour:
   - preview un break retime / quantize
   - generer un nouveau pattern aleatoire
   - iterer rapidement sur les markers, labels et parametres

Autrement dit :

- l'analyse sert a "pecher" des materiaux jouables
- le generateur sert a recombiner ces materiaux sur une grille
- l'UI sert a faire le pont entre heuristiques automatiques et correction humaine

## Carte rapide des modules

- [analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py)
  coeur de l'analyse audio, segmentation, scoring des hits, roles
- [pattern_generator.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py)
  generation de breaks a partir des hits classes
- [preview.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py)
  rendu audio des previews retime, quantize et pattern
- [ui.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/ui.py)
  mini app PyQt qui expose l'analyse, l'edition et la generation
- [cli.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/cli.py)
  point d'entree CLI

## Flux global

Le flux complet ressemble a ca :

```text
audio source
  -> detection d'onsets / markers
  -> segmentation en hits
  -> scoring local de chaque hit
  -> rerank contextuel entre hits
  -> inference de labels secondaires / layering
  -> attribution d'un role musical
  -> extraction de sequences rythmiques
  -> correction manuelle eventuelle
  -> constitution de pools de slices et de sequences
  -> generation d'un nouveau pattern
  -> preview audio du resultat
```

## 1. Analyse globale du sample

Le point d'entree principal est `detect_drum_from_audio(...)` dans
[analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L276)
et la construction du resultat passe par
[analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L380).

Le sample est d'abord traite globalement :

- separation harmonique / percussive
- extraction de features globales
- estimation du tempo / pulse / regularite
- calcul d'un score de loop
- estimation de la famille generale:
  - `drum`
  - `tonal`
  - `fx`
  - `hybrid`

Ensuite le systeme choisit une forme :

- `one_shot`
- `loop`

Et en fonction de cette forme, il produit des candidats :

- pour un one-shot drum :
  - `kick`, `snare`, `closed_hat`, etc.
- pour une loop drum :
  - `break`, `drum_loop`, `top_loop`, `perc_loop`
- pour le non-drum :
  - candidats adaptes au profil `tonal/fx/hybrid`

Le resultat complet est stocke dans `DrumDetectionResult` dans
[analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L57).

## 2. Segmentation en hits

La segmentation se fait dans `_detect_transient_hits(...)` puis remonte dans
`_build_detection_result(...)`.

L'idee n'est pas de faire de la separation de sources. On ne "split" pas un
break en stems. On decoupe plutot le sample en segments temporels plausibles
autour des transients.

Chaque hit detecte devient un `TransientHit` dans
[analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L28)
avec :

- `start_s`, `end_s`
- `label`
- `confidence`
- ratios d'energie grave / medium / aigu
- `secondary_labels`
- `layer_score`
- `role`
- `rhythmic_position`

Ce point est important :

- un hit = une slice temporelle jouable
- mais cette slice peut deja contenir plusieurs couches sonores
- le systeme accepte donc qu'un hit ait un label principal + des labels secondaires
- il garde aussi la classe de sa position d'origine sur la grille source :
  - `downbeat`
  - `backbeat`
  - `offbeat`
  - `subdivision`

Depuis les dernieres iterations, cette segmentation ne suit plus seulement la
regle "un onset = une slice".

Elle ajoute aussi :

- une fusion de faux micro-splits
  - si un petit onset ressemble surtout a une queue de kick ou a un rebond
    tres faible, il peut etre refusionne avec le hit precedent
- une estimation de fin de hit adaptee au contenu
  - la fin n'est plus juste "au prochain onset"
  - elle depend aussi de l'enveloppe et de la bande dominante du transient
  - un hit grave peut donc vivre plus longtemps qu'un hat tres court
- un mode strict pour les markers manuels
  - lors d'un rebuild depuis markers, on garde volontairement les segments
    imposes par l'utilisateur sans leur reappliquer les heuristiques de merge

En pratique, `split_density` agit maintenant a deux niveaux :

- sur la detection d'onsets elle-meme
- sur le comportement de merge / detail de la segmentation

Donc un `split_density` bas ne veut plus seulement dire "moins d'onsets", mais
aussi :

- plus de tolerance vis-a-vis des micro-splits
- des slices un peu plus longues, surtout pour les hits graves

A l'inverse, un `split_density` eleve preserve davantage les petits details,
les hats serres et les sous-transients.

## 3. Classification locale des hits

Le scoring brut d'un hit se fait dans
[_score_hit_candidates(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1545).

Le systeme s'appuie sur un melange de features :

- duree / decay
- contenu spectral grave / medium / aigu
- bruit / flatness
- attaque
- centroid spectral
- indices lies au transient lui-meme

Le scoring ne regarde plus seulement "le segment" comme un bloc uniforme.
Il combine maintenant :

- des features de corps (`body`)
- des features d'attaque (`attack`)
- un hint d'onset
  - quelle bande semblait porter le transient (`low`, `mid`, `high`)
- un mini profil de transient
  - comment l'energie monte juste avant / juste apres le hit

Cette lecture en couches sert surtout a mieux separer les cas proches :

- `kick` vs faux micro-hit sur sa queue
- `snare` / `clap`
- `closed_hat` / `snare_ruff`
- `open_hat` / `crash`

En sortie, on obtient un score par label. Les labels actuellement supportes
par le proto sont aussi ceux exposes dans l'UI :

- `kick`
- `kick_ghost`
- `snare`
- `snare_ghost`
- `snare_ruff`
- `clap`
- `closed_hat`
- `open_hat`
- `crash`
- `ride`
- `tom`
- `perc`

## 4. Rerank contextuel entre hits

La classification ne se fait pas uniquement hit par hit.
Il y a une passe contextuelle dans
[_resolve_contextual_hits(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1000).

Cette passe compare les hits entre eux pour produire des decisions plus
coherentes a l'echelle du break.

Pourquoi c'est utile :

- les hits les plus graves / portants tendent a devenir les meilleurs candidats `kick`
- les hits plus mid/noisy tendent a etre rerankes vers `snare` / `clap`
- les hits tres aigus / courts tendent a mieux ressortir en `hat`
- les breaks repetitifs profitent d'une meilleure coherence interne

Cette passe contextuelle fait maintenant deux choses differentes :

1. un rerank structurel
   - rang relatif des graves / mids / aigus dans le break
   - prise en compte de la proximite rythmique
   - relecture `ghost` / `ruff` / `crash` / `ride` selon decay et contexte
2. un biais de similarite entre hits
   - chaque hit est compare aux autres sur une signature
     `body + attack + hint + transient`
   - si plusieurs hits tres similaires forment deja un petit cluster coherent,
     ils poussent les hits ambigus vers la meme famille

Autrement dit, la passe contextuelle ne sert plus seulement a dire :

- "le plus grave du break ressemble a un kick"

Elle sert aussi a dire :

- "ce hit ambigu ressemble beaucoup aux deux autres hats, donc on lui fait
  davantage confiance comme hat que comme ruff"

En pratique, c'est la meilleure defense actuelle contre :

- `snare` / `clap`
- `closed_hat` / `snare_ruff`
- `open_hat` / `crash`
- petits hits layeres sur la queue d'un kick

Important :

- ce n'est pas un clustering dur
- on ne remplace pas brutalement le score local
- on applique plutot un biais de famille quand plusieurs hits proches entre eux
  vont deja dans la meme direction
- si le score local d'une famille est deja fort, on evite qu'un cluster voisin
  vienne l'ecraser trop facilement

## 5. Layering : labels secondaires et score de couche

Le proto ne pretend pas faire une vraie decomposition de couches.
En revanche, il essaie d'expliciter quand un hit semble hybride.

Ca se fait ici :

- selection des secondaires :
  [_select_secondary_labels(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1156)
- autorisation de certaines paires :
  [_layer_pair_allowed(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1170)
- estimation d'un `layer_score` :
  [_estimate_layer_score(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1189)

Exemples de paires autorisees :

- `kick + closed_hat`
- `kick + open_hat`
- `kick + crash`
- `snare + clap`
- `snare + open_hat`
- `open_hat + crash`

Interpretation :

- `label` = couche principale a utiliser en premier
- `secondary_labels` = couches plausibles superposees
- `layer_score` = a quel point cette lecture "layered" semble credible

Aujourd'hui, le generateur exploite surtout bien le label principal.
Le layering sert deja un peu a la resolution de debut de mesure, mais il y a
encore de la marge pour en faire un vrai moteur multi-couches.

## 5.bis Sequences extraites

En plus des hits individuels, l'analyse extrait maintenant des suites de hits
consecutifs reutilisables comme blocs.

Le but est simple :

- ne pas perdre la micro-dynamique d'un petit motif deja bon dans le break source
- reinjecter certains enchainements "en bloc" plutot que note par note

Les sequences sont construites a partir de n-grams de `2` a `12` hits
consecutifs. Chaque sequence conserve :

- les slices source dans l'ordre
- leurs offsets relatifs en steps
- leurs intervalles relatifs
- leurs ratios de velocite internes
- leur duree totale en steps

Ces sequences ne sont pas extraites depuis le timing brut du break, mais depuis
une version quantifiee de sa grille source :

- la grille est ancree sur le premier hit detecte du break
- les offsets internes sont mesures sur cette grille 16 steps quantifiee
- les petites avances / retards du break source ne deformaient donc plus les
  hints rythmiques des sequences

Point important pour l'UI :

- si l'utilisateur corrige la lecture du BPM detecte en `x2` ou `x0.5`
- les hits et sequences utilises par le generateur sont maintenant re-quantifies
  sur cette nouvelle grille effective
- autrement dit, les sequences suivent le meme repere rythmique que le reste du
  pattern generator, au lieu de rester figees sur le BPM brut de l'analyse

Chaque sequence recoit aussi un role global :

- `groove`
- `anticipation`
- `fill`
- `cadence`

Le stockage se fait dans `hit_sequences` sur `DrumDetectionResult`.

## 6. Roles musicaux

Au-dela du type brut, chaque hit recoit aussi un role musical.

La logique de base est dans
[_default_role_for_label(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1196)
et l'ajustement rythmique se fait dans
[_assign_hit_roles(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1212).

Roles utilises :

- `pillar`
  structure portante du groove
  ex: `kick`, `snare`, `clap`
- `texture`
  continuite rythmique
  ex: `closed_hat`, `ride`
- `accent`
  accent ponctuel
  ex: `open_hat`
- `punctuation`
  ponctuation de phrase
  ex: `crash`, certains `open_hat`
- `tension`
  petits coups de relance
  ex: `kick_ghost`, `snare_ghost`
- `fill`
  materiau de transition / fin de phrase
  ex: `snare_ruff`, `perc`, `tom`

Le role depend :

- du label
- du tempo estime
- de la position du hit sur une grille 16 steps

Ce role est central pour la generation.

En parallele, chaque hit garde une `rhythmic_position` inferree depuis la
grille 16 steps quantifiee du break source :

- step `1` / `9` -> `downbeat`
- step `5` / `13` -> `backbeat`
- step `3` / `7` / `11` / `15` -> `offbeat`
- le reste -> `subdivision`

Cette information ne remplace pas le role musical. Elle sert surtout de memoire
structurelle pour guider le replacage dans le generateur.

Important :

- la position est calculee par rapport au premier hit du break, pas par rapport
  au debut brut du fichier
- du coup, `rhythmic_position`, `start_step_hint` et les offsets de sequences
  suivent tous la meme lecture quantifiee du break

## 7. Ce que l'UI permet de corriger

L'UI dans [ui.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/ui.py)
sert autant d'outil d'analyse que d'outil de correction.

L'interface est maintenant organisee en onglets principaux :

- `Analyze / Waveform`
  - selection du fichier
  - fichiers recents
  - lancement de l'analyse
  - waveform / markers / cuts / undo / redo
  - grande table des transients
- `Preview`
  - previews `retime` / `quantize`
  - BPM cible et controles de relecture
  - mini vue visuelle `Source / Preview` pour lire ce que le quantize recale
- `Generator`
  - reglages complets du pattern
  - grille principale `Anchor / Lock / Event / FX`
  - edition detaillee du slot affiche si le live mode est actif
  - panneau `Manual pipeline` en vue `Advanced`
    pour regenirer seulement le skeleton puis lancer / rollback chaque passe a
    la main
- `Live`
  - slots `A / B`
  - stems mute
  - FX callback
  - mini patterns compacts par slot
- `Saved`
  - snapshots persistants des breaks generes
  - reouverture exacte d'une generation precedente dans `Generator`
  - rendu WAV a partir d'un break sauvegarde
- `Inspector`
  - resultat, candidats, JSON brut, details et vues d'inspection
  - export d'un `Debug report` texte complet du pipeline de generation

Cette separation sert a deux choses :

- rendre le workflow plus lisible
- eviter de rafraichir en permanence des panneaux lourds quand ils ne sont pas visibles

Fonctions importantes :

- edition des markers
  - ajout
  - suppression
  - deplacement
  - rebuild des hits depuis la liste de markers
- decoupe manuelle
  - cut de selection dans la waveform
  - undo / redo
  - split sample equally via menu contextuel
- correction manuelle des labels
  - la colonne `Label` de la table de hits peut etre redefinie
- exclusion du generateur
  - la colonne `Pool` permet de mute / unmute un hit pour le break generator
  - un hit mute reste visible, jouable et editable dans l'analyse
  - mais il est retire des pools de slices et des sequences utilisees par le generateur
- preview audio
  - playback waveform
  - preview retime / quantize
  - preview du pattern genere
- snapshots de break
  - bouton `★` dans `Generator` pour figer le break courant
  - bouton `★` dans chaque slot live pour figer l'etat exact du slot
  - l'onglet `Saved` permet de rouvrir plus tard ce meme break
- rendu WAV
  - bouton `Render WAV` dans `Generator`
  - bouton `Render WAV` aussi dans `Saved`
  - le rendu est borne a une boucle exacte du pattern
- controles waveform explicites
  - `Play waveform`
  - `Pause waveform`
  - `Stop waveform`
  - `Loop waveform`
  - raccourcis dedies quand la waveform a le focus
- modes d'affichage du generateur
  - `Basic`
    garde les controles essentiels et masque les panneaux plus analytiques
  - `Advanced`
    reaffiche le pitch, la synthese ghost, les motifs utilisateur et les vues
    d'inspection
  - presets d'affichage
    - `Balanced`
      vue equilibree entre edition et lecture
    - `Performance`
      replie davantage les panneaux d'info pour se concentrer sur le groove
    - `Inspector`
      ouvre les panneaux utiles pour comprendre finement ce que fait le moteur

L'UI sert aussi de memo de travail :

- les markers sont persistes par fichier
- les relabels manuels sont persistants
- l'analyse complete peut etre restauree pour un break deja travaille
- les reglages du generateur sont eux aussi memorises d'une session a l'autre
  - ex: `breath`, `anti-repeat`, `swing`, `velocity`, densites et toggles
- les snapshots de breaks sont persistes par projet dans
  `.drum_detector_saved_patterns.json`
- les slots live `A / B`, eux, restent pour l'instant volatils
  - ils ne sont pas restaures automatiquement a la reouverture comme les
    markers, relabels, analyses persistees et snapshots sauvegardes

L'idee est d'eviter de redecouper et de relabeliser le meme break a chaque
reouverture.

Ce point est volontaire :

- l'analyse est heuristique
- la correction humaine fait partie du workflow normal

## 8. Preview retime / quantize

Le rendu audio des previews est dans
[preview.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py).

Deux familles de preview existent pour les hits detectes :

1. `retime`
   - garde la vitesse des slices
   - change seulement leurs temps de depart selon le BPM cible
2. `quantize`
   - meme base que `retime`
   - mais les declenchements sont rapproches d'une grille
   - grille dispo: `1/8`, `1/16`, `1/32`
   - force de quantize reglable

Le point d'entree est
[build_retimed_preview(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py#L52).

L'idee generale :

- on prend les slices source
- on calcule un planning de declenchement
- on recompose un buffer audio
- on expose aussi les segments planifies pour synchroniser la tete de lecture UI

L'onglet `Preview` affiche aussi maintenant une mini vue compacte du planning :

- ligne `Src`
  placements retimes avant quantize
- ligne `Out`
  placements effectivement relus
- en mode `quantize`, la grille choisie est dessinee explicitement
- les connecteurs entre `Src` et `Out` montrent quels hits bougent et dans quel
  sens

Le but n'est pas de remplacer la waveform, mais de rendre plus lisible ce que
fait le quantize au niveau du placement rythmique.

## 9. Generateur de break

Le coeur est dans
[generate_break_pattern(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L113)
pour le mode classique, et dans
[generate_break_pattern_hybrid(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L315)
pour le mode hybride base sur des motifs utilisateur.

### 9.1 Entree du generateur

Le generateur prend :

- une liste de `TransientHit`
- une liste optionnelle de `HitSequence`
- un objet `BreakPatternParams`

Deux modes existent maintenant :

- `Classic`
  comportement historique, sans squelette utilisateur
- `Hybrid`
  ajoute une passe amont qui pose des `UserMotif` comme ancres temporaires,
  puis reutilise le generateur classique pour remplir les trous

En plus du mode `Classic / Hybrid`, le generateur expose maintenant un
`generation_profile` qui pilote surtout l'ordre des passes tardives et leur
agressivite :

- `Safe`
  priorise la lisibilite et limite davantage les reecritures tardives
- `Musical`
  profil par defaut, garde une phrase lisible tout en conservant des FX tardifs
  encore presents
- `Destructive`
  autorise plus de collisions entre passes et un comportement plus breakcore

Les parametres exposes sont :

- `energy`
- `kick_weight`
- `snare_weight`
- `hat_density`
- `ghost_density`
- `synth_ghost_enabled`
- `ghost_vel_range`
- `ghost_pitch_range`
- `ghost_gate_ratio`
- `fill_strength`
- `repeat_density`
- `repeat_span`
- `repeat_rate`
- `reverse_density`
- `kick_roll_density`
- `kick_roll_span`
- `kick_roll_contrast`
- `snare_stretch_density`
- `snare_stretch_span`
- `snare_stretch_amount`
- `snare_stretch_vel_curve`
- `pitch_mode`
- `pitch_scope`
- `pitch_scale`
- `pitch_root`
- `pitch_range`
- `pitch_sequence`
- `pitch_curve`
- `pitch_curve_range`
- `pitch_rate`
- `pitch_amount`
- `gate`
- `mono_choke`
- `sequence_density`
- `sequence_max_len`
- `sequence_role_lock`
- `user_motifs`
- `motif_density`
- `generation_profile`
- `velocity_spread`
- `swing`
- `anti_repeat`
- `breath_factor`
- `position_fidelity`
- `seed`
- `bars`

`energy` agit comme une macro qui rebalance les autres parametres.

Notes utiles :

- `repeat_density`
  controle combien de zones de repeat glitch apparaissent dans le pattern
- `repeat_span`
  controle la longueur probable des zones de repeat sur la timeline
- `repeat_rate`
  controle si les retriggers internes sont plutot en `x2` ou en `x4`
- `reverse_density`
  injecte des queues reverse apres certains `kick` / `snare` / `clap`
  sur les subdivisions entre reperes rythmiques
  la slice reverse reutilise la source du hit juste avant et reste contenue
  dans le slot qui mene vers le repere suivant
- `kick_roll_density`
  controle la frequence des kick rolls
  un kick roll est ici une petite rafale du meme kick sur plusieurs steps
  consecutifs, declenchee directement sur un beat pair du bar
  et etalee ensuite sur les steps suivants, avec une velocite uniforme
  sur toute la succession, premier kick compris
- `kick_roll_span`
  controle la longueur probable des zones de kick roll
  la V1 reste volontairement sur des spans paires et courtes,
  calees sur les fenetres `5-8` et `13-16`
- `kick_roll_contrast`
  controle le niveau global de velocite du roll
  bas = roll plus doux, haut = roll plus fort
- `synth_ghost_enabled`
  active un fallback explicite pour fabriquer des ghosts a partir des snares
  normales quand les vrais `snare_ghost` / `kick_ghost` manquent
- `ghost_vel_range`
  plage du ratio de velocite applique aux ghosts synthetiques
  ex: `(0.20, 0.45)` pour garder un vrai caractere de ghost note
- `ghost_pitch_range`
  petit decalage de pitch optionnel applique aux ghosts synthetiques
  `0.0, 0.0` = pas de decalage timbral
- `ghost_gate_ratio`
  gate optionnel applique aux ghosts synthetiques
  `0.0` = pas de gate supplementaire
  plus haut = queue plus courte et ghost plus leger
- `snare_stretch_density`
  controle la frequence des zones de retrigger exponentiel sur snares, claps
  et ruffs
- `snare_stretch_span`
  controle la longueur cible de la zone de retrigger
  `0.0 -> 2 steps`, `1.0 -> jusqu'a 16 steps`
  la zone reelle reste plafonnee par la fin de mesure ou le prochain anchor
- `snare_stretch_amount`
  controle la vitesse de resserrement exponentiel entre retriggers
  bas = acceleration douce, haut = fin de zone tres compacte / breakcore
- `snare_stretch_vel_curve`
  controle la courbe de velocite des retriggers
  - `flat`
    meme niveau tout du long
  - `decay`
    energie qui descend progressivement
  - `crescendo`
    energie qui monte progressivement
  - `random`
    variations aleatoires dans la plage de velocite de la zone
- `pitch_mode`
  ajoute un mouvement de pitch par hit sur le pattern genere
  - `off`
    aucun pitch shift
  - `random`
    chaque hit cible tire une valeur dans `pitch_range`
  - `sequence`
    les hits cibles avancent dans `pitch_sequence`
  - `curve`
    les hits cibles suivent une courbe `up / down / bell / inv_bell`
- `pitch_scope`
  choisit quelles familles de hits sont eligibles
  - `snare`
  - `snare+clap`
  - `all_pillar`
  - `all`
- `pitch_scale`
  contraint les demi-tons autorises
  - `chromatic`
  - `minor`
  - `major`
  - `pentatonic`
  - `diminished`
- `pitch_root`
  demi-ton de reference de la gamme courante
  - `0 = C`
  - `1 = C#`
  - etc.
- `pitch_range`
  plage min / max en demi-tons pour le mode `random`
- `pitch_sequence`
  liste explicite de demi-tons pour le mode `sequence`
- `pitch_curve`
  forme de courbe utilisee en mode `curve`
- `pitch_curve_range`
  plage min / max utilisee par la courbe avant quantization de gamme
- `pitch_rate`
  vitesse de changement du pitch
  - `every_hit`
  - `every_2`
  - `every_bar`
- `pitch_amount`
  dose globale appliquee apres le choix du pitch
  - `0.0`
    aucun effet audible
  - `1.0`
    amplitude complete
  point important :
  `anti_repeat` ne bloque pas deux hits identiques si leur `pitch_shift`
  differe, car leur perception finale n'est plus la meme
- `gate`
  raccourcit globalement la longueur jouee des slices au moment de la preview du pattern
- `mono_choke`
  active une lecture mono globale
  - a chaque nouveau hit declenche, la queue du hit precedent est coupee
  - ce choke ne depend pas de la famille du hit
  - il s'applique au pattern genere, aux previews `retime / quantize` et au
    mode live
- `user_motifs`
  liste de motifs partiels definis par l'utilisateur et persistes par projet
- `motif_density`
  scale global applique a la probabilite de base de tous les motifs utilisateur
  en mode `Hybrid`

Dans l'UI, les effets sont visibles discretement dans la grille du
pattern :

- teinte legere sur les steps concernes
- marqueur `[` au debut de zone et `]` a la fin dans l'entete de timeline
- marqueur `{` au debut de kick roll et `}` a la fin
- teinte plus chaude pour les steps `reverse`
- teinte cuivre pour les steps `kick_roll`
- teinte bleue pour toute la zone `snare_stretch`, avec un debut plus marque
- teinte verte discrete sur les steps avec `pitch_shift`
- ligne `FX` dans la timeline pour lire explicitement `Rpt x2/x4`, `Rev<-K/S/C`, `KRoll`, les points de retrigger `Snr.Str` et `Pch +/-N`

L'UI expose aussi un petit tableau de probabilites d'effets :

- `Repeat`
  chance heuristique de voir apparaitre une zone de retrigger glitch
- `Reverse`
  chance heuristique d'injecter une queue reverse sur une classe de position
- `K.Roll`
  chance heuristique de lancer une rafale de kicks sur plusieurs steps
  a partir d'un kick deja present
- `Snr.Str`
  chance heuristique de transformer un snare, clap ou ruff en zone glitch
  qui occupe le break jusqu'au repere suivant
- `Pitch`
  chance heuristique qu'un hit cible recoive un `pitch_shift`
  selon le mode, la portee et l'intensite courants

L'UI expose aussi deux actions directes dans `Generator` :

- `★`
  sauvegarde le break courant comme snapshot persistant
- `Render WAV`
  exporte un `.wav` du pattern courant
  - le rendu est borne a la duree exacte d'une boucle du pattern
  - il reutilise les memes regles de lecture que le preview
    (`gate`, `mono_choke`, swing et FX structurels deja precalcules)

L'UI ajoute aussi une ligne `Anchor` au-dessus de la grille generee.
Elle permet de figer certains steps en :

- `kick`
- `snare`
- `clap`
- `hat`
- `ghost`
- `other`
- `silence`

Cette ligne sert a verrouiller un squelette rythmique simple
(ex: kick sur `1`, snare sur `5` et `13`), puis laisser le generateur
construire le reste autour.

En mode `Hybrid`, l'UI ajoute aussi un panneau `Add sequence` :

- mini grille editable de `2` a `8` steps
- valeurs possibles :
  - `kick`
  - `snare`
  - `hat`
  - `ghost`
  - `silence`
  - `trou`
- `base_prob`
- `role`
- `dominant_type`
- calcul live de la probabilite effective
- sauvegarde dans `.drum_detector_user_motifs.json` a la racine du projet courant

Les motifs sauvegardes sont listes dans `User motifs` avec :

- leur pattern
- leur role
- leur type dominant
- leur probabilite de base
- leur probabilite effective avec les reglages actifs
- un bouton de suppression

Les parametres sequences servent a choisir combien de fois le generateur
essaie d'utiliser un bloc de hits deja observe au lieu de repartir en pur mode
atomique.

L'Inspector expose aussi maintenant un bouton `Debug report` qui regenere un
rapport texte complet du pattern avec :

- les params courants
- le resume des pools
- l'historique step par step de chaque passe
- un resume des collisions entre passes
- les metriques finales du pattern

Le rapport est regenere a chaque clic avec les reglages visibles au moment du
clic. Il peut etre copie dans le presse-papiers ou sauvegarde en `.txt`.

En vue `Advanced`, le `Generator` expose aussi maintenant un panneau
`Manual pipeline`.

Le but n'est pas de remplacer le pipeline automatique, mais de permettre un
workflow de sculpt / debug sur un pattern deja en cours :

- `Regenerate skeleton`
  regenere seulement le squelette de base
- `Run`
  applique une passe precise sur le pattern courant
- `Rollback`
  revient au snapshot pris juste avant cette passe
- `Run all enabled`
  reapplique toutes les passes activees depuis le skeleton courant
- `Export debug report`
  exporte le `DebugLog` courant tel qu'il a evolue passe par passe

Les toggles de ce panneau pilotent aussi le pipeline automatique :

- si une passe est desactivee ici, elle ne sera plus executee pendant une
  generation automatique classique
- le mode manuel reste reserve a l'onglet `Generator`
- le mode `Live`, lui, garde le pipeline automatique pour la regen des slots
  `A / B`

L'UI expose maintenant aussi une section `Pitch` avec :

- `Mode`
- `Scope`
- `Scale`
- `Root`
- `Amount`
- `Range min / max`
- `Rate`
- `Sequence`
  visible seulement en mode `sequence`
- `Curve` + `Curve range`
  visibles seulement en mode `curve`

`position_fidelity` regle a quel point le generateur respecte la classe
rythmique d'origine des slices :

- `0.0` -> ce biais est ignore
- `1.0` -> un hit `downbeat` sera fortement favorise sur un `downbeat`,
  un `backbeat` sur un `backbeat`, etc.

Ce n'est pas une contrainte dure. C'est un poids preferentiel.

### 9.2 Pools de slices

Avant de generer, le systeme construit des pools dans
[_build_pools(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L173).

Exemples :

- `kick`
- `kick_ghost`
- `snare`
- `clap`
- `snare_ghost`
- `snare_ruff`
- `ride`
- `snareish`
- `hatish`
- `otherish`

Le but est que la generation pioche dans des buckets fonctionnels plutot que
de balancer des slices au hasard.

Il existe maintenant un deuxieme niveau de pool :

- les pools de sequences `groove`
- les pools de sequences `anticipation`
- les pools de sequences `fill`
- les pools de sequences `cadence`

### 9.3 Generation du squelette

Le pattern est genere sur une grille de 16 steps par mesure.

Le generateur decide d'abord une famille d'evenement par step via
[_step_family_weights(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L221).

Mais avant de tomber sur ce mode atomique, il peut maintenant essayer de poser
une sequence en bloc si `sequence_density > 0`.

En mode `Hybrid`, il y a une passe supplementaire encore avant :

1. pose de `UserMotif` comme ancres temporaires
2. remplissage par le generateur existant
3. finalisation des vitesses / swing / effets comme d'habitude

Les motifs utilisateur suivent ces regles :

- `base_prob` est reponderee par `motif_density`
- cette probabilite est aussi modulee par :
  - `kick_weight` / `snare_weight` / `hat_density` / `ghost_density`
    selon le `dominant_type`
  - `anti_repeat` si le meme motif vient d'apparaitre dans la mesure precedente
  - `energy` si le pattern est pousse
  - `fill_strength` si le motif est un `fill`
  - `position_fidelity` selon la classe rythmique du premier hit explicite
- si un motif rencontre une `Anchor` manuelle, il est tronque a cet endroit
- ses `None` restent libres et sont remplis normalement par la passe suivante

Priorite globale :

- `Anchor` manuelle
- `UserMotif`
- `HitSequence`
- generation atomique

Familles principales :

- `kick`
- `snare`
- `hat`
- `ghost`
- `other`
- `silence`

La decision depend :

- de la position rythmique
  - temps forts
  - backbeats
  - offbeats
  - subdivisions
- des deux steps precedents
- de la respiration apres un kick
- de l'anti-repeat
- de la densite locale
- de la disponibilite reelle des pools
- de la position rythmique d'origine si `position_fidelity > 0`
- des ancres de steps posees manuellement dans la ligne `Anchor`

Depuis les dernieres iterations, le generateur ajoute aussi quelques garde-fous
internes pour conserver plus de coherence :

- les sequences et les steps ancres sont traites comme du materiau protege
- une `FillDecision` est maintenant prise tres tot, bar par bar
  - elle reserve une zone de fin de mesure avant le remplissage normal
  - cette zone devient interdite aux motifs utilisateur, aux sequences non
    `fill` et aux FX tardifs
  - le squelette y pose d'abord des silences temporaires ou une base de
    sequence `fill`, puis `fill_pass` la remplit en bloc
- les FX tardifs (`repeat`, `kick roll`, `reverse`, `snare stretch`) evitent
  de reecrire ce materiau protege
- le squelette reapplique maintenant aussi une petite ossature de piliers
  apres son tirage initial
  - `kick` prioritaire sur `1`
  - `snare/clap` prioritaire sur `5`
  - `9` et `13` restent des appuis probables, mais plus variables
  - ils peuvent soutenir la mesure, se decaler vers autre chose, ou laisser
    respirer le groove selon les poids et le contexte
- une meme mesure a un budget limite de mutations tardives, pour eviter qu'un
  trop grand nombre de passes finisse par ecraser le squelette initial
- le squelette de base autorise encore du silence, mais beaucoup moins sur les
  positions structurelles (`1`, `5`, `9`, `13`)

Si une sequence est choisie :

- elle doit tenir dans les steps restants de la mesure
- elle doit correspondre a la zone rythmique autorisee
- elle reserve aussi ses silences / gaps internes
- son hit de depart est compare a la classe rythmique cible
- le generateur avance alors par bloc plutot que step par step

Le point cle pour les sequences :

- seul l'ancrage de depart est biaise par `rhythmic_position`
- les hits suivants se deploient ensuite via leurs offsets relatifs
- on ne recalcule pas leur position un par un apres coup

Si une ancre de step existe :

- elle agit comme une contrainte forte
- le generateur tente de choisir une slice compatible avec cette ancre
- `silence` peut forcer un trou meme en zone de fill
- une sequence incompatible avec cette ancre est rejetee
- en fin de passe, les ancres sont reappliquees pour eviter qu'un fill ou une
  resolution ne les ecrase

### 9.4 Ghost notes

Les ghosts sont injectes apres la premiere passe dans
[_inject_ghost_notes(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L500).

Idee :

- trouver des zones plausibles autour des snares
- remplacer certains silences / hats par des ghosts
- utiliser si possible de vrais `snare_ghost` ou `kick_ghost`
- sinon, si `synth_ghost_enabled` est actif :
  - reutiliser une slice `snare` / `clap` / `snare_ruff`
  - la marquer comme ghost synthétique
  - reduire sa velocite via `ghost_vel_range`
  - lui appliquer un petit `ghost_pitch_range` optionnel
  - lui appliquer un `ghost_gate_ratio` optionnel pour couper la queue

Important :

- le fallback synthétique ne remplace pas la priorite des vrais ghosts
- il intervient surtout quand le pool ghost est vide ou insuffisant
- au rendu, ces transformations sont appliquees hit par hit dans `preview.py`
  sur la slice choisie, pas globalement sur tout le break

### 9.5 Fills

Le fill n'est plus pense comme une petite passe tardive opportuniste.
Il devient un element structurel decide en amont.

Le pipeline fait maintenant :

1. decision de fill par mesure (`FillDecision`)
2. reservation d'une zone de fin de mesure
3. squelette normal hors de cette zone
4. remplissage du fill en bloc par `fill_pass`
5. resolution du `1` suivant via
   [_apply_bar_start_resolutions(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L633)

La decision expose :

- `active`
- `fill_type`
- `zone_start -> zone_end`
- `source`
  - `generated`
  - `sequence`

Types de fills actuellement modelises :

- `ghost_hat`
- `ruff`
- `crash_open`
- `double_kick`
- `dense`
- `perc_burst`
- `kick_snare_alternance`
- `silence_drop`

Effets concrets de cette reservation :

- un `UserMotif` ne peut plus chevaucher la zone reservee
- une sequence non `fill` ne peut plus deborder dedans
- les passes tardives `ghost / repeat / kick_roll / reverse / snare_stretch`
  la laissent tranquille
- si une sequence de role `fill` existe dans la source, elle peut servir de
  base, puis le type choisi complete les trous

Du point de vue utilisateur :

- `Fill` continue de regler la force / frequence globale
- `Fill style` permet soit `Auto`, soit un type force
- en mode `Auto`, l'UI affiche aussi le type effectivement tire pour le pattern
  courant

### 9.6 Velocite et swing

Une fois les labels choisis, le proto finalise les vitesses dans
[_finalize_step_velocity(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L855).

Les vitesses sont influencees par :

- la classe du hit
- la position dans la mesure
- l'activite recente
- la presence d'un silence avant
- la densite locale
- le spread de velocite

Le swing est ensuite applique au moment du rendu de preview du pattern dans
[build_pattern_preview(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py#L185).

Le pitch shift est lui aussi applique au rendu, slice par slice :

- chaque `GeneratedPatternStep` peut porter un `pitch_shift` en demi-tons
- si cette valeur est non nulle, la slice source est resamplee juste avant son
  mixage dans le buffer final
- le traitement est local au hit
  il n'affecte ni le reste du pattern, ni les autres slices

Les ghosts synthetiques reutilisent le meme principe au rendu :

- `ghost_vel_ratio`
  reduit la velocite finale du step
- `ghost_pitch_offset`
  ajoute un petit pitch shift local a la slice
- `ghost_gate_ratio`
  peut tronquer la slice avant son mixage pour alleger la queue

### 9.7 Reroll

Le generateur sait aussi reroll un step specifique sans refaire tout le pattern
via [reroll_break_pattern_step(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L138).

L'idee n'est pas seulement "regenerer aleatoirement", mais permettre un usage
plus proche d'un tracker / groovebox :

- pattern qui joue en boucle
- un step est rerolle
- le reste du pattern reste stable

La ligne `Anchor` s'integre aussi a ce workflow :

- tu poses une ancre sur un step
- tu reroll seulement ce step
- le generateur respecte l'ancre sans reconstruire tout le pattern

Le pattern genere expose aussi maintenant quelques metriques internes utiles
pour debugger la qualite du resultat :

- `silence_ratio`
- `sequence_ratio`
- `post_fx_ratio`
- `fill_ratio`
- `resolution_ratio`
- `protected_ratio`

### 9.7.bis Snapshots et rendu

Le proto sait maintenant figer une generation pour la retrouver plus tard.

Le workflow est simple :

1. generer un break dans `Generator` ou dans un slot live
2. cliquer sur `★`
3. retrouver ce break dans l'onglet `Saved`
4. le rouvrir plus tard dans `Generator`
5. ou l'exporter directement en `WAV`

Chaque snapshot garde :

- le chemin du sample source
- le `DrumDetectionResult` utilise au moment de la sauvegarde
- le `GeneratedBreakPattern` exact
- les params de generation utiles a la relecture
- les anchors et `locked_steps`

Le but est double :

- ne pas perdre une generation reussie entre deux sessions
- pouvoir revenir exactement au meme break, pas seulement a une seed approchante

Le rendu `WAV` d'un pattern courant ou sauvegarde :

- recalcule un preview du pattern a partir de cet etat fige
- exporte une boucle strictement bornee a la duree du pattern
- ne deborde donc pas au-dela du nombre de mesures generees

### 9.8 Mode Live

Le proto expose maintenant un mode `Live` dans l'UI du generateur.

L'idee n'est plus seulement de :

- generer un pattern
- le lire tel quel

Mais de pouvoir :

- garder un slot actif qui joue
- regenerer un second slot en arriere-plan
- switcher proprement sur le `1` suivant
- muter / remuter des stems en direct
- appliquer quelques FX directement dans la callback audio

Le mode live repose sur trois briques.

#### A. Double slot A / B

Chaque slot garde :

- un `GeneratedBreakPattern`
- un snapshot de `BreakPatternParams`
- sa `seed`
- son statut (`ready`, `generating`, `playing`, `stale`)
- ses stems audio precalcules
- une mini vue compacte du pattern par mesure
  - ligne `Evt`
  - ligne `Anc`
  - ligne `Lock`

Important a ce stade :

- les slots `A / B` sont un etat de session
- si tu fermes puis rouvres l'application, ils ne sont pas restaures
  automatiquement comme les markers, relabels ou l'analyse persistee
- il faut donc regenirer ou reconstituer ton set live apres reouverture

La mini vue compacte du slot sert de repere rapide :

- elle affiche les labels courts (`K`, `S`, `HC`, etc.)
- elle colore les familles de hits
- elle teinte aussi les anchors et les locks
- elle montre une tete de lecture simple sur la step en cours
- elle permet de modifier rapidement `Anchor` et `Lock` sans quitter la page live

Le workflow vise un usage type groovebox :

- `A` joue
- `B` est regenere en arriere-plan
- `Switch` arme un swap
- le swap ne se fait qu'au retour sur le step `1`

Les boutons `Duplicate A->B` et `Duplicate B->A` recopient le snapshot du slot
source puis relancent une regeneration du slot cible.

Chaque slot live expose aussi un bouton `★` :

- il sauvegarde le pattern du slot tel qu'il joue a cet instant
- le snapshot apparait ensuite dans l'onglet `Saved`
- il peut etre rouvert plus tard dans `Generator` sans perdre la generation
  exacte du slot

La section `Callback FX` du mode live expose aussi un bouton
`Quick Render active` :

- il exporte directement le slot actif en `.wav`
- il reutilise le dernier dossier d'export WAV connu
- il ne rouvre pas de boite de dialogue
- si un fichier du meme nom existe deja, un suffixe numerique est ajoute pour
  eviter l'ecrasement

#### B. Preview pattern par stems

Le rendu pattern ne produit plus seulement un buffer mixe unique.
`build_pattern_preview(...)` construit aussi des stems separes :

- `kick`
- `snare`
- `hat`
- `ghost`
- `clap`
- `repeat`
- `reverse`
- `roll`
- `stretch`
- `other`

Les stems FX contiennent uniquement les evenements portant vraiment cet effet.
Exemple :

- un retrigger `repeat` tombe dans le stem `repeat`
- un tail `reverse` tombe dans `reverse`
- un `kick roll` tombe dans `roll`
- un `snare stretch` tombe dans `stretch`

Les `RetimedPreviewSegment` gardent aussi maintenant le nom du `stem`, ce qui
permet de conserver un suivi visuel coherent meme si la lecture live ne lit pas
un buffer mixe unique.

#### C. FX callback temps reel

Quelques traitements se font directement dans la callback audio, stem par stem :

- `gain`
- `lowpass`
- `highpass`
- `distortion`
- `bitcrush`
- `gate`
- `stutter`

La `distortion` n'est pas implicite :

- c'est bien un effet live a part entiere
- elle expose trois reglages :
  - `drive`
  - `tone`
  - `mix`
- elle se route stem par stem comme les autres FX callback
- son but est surtout d'ajouter un caractere sale / nerveux en performance,
  sans obliger a regenirer le pattern

Chaque effet a sa propre matrice de cibles :

- tu peux l'appliquer a tous les stems
- ou seulement a certains (`snare`, `repeat`, `stretch`, etc.)

Ordre de traitement live actuel :

1. lecture des stems actifs
2. `gain` cible par stem
3. filtres `lowpass` / `highpass`
4. `distortion`
5. `bitcrush`
6. `gate`
7. `stutter`

Le `stutter` est un `hold` :

- il gele la lecture du step courant tant qu'il est maintenu
- sans modifier le buffer precalcule lui-meme

Important :

- les FX live ne re-renderisent pas le pattern
- ils agissent sur le flux de sortie en direct
- les effets structurels du generateur (`repeat`, `reverse`, `stretch`, etc.)
  restent eux precalcules dans les stems

#### UI live

Quand `Live mode` est actif, l'UI fait remonter surtout trois zones :

1. zone `A/B`
   - statut du slot
   - seed
   - resume rapide des params
   - `Live BPM`
   - generation / duplication / switch
   - mini pattern compact par slot
2. zone `Stems`
   - toggles `kick / snare / hat / ghost / clap / repeat / reverse / roll / stretch / other`
   - boutons `All` / `None`
3. zone `Live FX`
   - une ligne par effet
   - controle principal
   - bouton `All`
   - toggles de stems cibles

Raccourcis live utiles :

- `Space`
  programme le switch A/B au prochain retour sur le step `1`
- `D`
  duplique le slot actif vers l'inactif
- `R`
  regenere le slot inactif
- `1..9,0`
  toggles rapides des stems dans l'ordre affiche
- `G`
  maintient le `stutter hold`

Les slots ont aussi des etats visuels plus explicites :

- slot actif en lecture
- slot pret
- slot en generation
- slot `pending` quand un switch est arme pour le prochain `1`

Le but est de pouvoir lire l'etat du set d'un coup d'oeil sans dependre
uniquement du texte.

Le `Live BPM` n'est pas un tempo parallele independant :

- c'est un acces direct depuis la page live au meme `BPM cible` global que le
  generateur
- le champ live et le champ du generateur restent synchronises
- changer `Live BPM` revient donc a changer le tempo global du systeme de
  generation / lecture live
- ce n'est ni un `tap tempo`, ni un override temporaire propre a un seul slot

#### D. Perf et isolement de charge

Le point important du mode live recent :

- la lecture audio reste prioritaire
- la regeneration d'un slot ne doit pas prendre le pas sur la callback audio

Pour ca, la regen live essaie maintenant de rester au maximum hors du thread UI :

- generation et rebuild live dans un process dedie
- priorite plus basse pour ce process de regen
- reutilisation d'un buffer audio partage pour eviter de reserialiser tout le
  sample source a chaque regen
- prechauffage des groupes de stems prepare hors UI
- mini vues live allegees
  - elles ne se reconstruisent plus completement a chaque refresh
  - la tete de lecture met seulement a jour la colonne active

Autrement dit :

- le transport audio reste le plus simple possible
- les gros calculs de regen sont repousses hors du chemin critique
- l'UI live garde ses reperes visuels, mais avec des rafraichissements plus
  parcimonieux

En pratique, le slot affiche dans `Generator` et le slot joue dans `Live`
restent distincts :

- `Live` sert a performer
- `Generator` sert a regler plus finement le slot `A` ou `B` affiche
- les anchors / locks restent donc accessibles meme en workflow live

## 10. Relation entre detection et generation

Le generateur n'est pas independant du detecteur.
Il herite directement de ses qualites et de ses erreurs.

Si la detection se trompe :

- un snare peut finir dans un pool de `perc`
- un open hat peut etre pris pour un crash
- un hit layered peut etre utilise comme slice principale la ou il faudrait une
  autre couche

Du coup, la boucle de travail ideale est :

1. analyser
2. ajuster markers si besoin
3. corriger les labels faux
4. regenerer le pattern
5. ecouter
6. reaffiner

## 11. Limites actuelles

Le proto reste heuristique.

Les limites les plus importantes sont :

- pas de vrai stem separation
- pas de vrai multipitch / multilabel profond
- `secondary_labels` encore sous-exploites en generation
- ambiguites frequentes :
  - `snare` / `clap`
  - `closed_hat` / `snare_ruff`
  - `open_hat` / `crash`
  - petits ghosts faibles
- la qualite depend beaucoup de la segmentation initiale
- les breaks tres process / compresses / sales restent durs a lire
- la similarite inter-hits reste heuristique
  - elle aide bien sur les breaks repetitifs
  - mais elle reste moins fiable si presque tous les hits sont deja tres
    process, tres layers ou tres differents les uns des autres
- la fin exacte d'un hit reste un compromis
  - trop courte : on coupe un kick ou un snare
  - trop longue : on mange le transient suivant
  - le systeme est meilleur qu'avant, mais ce point reste structurellement dur

## 12. Axes d'amelioration les plus prometteurs

Si on veut continuer a faire progresser le systeme, les chantiers les plus
rentables sont probablement :

### A. Mieux classer les hits

- renforcer encore la comparaison inter-hits
- faire un clustering plus explicite de hits similaires
- apprendre des profils de break par famille
- utiliser davantage les corrections manuelles comme signal faible
- separer encore mieux attaque / corps / tail dans le scoring

### B. Mieux exploiter le layering

- transformer `secondary_labels` en vraie logique de generation multi-couches
- permettre des substitutions par role
  - ex: pas de crash -> open hat long
- distinguer plus clairement "hit principal" et "ornement superpose"

### C. Mieux modeliser les fills

- exposer plusieurs styles de fill
  - `resolve`
  - `ruff`
  - `double_kick`
  - `perc_burst`
- mieux controler les transitions entre mesures
- introduire des fills generes en bloc plus explicites

### D. Mieux modeliser les styles

- presets `amen`, `jungle`, `boom bap`, etc.
- differencier davantage les roles selon le style
- faire varier la ponctuation de phrase selon le genre
- rendre ces presets reutilisables plus directement en workflow live
  - ex: point de depart rapide pour remplir un slot `A` ou `B`

### E. Mieux rendre le systeme editable

- conserver l'historique des corrections manuelles
- afficher plus clairement :
  - label principal
  - secondaires
  - role
  - confiance
- permettre des overrides de role en plus des overrides de label

### F. Mieux faire evoluer le live mode

- persister eventuellement les slots `A / B` ou au moins leur snapshot
  parametres + seed
- mieux separer encore la charge audio, UI et regen pour reduire les underflows
- ajouter des scenes / presets live memorisables
- clarifier encore la lecture du set
  - slot actif
  - slot pending
  - tete de lecture
  - stems mutes / FX armes

## 13. Commandes utiles

Lancer l'UI :

```powershell
python -m prototypes.drum_detector.ui
```

Ou :

```powershell
.\scripts\run_drum_detector_ui.ps1
```

CLI sur un fichier :

```powershell
python -m prototypes.drum_detector.cli .\path\to\sample.wav
```

CLI JSON :

```powershell
python -m prototypes.drum_detector.cli .\path\to\sample.wav --json
```

Tests utiles :

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_pattern_generator tests.test_drum_preview tests.test_drum_detector tests.test_scale_detector tests.test_note_segments
```

## 14. Lecture rapide si on veut iterer dessus

Si tu veux modifier le systeme sans tout relire, l'ordre le plus utile est :

1. lire [analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L380)
   pour comprendre la construction du resultat
2. lire [analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1545)
   pour la classification locale des hits
3. lire [analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1000)
   pour la passe contextuelle
4. lire [analyzer.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/analyzer.py#L1212)
   pour les roles
5. lire [pattern_generator.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L113)
   pour le generateur
6. lire [pattern_generator.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L565)
   pour les fills
7. lire [preview.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py#L52)
   et [preview.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/preview.py#L185)
   pour le rendu audio
8. finir par [ui.py](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/ui.py)
   pour voir comment tout s'enchaine dans le workflow utilisateur

Ce README doit rester un document vivant.
Si le systeme change, l'ideal est de le mettre a jour en meme temps, sinon on
perd vite la vision globale qui le rend ameliorable.
