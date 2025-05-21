import time
import multiprocessing

def worker(i_shared):
    """Fonction exécutée dans le processus fils."""
    i_shared.value = 0      # initialise la valeur partagée à 0
    while True:
        i_shared.value += 1          # met à jour la valeur partagée
        # time.sleep(0.3)              # 300 ms

if __name__ == "__main__":
    # Crée une variable partagée de type int, initialisée à 0
    i_shared = multiprocessing.Value('i', 0)

    # Lance le process worker en daemon
    p = multiprocessing.Process(target=worker, args=(i_shared,), daemon=True)
    p.start()

    try:
        # Boucle principale : lit i toutes les 1000 ms
        while True:
            time.sleep(1.0)           # 1000 ms
            print("Valeur de i dans le worker :", i_shared.value)
    except KeyboardInterrupt:
        print("Arrêt demandé, on termine.")
        # Le worker étant daemon, il s'arrête automatiquement
