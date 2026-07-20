# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le cerveau de l'onglet "Librairie" : a partir de la liste brute des
#   samples connus, il construit tout ce que la vue affiche :
#   * l'arborescence de navigation a gauche (librairies > sous-dossiers),
#     avec les compteurs de samples par dossier ;
#   * la liste filtree de droite (par dossier choisi, texte de recherche,
#     statut : normal / a analyser / fichier manquant) ;
#   * les textes affiches (statut, dossier, duree, volume...).
# - Pur calcul : aucune lecture disque, aucun signal Qt ; il travaille sur
#   le cache du SampleService, ce qui le rend rapide et facile a tester.
#
# CLASSES ET FONCTIONS (sommaire)
# - LibraryScope   : un "perimetre" de navigation (all = tout, root = une
#   librairie, folder = un sous-dossier, external = hors librairies).
# - LibraryNavNode : un noeud de l'arbre de navigation (label, compteurs,
#   enfants).
# - LibraryService
#   - get_root_libraries()    : les librairies declarees, dans l'ordre.
#   - get_cached_samples()    : copie de la liste des samples en cache.
#   - build_navigation()      : construit l'arbre de navigation complet.
#   - filter_samples()        : applique perimetre + recherche + statut, trie.
#   - get_status_key()/get_status_label() : statut d'un sample (cle/texte).
#   - is_missing()            : le fichier du sample a-t-il disparu ?
#   - get_folder_label()      : chemin du dossier, relatif a sa librairie.
#   - get_parent_folder_path(): dossier parent (chemin complet).
#   - get_root_label()/get_root_path() : librairie d'appartenance.
#   - format_duration()/format_rms()   : textes "12.3s" / "0.123".
#   - _sample_matches_library(): le sample habite-t-il cette librairie ?
#   - _build_tree_for_root()  : fabrique l'arbre des sous-dossiers d'une librairie.
#   - _library_root_for_sample(): retrouve la librairie d'un sample.
#   - _match_scope()          : le sample est-il dans ce perimetre ?
#
# LIENS CLES
# - frontend/library_gui/library_widget.py : la vue qui consomme ce service.
# - backend/services/sample_service.py     : fournit le cache des samples.
# - backend/services/settings_service.py   : fournit la liste des librairies.
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
import os

from backend.services.audio_metadata import normalize_audio_path


@dataclass(slots=True)
class LibraryScope:
    """Perimetre de navigation : ce que l'utilisateur a selectionne a gauche.

    kind = "all" (tout), "root" (une librairie), "folder" (un sous-dossier)
    ou "external" (samples hors de toute librairie). value contient le
    chemin du dossier pour root/folder, None sinon.
    """

    kind: str
    value: str | None = None


@dataclass(slots=True)
class LibraryNavNode:
    """Un noeud de l'arbre de navigation (librairie ou sous-dossier).

    Porte son etiquette, son perimetre (pour filtrer au clic), le nombre de
    samples qu'il contient (sous-dossiers inclus), le nombre de fichiers
    manquants, et ses noeuds enfants.
    """

    label: str
    scope: LibraryScope
    sample_count: int
    missing_count: int = 0
    children: list["LibraryNavNode"] = field(default_factory=list)


