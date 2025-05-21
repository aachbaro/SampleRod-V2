# /backend/models/recorder.py

import soundfile as sf
import numpy as np
import soundcard as sc
from datetime import datetime
import threading
import os
from collections import deque
import time
from backend.models import Settings

class Recorder:

    def __init__(self, settings: Settings):
        # Vérifie que les paramètres ont bien été fournis
        if not settings:
            raise ValueError("Les paramètres de l'application n'ont pas été initialisés dans la base de données.")

        # Initialisation des attributs de l'objet Recorder
        self.mic = None  # Microphone (loopback) utilisé pour l'enregistrement
        self.is_recording = False  # Indique si un enregistrement est en cours
        self.record_thread = None  # Thread d'enregistrement principal
        self.bac_rec_thread = None  # Thread pour l'enregistrement rétroactif
        self.save_thread = None  # Thread éventuel pour la sauvegarde
        self.settings = settings  # Paramètres de l'application
        self.retro_time_selected = int(0)  # Durée du pré-enregistrement sélectionné
        self.last_audio_recorded_name = None  # Nom du dernier fichier enregistré
        self.last_audio_recorded_frames = []  # Données audio du dernier enregistrement
        self.ready_to_send_data = False  # Signal pour indiquer que des données sont prêtes
        self.block_size = 512  # Taille du bloc d'enregistrement
        self.sample_rate = 44100  # Fréquence d'échantillonnage
        self.selected_folder_path = None  # Chemin du dossier de destination pour l'enregistrement

        # Affiche tous les microphones disponibles (incluant le loopback)
        print("=== Available Microphones (loopback) ===")
        for mic in sc.all_microphones(include_loopback=True):
            print(mic)
        print("=========================================")

        # Active l'enregistrement rétroactif si l'option est activée dans les paramètres
        if self.settings.retro_recording_enabled:
            self.bac_rec_activated()

    def record_button_clicked(self, selected_library, retro_time_selected):
        # Appelé quand l'utilisateur clique sur le bouton d'enregistrement
        self.selected_folder_path = selected_library
        self.retro_time_selected = retro_time_selected
        if self.is_recording:
            return self.stop_recording()
        else:
            return self.start_recording()

    def start_recording(self):
        # Lance un enregistrement classique (sans rétro enregistrement)
        self.is_recording = True
        if not self.settings.retro_recording_enabled:
            try:
                # Initialise le micro avec loopback sur le haut-parleur par défaut
                self.mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True).recorder(samplerate=44100)
                self.record_thread = threading.Thread(target=self.record)
                self.record_thread.start()
            except Exception as e:
                print(f"[ERREUR] Impossible d'initialiser le micro : {e}")
                self.is_recording = False
                return False
        return True

    def stop_recording(self):
        # Arrête un enregistrement en cours
        self.is_recording = False
        if self.record_thread:
            self.record_thread.join()
        if self.bac_rec_thread:
            self.bac_rec_thread.join()
        # Sauvegarde les données audio capturées
        self.save_recording(self.last_audio_recorded_frames, self.last_audio_recorded_name, 44100)
        # Réactive l'enregistrement rétroactif si activé
        if self.settings.retro_recording_enabled:
            self.bac_rec_activated()
        return False

    def bac_rec_activated(self):
        # Active le mode d'enregistrement rétroactif en arrière-plan
        print("recorder: back_rec_activated")
        try:
            self.mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True).recorder(samplerate=44100)
            self.bac_rec_thread = threading.Thread(target=self.back_recording)
            self.bac_rec_thread.start()
        except Exception as e:
            print(f"[ERREUR] Impossible d'initialiser le micro (rétro) : {e}")

    def bac_rec_deactivated(self):
        # Désactive le thread de rétro enregistrement
        print("recorder: back_rec_deactivated")
        if self.bac_rec_thread:
            self.bac_rec_thread.join()

    def record(self):
        # Fonction d'enregistrement standard (non rétro)
        output_file_name = self.create_file_name()
        sample_rate = 44100
        frames = []

        try:
            with self.mic:
                print('recorder: Recording...')
                sound_started = False
                while self.is_recording:
                    data = self.mic.record(numframes=self.block_size)
                    if np.any(data) or sound_started:
                        sound_started = True
                        frames.append(data)
                    time.sleep(0.001)  # Pour éviter de saturer le CPU en idle
        except Exception as e:
            print(f"recorder: Recording interrupted by error: {e}")

        if frames:
            # Stocke les données dans les attributs de la classe
            self.last_audio_recorded_frames = frames
            self.last_audio_recorded_name = output_file_name
        else:
            print("[ATTENTION] Aucun son n'a été enregistré (frames vide).")
            self.last_audio_recorded_frames = []

    def back_recording(self):
        print("recorder: back_rec thread launched")
        # Fonction d'enregistrement rétroactif
        maxlen = int(self.settings.pre_recording_seconds * self.sample_rate / self.block_size)
        pre_frames = deque(maxlen=maxlen)
        frames = []

        try:
            with self.mic:
                sound_started = False
                record_started = False
                while self.settings.retro_recording_enabled:
                    if not record_started and self.is_recording:
                        record_started = True
                        print('recorder: Recording...')
                    elif not self.is_recording and record_started:
                        print("recorder: record stopped from bac_rec_thread")
                        record_started = False
                        sound_started = False

                        # Garde les X dernières frames si rétro sélectionné
                        retro_blocks = int(self.retro_time_selected * self.sample_rate / self.block_size)
                        retro_frames = list(pre_frames)[-retro_blocks:] if self.retro_time_selected > 0 else []

                        # Combine rétro + enregistrement courant
                        self.last_audio_recorded_frames = retro_frames + frames
                        self.last_audio_recorded_name = self.create_file_name()

                        frames.clear()
                        pre_frames.clear()
                        break

                    data = self.mic.record(numframes=self.block_size)

                    if np.any(data) or sound_started:
                        sound_started = True
                        if record_started:
                            frames.append(data)
                        else:
                            pre_frames.append(data)
                    time.sleep(0.001)  # Pour éviter de saturer le CPU en idle

        except Exception as e:
            print(f"[ERREUR] Erreur dans le thread rétro : {e}")

        print('recorder: bacRec thread stopped')

    def save_recording(self, frames, output_file_name, sample_rate):
        # Sauvegarde les données audio dans un fichier WAV
        try:
            if not frames or len(frames) == 0:
                print("[ATTENTION] Aucun frame à sauvegarder.")
                return
            # Vérifie que le dossier existe avant d'écrire
            folder = os.path.dirname(output_file_name)
            if folder and not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            all_recordings = np.vstack(frames)
            sf.write(file=output_file_name, data=all_recordings, samplerate=sample_rate)
            print(f'recorder: Audio saved in {output_file_name}.')
            self.ready_to_send_data = True
        except Exception as error:
            print(f"[ERREUR] recorder: Error saving audio: {error}")
            self.ready_to_send_data = True

    def create_file_name(self):
        # Génère un nom de fichier basé sur la date actuelle
        maintenant = datetime.now()
        format_date_heure = maintenant.strftime("SMPL_%Y-%m-%d_%Hh%M.%S")
        if self.selected_folder_path:
            # Utilisation de os.path.join pour gérer les chemins cross-platform
            return os.path.join(self.selected_folder_path, f"{format_date_heure}.wav")
        else:
            return f"{format_date_heure}.wav"

    def get_last_record_data(self):
        # Retourne les infos sur le dernier enregistrement
        filename = self.last_audio_recorded_name
        frames = self.last_audio_recorded_frames
        date = datetime.now()
        length = len(frames)
        self.ready_to_send_data = True
        recording_info = {
            "filename": filename,
            "date": date,
            "length": length,
        }
        return recording_info

    def last_record_data_zero(self):
        # Réinitialise les données du dernier enregistrement
        self.last_audio_recorded_frames.clear()
        self.last_audio_recorded_name = None
        self.ready_to_send_data = False