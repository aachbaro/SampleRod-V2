# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Sous-package contenant tous les controleurs du WaveformWidget.
# - Chaque module isole un domaine fonctionnel distinct.
#
# MODULES
# - waveform_loader.py      : WaveformLoaderThread (chargement async via soundfile)
# - waveform_renderer.py    : WaveformRenderer (enveloppe min/max + courbes PyQtGraph)
# - waveform_playback.py    : WaveformPlaybackController (stream sounddevice)
# - waveform_interactions.py: WaveformInteractionsController (gestes souris/clavier)
# - waveform_region.py      : WaveformRegionController (selection, cut, export)
# - waveform_markers.py     : WaveformMarkersController (ajout/suppression markers)
# - waveform_navigation.py  : WaveformNavigationController (zoom/pan ViewBox)
# - waveform_history.py     : WaveformHistoryController (undo/redo)
# - waveform_save.py        : WaveformSaveController (save overwrite/copy)
# - waveform_shortcuts.py   : WaveformShortcutsController (raccourcis clavier)
# - waveform_plot_helpers.py: utilitaires PyQtGraph (region menu, viewbox custom)
# - waveform_ui.py          : WaveformUIBuilder + HoverIconButton
# - history_stack.py        : HistoryStack (pile undo/redo generique)
#
# LIENS CLES
# - frontend/sample_gui/wave_form.py : WaveformWidget (orchestrateur)
# - frontend/sample_gui/marker_manager.py : MarkerManager (data + lignes)
# -----------------------------------------------------------------------------
