# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Sous-package du panneau droit : outil Dossiers (DirectoryWidget).
# - Permet de naviguer dans un dossier systeme et d'importer des samples
#   par drag & drop vers la SampleList ou le Labo.
#
# MODULES PRINCIPAUX
# - directory_widget.py      : DirectoryWidget (panneau racine)
# - directory_list_widget.py : liste des fichiers avec preview inline
# - directory_item_widget.py : item de fichier (preview + actions)
# - directory_detail.py      : panneau de detail (metadonnees + waveform)
# - directory_ui.py          : UI builders (DirectoryWidget + item)
# - directory_store_sync.py  : synchronisation incrementale avec sample_store
# - directory_navigation.py  : navigation filesystem + arbre Qt
# - directory_selection.py   : selection, detail et preview partagee
# - directory_dnd.py         : drag-and-drop (source vers SampleList)
# - directory_history.py     : historique de navigation
# - directory_preview.py     : lecture audio preview inline
# - directory_tool.py        : outil de tri et filtrage
#
# LIENS CLES
# - frontend/right_panel/__init__.py  : ToolsPanel (parent)
# - frontend/sample_gui/sample/sample_list.py : recepteur du D&D
# -----------------------------------------------------------------------------

