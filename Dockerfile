FROM python:3.13-slim-bullseye

# Répertoire de travail à l'intérieur du conteneur.
# Toutes les commandes suivantes s'exécuteront à partir de ce répertoire.
WORKDIR /app

# Définir des variables d'environnement.
# PYTHONUNBUFFERED=1 garantit que les logs (print) apparaissent immédiatement.
ENV PYTHONUNBUFFERED=1

ENV MILVUS_HOST=localhost
ENV MILVUS_PORT=19530
ENV MILVUS_USER=root
ENV MILVUS_PASSWORD=Milvus
ENV OLLAMA_HOST=localhost
ENV OLLAMA_PORT=11434

# Copier le fichier des dépendances D'ABORD.
# Cette étape est séparée pour profiter du cache de Docker.
# Si le fichier requirements.txt ne change pas, Docker n'exécutera pas
# la coûteuse étape d'installation des dépendances à chaque build.
COPY requirements.txt .

# Installer les dépendances Python.
# --no-cache-dir réduit la taille finale de l'image.
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code de l'application dans le conteneur.
# Cela inclut votre script gitlab_connector.py.
COPY *.py .

# Étape 7: Définir la commande par défaut à exécuter au démarrage du conteneur.
CMD ["python", "app.py"]

