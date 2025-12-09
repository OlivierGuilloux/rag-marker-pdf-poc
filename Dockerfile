FROM python:3.13-slim-bullseye

# Étape 2: Définir le répertoire de travail à l'intérieur du conteneur.
# Toutes les commandes suivantes s'exécuteront à partir de ce répertoire.
WORKDIR /app

# Étape 3: Définir des variables d'environnement.
# PYTHONUNBUFFERED=1 garantit que les logs (print) apparaissent immédiatement.
ENV PYTHONUNBUFFERED=1

# Étape 4: Copier le fichier des dépendances D'ABORD.
# Cette étape est séparée pour profiter du cache de Docker.
# Si le fichier requirements.txt ne change pas, Docker n'exécutera pas
# la coûteuse étape d'installation des dépendances à chaque build.
COPY requirements.txt .

# Étape 5: Installer les dépendances Python.
# --no-cache-dir réduit la taille finale de l'image.
RUN pip install --no-cache-dir -r requirements.txt

# Étape 6: Copier le reste du code de l'application dans le conteneur.
# Cela inclut votre script gitlab_connector.py.
COPY app.py .

# Étape 7: Définir la commande par défaut à exécuter au démarrage du conteneur.
CMD ["python", "app.py"]

