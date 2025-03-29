import soundfile as sf
import sounddevice as sd
import numpy as np

class AudioPlayer:
    def __init__(self, filepath):
        self.filepath = filepath
        self.data, self.samplerate = sf.read(filepath)  # Lire le fichier audio
        self.current_position = 0  # Position actuelle en échantillons
        self.playing = False
        self.paused = False
        self.stream = None

    def _audio_callback(self, outdata, frames, time, status):
        """ Callback pour lire les données audio """
        if self.paused:  # Si on est en pause, on ne joue pas d'audio
            outdata.fill(0)
            return

        start = self.current_position
        end = start + frames

        # S'assurer qu'on ne dépasse pas la fin des données
        if end > len(self.data):
            outdata[:len(self.data) - start] = self.data[start:]
            outdata[len(self.data) - start:] = 0
            self.current_position = len(self.data)
            self.stop_audio()  # Arrêter la lecture quand on a atteint la fin
        else:
            outdata[:] = self.data[start:end]
            self.current_position = end

    def play_audio(self):
        """ Démarre la lecture audio dans un flux """
        if self.playing:
            print("Audio déjà en lecture.")
            return

        self.playing = True
        self.paused = False
        self.stream = sd.OutputStream(samplerate=self.samplerate, channels=1, dtype='float32', callback=self._audio_callback)
        self.stream.start()
        print("Lecture audio démarrée.")

    def pause_audio(self):
        """ Met en pause la lecture audio """
        if not self.playing or self.paused:
            print("Audio déjà en pause ou non en lecture.")
            return
        self.paused = True
        print("Lecture audio en pause.")

    def resume_audio(self):
        """ Reprend la lecture audio """
        if not self.playing or not self.paused:
            print("Audio déjà en lecture ou non démarré.")
            return
        self.paused = False
        print("Reprise de la lecture audio.")

    def stop_audio(self):
        """ Arrête la lecture audio """
        if not self.playing:
            print("Audio déjà arrêté.")
            return
        self.playing = False
        self.paused = False
        if self.stream is not None:
            self.stream.stop()
        print("Lecture audio arrêtée.")

    def set_position(self, position_ms):
        """ Change la position de lecture en millisecondes """
        position_samples = int(position_ms * self.samplerate / 1000)  # Convertir la position en échantillons
        if 0 <= position_samples < len(self.data):
            self.current_position = position_samples
            print(f"Position de lecture changée à {position_ms} ms.")
        else:
            print("Position en dehors des limites du fichier audio.")

# Exemple d'utilisation :
player = AudioPlayer('exemple.wav')

# Démarre la lecture
player.play_audio()

# Met en pause après 5 secondes
import time
time.sleep(5)
player.pause_audio()

# Reprend après 2 secondes
time.sleep(2)
player.resume_audio()

# Change la position après 3 secondes
time.sleep(3)
player.set_position(5000)  # Se mettre à 5 secondes (5000 ms)

# Arrête après 3 secondes
time.sleep(3)
player.stop_audio()