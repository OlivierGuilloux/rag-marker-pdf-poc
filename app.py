import os
import re
import json # Pour parser le nouveau paramètre
import tempfile
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
import utils

# Imports pour Marker
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

# Import pymilvus

from pymilvus import MilvusClient

# Intialiser les variables à partir de l'environnement
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_USER = os.getenv("MILVUS_USER", "root")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "Milvus")

# --------------------------------------------------------------------------
# Initialisation et chargement des modèles (inchangé)
# --------------------------------------------------------------------------
app = Flask(__name__)
print("Initialisation de l'API...")
model_dict = create_model_dict()
converter = PdfConverter(artifact_dict=model_dict)

print("Convertisseur Marker prêt. L'API est prête.")
# --------------------------------------------------------------------------
# Fonction de détection (inchangée)
# --------------------------------------------------------------------------
def is_pdf_text_based(filepath, text_threshold=100):
    try:
        doc = fitz.open(filepath)
        total_text_length = 0
        pages_to_check = min(len(doc), 3)
        if pages_to_check == 0: return False
        for i in range(pages_to_check):
            total_text_length += len(doc.load_page(i).get_text("text"))
        doc.close()
        avg_chars_per_page = total_text_length / pages_to_check
        print(f"Analyse du PDF : {avg_chars_per_page:.0f} caractères extraits en moyenne par page.")
        return avg_chars_per_page > text_threshold
    except Exception:
        return False


# --------------------------------------------------------------------------
# Structuration basée sur la ToC
# --------------------------------------------------------------------------
def structure_text_with_toc(markdown_text):
    """
    Analyse la table des matières (ToC) pour structurer le reste du document.
    """
    # Phase 1: Isoler la ToC
    # Cette regex trouve un bloc commençant par "Table des matières" (ou similaire)
    # et s'arrête au premier double saut de ligne, qui marque souvent le début du contenu.
    toc_regex = re.compile(r"^\s*(table\sdes\smatières|sommaire|contents)[\s\S]*?(?=\n\n)", re.IGNORECASE | re.MULTILINE)
    toc_match = toc_regex.search(markdown_text)

    if not toc_match:
        return markdown_text, False, "Table des matières non trouvée."

    toc_block = toc_match.group(0)
    print("Table des matières extraite.")

    # Phase 2: Analyser la ToC et créer l'annuaire des titres
    # L'annuaire stockera le texte exact du titre et le niveau de markdown à appliquer
    title_directory = {}
    for line in toc_block.split('\n'):
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        #print(cleaned_line)

        # Récupère 2 niveau de titre #.# ...
        title_regex = re.compile(r"\s*(\d+)[\.|\s](\d*)\.*(\d*)\s*(.*?)\.{2,}.*$")
        # Récupère le titre complet pour la substitution
        ## Fonctionne avec files/test.pdf
        title_replace = re.compile(r"\s*(\d\.\d*\s*.*?)\.{2,}.*$")
        title_replace = re.compile(r"\s*(\d+[\.|\s]\d*\.*\d*)\s\s*(.*?)\.{2,}.*$")
        line_match = title_regex.match(cleaned_line)
        #print(line_match)
        title_match = title_replace.match(cleaned_line)
        if line_match:
            if line_match.group(1):
                title_directory[title_match.group(1)] = '#'
            if line_match.group(2):
                title_directory[title_match.group(1)] = '##'
            if line_match.group(3):
                title_directory[title_match.group(1)] = '###'
                #print(line_match.groups())
    if not title_directory:
        return markdown_text, False, "Aucun titre valide trouvé dans la ToC."
    print(f"{len(title_directory)} titres extraits de la ToC.")

    # Phase 3: Reconstruire le corps du texte
    body_text = toc_regex.sub("", markdown_text, count=1) # On supprime la ToC
    
    body_lines = body_text.split('\n')
    structured_lines = []
    
    for line in body_lines:
        cleaned_line = line.strip()
        # On vérifie si la ligne correspond exactement à un titre de notre annuaire
        print(cleaned_line)
        if cleaned_line in title_directory:
            markdown_level = title_directory[cleaned_line]
            structured_lines.append(f"{markdown_level} {cleaned_line}")
        else:
            structured_lines.append(line)

    structured_text = "\n".join(structured_lines)
    return structured_text, True, f"{len(title_directory)} titres ont été structurés."


# --------------------------------------------------------------------------
# Fonction de post-traitement (simplifiée car la ToC est déjà gérée)
# --------------------------------------------------------------------------
def post_process_markdown(markdown_text):
    cleaned_text = markdown_text
    # Règle: Supprimer les sauts de ligne excessifs
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    # Règle: Supprimer les lignes ne contenant qu'un numéro de page
    cleaned_text = re.sub(r'^\s*\d+\s*$', '', cleaned_text, flags=re.MULTILINE)
    # Règle: Supprimer page #/#
    cleaned_text = re.sub(r'^\s*page\s+\d+/\d+\s*', '', cleaned_text, flags=re.MULTILINE)
    return cleaned_text.strip()


# --------------------------------------------------------------------------
# Endpoint de l'API (mis à jour pour accepter les nouveaux paramètres)
# --------------------------------------------------------------------------
@app.route('/convert', methods=['POST'])
def convert_pdf_endpoint():
    # --- Validation de la requête ---
    if 'pdf_file' not in request.files: return jsonify({"error": "Clé 'pdf_file' manquante."}), 400
    file = request.files['pdf_file']
    # ... (autres validations inchangées)

    with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as temp_pdf:
        try:
            file.save(temp_pdf.name)
            raw_markdown = ""
            processing_method = ""
            # ... (logique de tri pour choisir entre PyMuPDF et Marker inchangée)
            if is_pdf_text_based(temp_pdf.name):
                print(f"Chemin rapide détecté pour {file.filename}.")
                raw_markdown = utils.smart_pdf_processing(temp_pdf.name)
                processing_method = "fast_extraction"
            else:
                print(f"Chemin Marker détecté pour {file.filename}.")
                rendered = converter(temp_pdf.name)
                raw_markdown, _, _ = text_from_rendered(rendered)
                processing_method = "marker_ocr"
 
            # --- ÉTAPE DE STRUCTURATION ---
            structured_markdown, was_structured, structuring_message = structure_text_with_toc(raw_markdown)
            
            # --- ÉTAPE DE NETTOYAGE FINAL ---
            final_markdown = post_process_markdown(structured_markdown)
            
            return jsonify({
                "filename": file.filename,
                "markdown": final_markdown,
                "method": processing_method,
                "structuring": {
                    "success": was_structured,
                    "message": structuring_message
                }
            })

        except Exception as e:
            return jsonify({"error": f"Une erreur est survenue: {str(e)}"}), 500


@app.route('/delete', methods=['DELETE'])
def delete_element_from_milvus():
    """ """
    client = MilvusClient(
        uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}",
        token=f"{MILVUS_USER}:{MILVUS_PASSWORD}"
    )
    nb_deleted = 0
    for file in request.json.get('to_delete', []):
        # Supprimer le / du début
        if file[0] == '/':
            file = file[1:]
        res = client.delete(
            collection_name="documents_rag",
            filter="file_path == \"%s\"" % file
        )
        if res.get('delete_count', 0) > 0:
            nb_deleted += 1
    if nb_deleted == 0:
        return '', 204
    else:
        return jsonify(nb_deleted), 200
# --- Point d'entrée pour lancer le serveur (inchangé) ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
