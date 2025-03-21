import sqlite3

# Connecter à la base de données
db_path = 'samples.db'  # Remplacez par le chemin correct si nécessaire
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Afficher les tables existantes
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

if tables:
    print("Tables existantes dans la base de données :")
    for table in tables:
        print(f"- {table[0]}")
else:
    print("Aucune table trouvée dans la base de données.")

# Afficher le contenu de chaque table
print("\nContenu des tables :")
for table in tables:
    table_name = table[0]
    print(f"\nTable: {table_name}")
    try:
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        
        if rows:
            for row in rows:
                print(row)
        else:
            print("Cette table est vide.")
    except Exception as e:
        print(f"Erreur lors de la récupération des données de la table {table_name}: {e}")

# Fermer la connexion
conn.close()
