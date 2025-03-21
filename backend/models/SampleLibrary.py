import os
from pathlib import Path
from . import db

class SampleBank(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(200), nullable=False, unique=True)
    position = db.Column(db.Integer, nullable=False)

    def __init__(self, path: str):
        print(f"Sample Bank: Initializing Sample Bank with {path}")
        # Vérification de l'existence et de la validité du chemin
        if not os.path.exists(path):
            raise ValueError("Le chemin spécifié n'existe pas.")
        if not os.path.isdir(path):
            raise ValueError("Le chemin spécifié n'est pas un dossier.")

        # Vérification de l'existence dans la base de données
        existing_library = SampleBank.query.filter_by(path=str(Path(path).resolve())).first()
        if existing_library:
            raise ValueError("Cette librairie existe déjà dans la base de données.")

        self.path = str(Path(path).resolve())

        # Définir la position de la nouvelle librairie :
        # On récupère la position maximale parmi les librairies existantes
        max_position = db.session.query(db.func.max(SampleBank.position)).scalar()
        self.position = 0 if max_position is None else max_position + 1

        db.session.add(self)
        db.session.commit()
        print(f"Classe Sample Bank: La librairie {self.path} a été ajoutée avec succès")

    def __repr__(self):
        return f"<SampleBank id={self.id}, position={self.position}, path={self.path}>"

    def to_dict(self):
        """
        Convertit l'instance en dictionnaire pour faciliter le transfert de données.
        """
        print("SampleBank.to_dict")
        return {
            'id': self.id,
            'path': self.path,
            'position': self.position,
        }

    @staticmethod
    def get_all_libraries():
        """
        Récupère toutes les instances de SampleBank depuis la base de données,
        triées par position.
        """
        print("Récupération des librairies depuis la base de données")
        return SampleBank.query.order_by(SampleBank.position).all()

    @staticmethod
    def delete_library_by_id(library_id):
        """
        Supprime une librairie de la base de données à partir de son ID, puis
        réaffecte les positions pour que l'ordre reste séquentiel.
        """
        print(f"SampleBank: Tentative de suppression de la librairie avec ID {library_id}")
        library = SampleBank.query.get(library_id)
        if not library:
            raise ValueError("La librairie spécifiée n'existe pas dans la base de données.")

        db.session.delete(library)
        db.session.commit()
        print(f"SampleBank: Librairie avec ID {library_id} supprimée avec succès.")

        # Réaffecte les positions pour que l'ordre reste séquentiel
        SampleBank.reassign_positions()

    @staticmethod
    def reassign_positions():
        """
        Réaffecte les positions de toutes les librairies de façon séquentielle
        (0, 1, 2, ...).
        """
        libraries = SampleBank.query.order_by(SampleBank.position).all()
        for index, lib in enumerate(libraries):
            lib.position = index
        db.session.commit()
        print("Positions réaffectées avec succès.")

    @staticmethod
    def update_positions(new_order):
        """
        Met à jour les positions des librairies en fonction d'une nouvelle commande.
        :param new_order: Liste d'IDs dans l'ordre souhaité.
        """
        for pos, lib_id in enumerate(new_order):
            library = SampleBank.query.get(lib_id)
            if library:
                library.position = pos
        db.session.commit()
        print("Positions mises à jour avec succès.")