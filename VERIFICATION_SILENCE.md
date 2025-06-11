# Vérification de la détection de fichiers WAV silencieux

Ce document décrit comment tester manuellement la détection d'un enregistrement vide dans `RecordWidgetWindow`.

## Cas d'un fichier muet
1. Placer dans le dossier des bibliothèques un fichier WAV constitué uniquement de zéros (par exemple généré avec `numpy.zeros`).
2. Forcer `RecorderService` à retourner ce fichier comme résultat d'enregistrement (ou remplacer temporairement un fichier enregistré par ce WAV muet).
3. Lancer l'application et déclencher l'enregistrement.
4. À la réception du fichier muet, une notification WARNING doit apparaître avec le message :
   *« Le fichier WAV généré est entièrement muet. Vérifiez le périphérique d’enregistrement. »*
5. Aucun nouveau sample ne doit être ajouté à la liste.

## Cas normal
1. Effectuer un enregistrement réel contenant de l'audio non nul.
2. Vérifier qu'aucune notification WARNING n'est affichée et que le sample est bien ajouté à la base et à la liste des samples.
