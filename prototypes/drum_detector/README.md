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
- preview audio
  - playback waveform
  - preview retime / quantize
  - preview du pattern genere

L'UI sert aussi de memo de travail :

- les markers sont persistes par fichier
- les relabels manuels sont persistants
- l'analyse complete peut etre restauree pour un break deja travaille

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

Les parametres exposes sont :

- `energy`
- `kick_weight`
- `snare_weight`
- `hat_density`
- `ghost_density`
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
- `gate`
- `sequence_density`
- `sequence_max_len`
- `sequence_role_lock`
- `user_motifs`
- `motif_density`
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
- `snare_stretch_density`
  controle la frequence des snare stretches
  plus haut = davantage de snares, claps ou ruffs allonges
- `snare_stretch_span`
  controle jusqu'ou le stretch essaie d'aller vers le repere suivant
  en pratique, il vise surtout la fenetre restante jusqu'au beat suivant
- `snare_stretch_amount`
  controle a quel point la slice est vraiment etiree dans cette fenetre
  bas = discret, haut = vrai effet glitch/stutter granulaire breakcore
  l'effet garde l'attaque du snare une seule fois, et glitch surtout la tail
  il ne mute plus automatiquement les hits suivants du pattern
- `gate`
  raccourcit globalement la longueur jouee des slices au moment de la preview du pattern
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
- ligne `FX` dans la timeline pour lire explicitement `Rpt x2/x4`, `Rev<-K/S/C`, `KRoll` et `Str xN`

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
- les FX tardifs (`repeat`, `kick roll`, `reverse`, `snare stretch`) evitent
  de reecrire ce materiau protege
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
- fallback sur des slices proches si la source est pauvre

### 9.5 Fills

Les fills ne sont plus uniquement traites step par step.
Il y a une logique de bloc de fin de mesure dans
[_apply_fill_blocks(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L549)
et surtout dans
[_apply_bar_end_fill(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L565).

L'idee actuelle :

- step 13 :
  backbeat de fin de phrase
- step 14 :
  `lift`
  souvent texture / ouverture / petit mouvement
- step 15 :
  `drive`
  hit de relance ou coeur du fill
- step 16 :
  `release`
  pas forcement un crash brutal
  plutot une ouverture, un relachement, ou un silence
- step 1 suivant :
  `resolution`
  retour plus propre sur un downbeat via
  [_apply_bar_start_resolutions(...)](/c:/Users/adama/Documents/roadToDev/pascuans/samplerod/prototypes/drum_detector/pattern_generator.py#L633)

Ca a ete ajoute pour eviter l'impression de fills "a l'envers", en particulier :

- crash trop tardif en fin de mesure
- hihat ouvert au mauvais endroit
- retour sur le `1` pas assez ancre

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

### E. Mieux rendre le systeme editable

- conserver l'historique des corrections manuelles
- afficher plus clairement :
  - label principal
  - secondaires
  - role
  - confiance
- permettre des overrides de role en plus des overrides de label

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
