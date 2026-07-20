# Suivi du chantier de documentation (en-tetes + commentaires)

Objectif : chaque fichier de l'application principale doit avoir
- un en-tete ROLE DANS L'ARCHITECTURE / FONCTIONS (sommaire) / LIENS CLES
- des docstrings en francais sur les fonctions
- des commentaires dans la logique complexe
- des separateurs de sections si utile

Convention : francais sans accents (comme les en-tetes existants).

## Groupe 1 — Racine + backend/models
- [x] app.py
- [x] backend/db.py
- [x] backend/models/AppContext.py
- [x] backend/models/SampleLibrary.py
- [x] backend/models/sample.py
- [x] backend/models/screenshot.py
- [x] backend/models/integrity_worker.py
- [x] backend/models/normalize_worker.py
- [x] backend/models/recorder_worker.py
- [x] backend/models/__init__.py

## Groupe 2 — backend/services
- [x] backend/services/audio_metadata.py
- [x] backend/services/directory_service.py
- [x] backend/services/drum_analysis_service.py
- [x] backend/services/library_service.py
- [x] backend/services/notification_service.py
- [x] backend/services/recorder_service.py
- [x] backend/services/remote_control_service.py
- [x] backend/services/sample_service.py
- [x] backend/services/scale_analysis_service.py
- [x] backend/services/screenshot_service.py
- [x] backend/services/settings_service.py
- [x] backend/services/stem_separator_service.py

## Groupe 3 — frontend racine
- [x] frontend/main_window.py
- [x] frontend/custom_widgets.py
- [x] frontend/notification_widgets.py
- [x] frontend/record_widget.py
- [x] frontend/record_widget_ui.py
- [x] frontend/splash.py

## Groupe 4 — frontend/activity
- [x] frontend/activity/__init__.py
- [x] frontend/activity/activity_service.py
- [x] frontend/activity/activity_tray.py

## Groupe 5 — frontend/labo
- [x] frontend/labo/__init__.py
- [x] frontend/labo/artifact_tray.py
- [x] frontend/labo/audio_drop.py
- [x] frontend/labo/bins_panel.py
- [x] frontend/labo/break_generator_panel.py
- [x] frontend/labo/break_panel.py
- [x] frontend/labo/break_widget.py
- [x] frontend/labo/labo_widget.py
- [x] frontend/labo/lab_artifact.py
- [x] frontend/labo/stem_separator_tool.py
- [x] frontend/labo/waveform_tool.py
- [x] frontend/labo/waveform_tool_dnd.py

## Groupe 6 — frontend/library_gui + reserve
- [x] frontend/library_gui/library_detail.py
- [x] frontend/library_gui/library_ui.py
- [x] frontend/library_gui/library_widget.py
- [x] frontend/reserve/__init__.py
- [x] frontend/reserve/reserve_actions.py
- [x] frontend/reserve/reserve_entry.py
- [x] frontend/reserve/reserve_pane.py

## Groupe 7 — frontend/right_panel
- [x] frontend/right_panel/tab_bar.py
- [x] frontend/right_panel/tools_panel.py
- [x] frontend/right_panel/__init__.py
- [x] frontend/right_panel/composer/composer_clip_list.py
- [x] frontend/right_panel/composer/composer_dnd.py
- [x] frontend/right_panel/composer/composer_model.py
- [x] frontend/right_panel/composer/composer_ui.py
- [x] frontend/right_panel/composer/composer_widget.py
- [x] frontend/right_panel/composer/__init__.py
- [x] frontend/right_panel/directory/directory_detail.py
- [x] frontend/right_panel/directory/directory_dnd.py
- [x] frontend/right_panel/directory/directory_history.py
- [x] frontend/right_panel/directory/directory_item_widget.py
- [x] frontend/right_panel/directory/directory_list_widget.py
- [x] frontend/right_panel/directory/directory_preview.py
- [x] frontend/right_panel/directory/directory_store_sync.py
- [x] frontend/right_panel/directory/directory_tool.py
- [x] frontend/right_panel/directory/directory_ui.py
- [x] frontend/right_panel/directory/directory_widget.py

## Groupe 8 — frontend/sample_gui (sample/)
- [x] frontend/sample_gui/marker_manager.py
- [x] frontend/sample_gui/sample/sample_card.py
- [x] frontend/sample_gui/sample/sample_card_actions.py
- [x] frontend/sample_gui/sample/sample_card_interactions.py
- [x] frontend/sample_gui/sample/sample_card_move.py
- [x] frontend/sample_gui/sample/sample_card_playback.py
- [x] frontend/sample_gui/sample/sample_card_selection.py
- [x] frontend/sample_gui/sample/sample_card_status.py
- [x] frontend/sample_gui/sample/sample_card_ui.py
- [x] frontend/sample_gui/sample/sample_card_waveform.py
- [x] frontend/sample_gui/sample/sample_list.py
- [x] frontend/sample_gui/sample/sample_list_cards.py
- [x] frontend/sample_gui/sample/sample_list_dragdrop.py
- [x] frontend/sample_gui/sample/sample_list_import.py
- [x] frontend/sample_gui/sample/sample_list_normalize.py
- [x] frontend/sample_gui/sample/sample_list_pagination.py
- [x] frontend/sample_gui/sample/sample_list_selection.py
- [x] frontend/sample_gui/sample/sample_list_service.py
- [x] frontend/sample_gui/sample/sample_list_ui.py

## Groupe 9 — frontend/sample_gui (waveform/)
- [x] frontend/sample_gui/wave_form.py
- [x] frontend/sample_gui/waveform/__init__.py
- [x] frontend/sample_gui/waveform/history_stack.py
- [x] frontend/sample_gui/waveform/waveform_history.py
- [x] frontend/sample_gui/waveform/waveform_interactions.py
- [x] frontend/sample_gui/waveform/waveform_loader.py
- [x] frontend/sample_gui/waveform/waveform_markers.py
- [x] frontend/sample_gui/waveform/waveform_navigation.py
- [x] frontend/sample_gui/waveform/waveform_playback.py
- [x] frontend/sample_gui/waveform/waveform_plot_helpers.py
- [x] frontend/sample_gui/waveform/waveform_region.py
- [x] frontend/sample_gui/waveform/waveform_renderer.py
- [x] frontend/sample_gui/waveform/waveform_save.py
- [x] frontend/sample_gui/waveform/waveform_shortcuts.py
- [x] frontend/sample_gui/waveform/waveform_ui.py

## Groupe 10 — frontend divers
- [x] frontend/screenshot_gui/screenshot_card.py
- [x] frontend/screenshot_gui/screenshot_list.py
- [x] frontend/settings_gui/audio_settings.py
- [x] frontend/settings_gui/display_settings.py
- [x] frontend/settings_gui/libraries_list.py
- [x] frontend/settings_gui/remote_control_settings.py
- [x] frontend/settings_gui/retro_recording_settings.py
- [x] frontend/settings_gui/screenshot_settings.py
- [x] frontend/settings_gui/waveform_settings.py
- [x] frontend/styles/theme.py
- [x] frontend/workspace/atelier_widget.py
- [x] frontend/right_panel/directory/__init__.py
- [x] frontend/library_gui/__init__.py
- [x] frontend/workspace/__init__.py
- [x] frontend/styles/__init__.py
