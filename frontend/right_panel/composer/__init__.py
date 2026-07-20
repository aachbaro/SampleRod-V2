# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Package "Compositeur" du panneau droit : assemblage de slices en un sample.
#
# Modules exportes:
#   composer_widget.py     : SampleComposerWidget (onglet Compositeur)
#   composer_model.py      : ComposerModel + ComposerClip (logique pure Qt)
#   composer_clip_list.py  : ComposerClipListWidget + ComposerClipRow (DnD + reorder)
#   composer_dnd.py        : helpers de decodage MIME (slice, sample-card, fichiers)
#   composer_ui.py         : build_composer_widget_ui() + styles
# -----------------------------------------------------------------------------