class LibraryService:
    """Service utilitaire pour la vue bibliotheque indexee."""

    # Cles des statuts possibles d'un sample (utilisees par le filtre).
    STATUS_ALL = "all"
    STATUS_NORMAL = "normal"
    STATUS_PENDING = "pending"
    STATUS_MISSING = "missing"

    def __init__(self, settings_service, sample_store):
        self.settings = settings_service
        self.sample_store = sample_store

    def get_root_libraries(self) -> list:
        """Les librairies declarees par l'utilisateur, triees par position."""
        libraries = getattr(self.settings, "libraries", []) or []
        return sorted(libraries, key=lambda library: getattr(library, "position", 0))

    def get_cached_samples(self) -> list:
        """Copie de la liste des samples actuellement en cache memoire."""
        return list(self.sample_store.get_cached())

    def build_navigation(self, samples: list) -> list[LibraryNavNode]:
        """Construit l'arbre de navigation complet affiche a gauche.

        Structure produite, dans l'ordre :
        1. "Toute la bibliotheque" (tous les samples) ;
        2. une entree par librairie contenant des samples, avec son
           arborescence de sous-dossiers ;
        3. "Externes" : les samples qui n'appartiennent a aucune librairie.
        """
        normalized_samples = [sample for sample in samples if getattr(sample, "path", None)]
        nodes: list[LibraryNavNode] = [
            LibraryNavNode(
                label="Toute la bibliotheque",
                scope=LibraryScope("all"),
                sample_count=len(normalized_samples),
                missing_count=sum(1 for sample in normalized_samples if self.is_missing(sample)),
            )
        ]

        for library in self.get_root_libraries():
            root_path = normalize_audio_path(library.path)
            root_samples = [sample for sample in normalized_samples if self._sample_matches_library(sample, root_path)]
            if not root_samples:
                continue
            nodes.append(
                LibraryNavNode(
                    label=os.path.basename(root_path) or root_path,
                    scope=LibraryScope("root", root_path),
                    sample_count=len(root_samples),
                    missing_count=sum(1 for sample in root_samples if self.is_missing(sample)),
                    children=self._build_tree_for_root(root_path, root_samples),
                )
            )

        external_samples = [sample for sample in normalized_samples if self._match_scope(sample, LibraryScope("external"))]
        if external_samples:
            nodes.append(
                LibraryNavNode(
                    label="Externes",
                    scope=LibraryScope("external"),
                    sample_count=len(external_samples),
                    missing_count=sum(1 for sample in external_samples if self.is_missing(sample)),
                )
            )

        return nodes

    def filter_samples(
        self,
        samples: list,
        *,
        scope: LibraryScope | None = None,
        search_text: str = "",
        status_filter: str = STATUS_ALL,
    ) -> list:
        """Filtre puis trie les samples pour la liste de droite.

        Trois filtres cumulatifs : le perimetre selectionne (scope), le
        statut choisi (tous / normal / a analyser / manquant) et le texte
        tape dans la recherche (cherche dans le nom, le chemin, le dossier
        et la librairie, sans tenir compte des majuscules). Le resultat est
        trie par librairie, puis dossier, puis nom.
        """
        result = []
        needle = (search_text or "").strip().lower()

        for sample in samples:
            if scope and not self._match_scope(sample, scope):
                continue
            if status_filter != self.STATUS_ALL and self.get_status_key(sample) != status_filter:
                continue
            if needle:
                # On assemble tous les textes ou chercher en une seule chaine.
                haystack = " ".join(
                    filter(
                        None,
                        [
                            str(getattr(sample, "name", "") or ""),
                            str(getattr(sample, "path", "") or ""),
                            self.get_folder_label(sample),
                            self.get_root_label(sample),
                        ],
                    )
                ).lower()
                if needle not in haystack:
                    continue
            result.append(sample)

        return sorted(
            result,
            key=lambda sample: (
                self.get_root_label(sample).lower(),
                self.get_folder_label(sample).lower(),
                str(getattr(sample, "name", "") or "").lower(),
                int(getattr(sample, "id", 0) or 0),
            ),
        )

    def get_status_key(self, sample) -> str:
        """Cle de statut d'un sample (missing prioritaire sur pending)."""
        if self.is_missing(sample):
            return self.STATUS_MISSING
        if bool(getattr(sample, "needs_analysis", False)):
            return self.STATUS_PENDING
        return self.STATUS_NORMAL

    def get_status_label(self, sample) -> str:
        """Texte de statut affiche a l'utilisateur."""
        status_key = self.get_status_key(sample)
        if status_key == self.STATUS_MISSING:
            return "Fichier manquant"
        if status_key == self.STATUS_PENDING:
            return "A analyser"
        return "Normal"

    def is_missing(self, sample) -> bool:
        """Vrai si le fichier du sample a disparu du disque."""
        return bool(getattr(sample, "missing", False))

    def get_folder_label(self, sample) -> str:
        """Texte du dossier d'un sample, relatif a sa librairie.

        Ex : un sample dans C:\\Libs\\Drums\\Kicks affiche "Drums / Kicks"
        si la librairie est C:\\Libs, ou "(racine)" s'il est directement
        dedans. Hors librairie, on affiche le chemin complet.
        """
        parent = os.path.dirname(normalize_audio_path(getattr(sample, "path", "") or ""))
        if not parent:
            return ""

        library_root = self._library_root_for_sample(sample)
        if library_root is not None:
            try:
                relative = os.path.relpath(parent, library_root)
            except ValueError:
                relative = parent
            if relative in (".", ""):
                return "(racine)"
            return relative.replace("\\", " / ")
        return parent

    def get_parent_folder_path(self, sample) -> str:
        """Chemin complet du dossier contenant le sample."""
        return os.path.dirname(normalize_audio_path(getattr(sample, "path", "") or ""))

    def get_root_label(self, sample) -> str:
        """Nom de la librairie du sample, ou "Externes" s'il n'en a pas."""
        library_root = self.get_root_path(sample)
        if library_root is not None:
            return os.path.basename(library_root) or library_root
        return "Externes"

    def get_root_path(self, sample) -> str | None:
        """Chemin de la librairie du sample (None si hors librairies)."""
        return self._library_root_for_sample(sample)

    def format_duration(self, sample) -> str:
        """Duree formatee pour l'affichage, ex : "12.3s"."""
        duration = float(getattr(sample, "duration", 0.0) or 0.0)
        return f"{duration:.1f}s"

    def format_rms(self, sample) -> str:
        """Volume moyen formate pour l'affichage ("-" si non calcule)."""
        rms_level = getattr(sample, "rms_level", None)
        if rms_level is None:
            return "-"
        return f"{float(rms_level):.3f}"

    def _sample_matches_library(self, sample, root_path: str) -> bool:
        """Vrai si le fichier du sample est dans root_path (ou en dessous)."""
        sample_path = normalize_audio_path(getattr(sample, "path", "") or "")
        try:
            return os.path.commonpath([sample_path, root_path]) == root_path
        except ValueError:
            # Chemins sur des disques differents : forcement non.
            return False

    def _build_tree_for_root(self, root_path: str, samples: list) -> list[LibraryNavNode]:
        """Fabrique l'arbre des sous-dossiers d'une librairie.

        Premiere passe : pour chaque sample, on remonte son chemin segment
        par segment depuis la racine de la librairie, en creant/incrementant
        un "seau" (bucket) par dossier traverse — ainsi chaque dossier
        compte les samples de TOUTE sa descendance. Seconde passe : on
        transforme recursivement ces seaux en LibraryNavNode tries.
        """
        folder_map: dict[str, dict[str, object]] = {}
        for sample in samples:
            parent = os.path.dirname(normalize_audio_path(sample.path))
            if parent == root_path:
                # Sample directement a la racine : aucun sous-dossier a creer.
                continue
            try:
                relative_parent = os.path.relpath(parent, root_path)
            except ValueError:
                continue
            current_path = root_path
            for segment in relative_parent.split(os.sep):
                current_path = normalize_audio_path(os.path.join(current_path, segment))
                bucket = folder_map.setdefault(
                    current_path,
                    {
                        "label": segment,
                        "sample_count": 0,
                        "missing_count": 0,
                        "children": set(),
                    },
                )
                bucket["sample_count"] = int(bucket["sample_count"]) + 1
                if self.is_missing(sample):
                    bucket["missing_count"] = int(bucket["missing_count"]) + 1

                parent_path = normalize_audio_path(os.path.dirname(current_path))
                if parent_path in folder_map:
                    folder_map[parent_path]["children"].add(current_path)

        def build_node(path: str) -> LibraryNavNode:
            """Convertit un seau (et ses enfants, recursivement) en noeud."""
            data = folder_map[path]
            children = [build_node(child_path) for child_path in sorted(data["children"])]
            return LibraryNavNode(
                label=str(data["label"]),
                scope=LibraryScope("folder", path),
                sample_count=int(data["sample_count"]),
                missing_count=int(data["missing_count"]),
                children=children,
            )

        top_level = []
        for path in sorted(folder_map):
            parent = normalize_audio_path(os.path.dirname(path))
            if parent == root_path:
                top_level.append(build_node(path))
        return top_level

    def _library_root_for_sample(self, sample) -> str | None:
        """Retrouve la librairie qui contient ce sample (None si aucune)."""
        for library in self.get_root_libraries():
            root_path = normalize_audio_path(library.path)
            if self._sample_matches_library(sample, root_path):
                return root_path
        return None

    def _match_scope(self, sample, scope: LibraryScope) -> bool:
        """Le sample appartient-il au perimetre selectionne ?

        "all" accepte tout ; "external" accepte les samples hors librairies ;
        "root"/"folder" acceptent les samples situes dans le dossier vise
        (sous-dossiers compris).
        """
        if scope.kind == "all":
            return True

        sample_path = normalize_audio_path(getattr(sample, "path", "") or "")
        if scope.kind == "external":
            return self._library_root_for_sample(sample) is None

        if scope.value is None:
            return False

        target = normalize_audio_path(scope.value)
        try:
            return os.path.commonpath([sample_path, target]) == target
        except ValueError:
            return False
