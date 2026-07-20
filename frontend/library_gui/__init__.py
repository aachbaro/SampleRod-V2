# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Sous-package de la vue "Bibliotheques" (librairies indexees).
# - Permet de naviguer dans les librairies de samples enregistrees.
#
# MODULES PRINCIPAUX
# - library_widget.py : LibraryWidget (panneau principal avec liste + detail)
# - library_detail.py : panneau de detail d'une librairie selectionnee
# - library_ui.py     : constructeur UI de LibraryWidget
#
# LIENS CLES
# - backend/models/SampleLibrary.py        : modele SampleBank
# - backend/services/library_service.py    : LibraryService
# - frontend/settings_gui/libraries_list.py: gestion des bibliotheques
# -----------------------------------------------------------------------------
