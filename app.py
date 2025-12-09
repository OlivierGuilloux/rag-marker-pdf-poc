import os
import re # On importe le module des expressions régulières
import tempfile
import fitz  # PyMuPDF
from flask import Flask, request, jsonify

# Imports pour Marker
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

# --------------------------------------------------------------------------
# 1. Initialisation et chargement des modèles (inchangé)
# --------------------------------------------------------------------------
app = Flask(__name__)
print("Initialisation de l'API...")
model_dict = create_model_dict()
converter = PdfConverter(artifact_dict=model_dict)
print("Convertisseur Marker prêt. L'API est prête.")

# --------------------------------------------------------------------------
# 2. Fonction de détection (inchangée)
# --------------------------------------------------------------------------
def is_pdf_text_based(filepath, text_threshold=100):
    # ... (code de la fonction inchangé) ...
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
# 3. Fonction de nettoyage post-traitement (NOUVEAU)
# --------------------------------------------------------------------------
def post_process_markdown(markdown_text):
    """
    Applique des règles de nettoyage sur le Markdown brut.
    """
    print("Application du post-traitement...")
    
    # Règle 1: Supprimer une table des matières (exemple simple)
    # Cherche des motifs comme "Table des matières" ou "Sommaire" suivis de lignes
    # avec des points et des chiffres. C'est une regex basique à affiner.
    # Le flag re.DOTALL permet au '.' de matcher aussi les sauts de ligne.
    toc_pattern = re.compile(r"^(table\sdes\smati|sommaire)[\s\S]*?(?=\n#\s|\n##\s)", re.IGNORECASE | re.MULTILINE)
    cleaned_text = toc_pattern.sub("", markdown_text)

    # Règle 2: Supprimer les sauts de ligne excessifs
    # Remplace 3 sauts de ligne ou plus par seulement 2.
    excessive_newlines_pattern = re.compile(r'\n{3,}')
    cleaned_text = excessive_newlines_pattern.sub('\n\n', cleaned_text)
    
    # Règle 3: Supprimer les numéros de page en pied de page (si motif simple)
    # Ex: une ligne ne contenant qu'un chiffre, potentiellement entouré d'espaces.
    page_number_pattern = re.compile(r'^\s*\d+\s*$', re.MULTILINE)
    cleaned_text = page_number_pattern.sub('', cleaned_text)

    print(f"Nettoyage terminé. Longueur avant: {len(markdown_text)}, après: {len(cleaned_text)}")
    return cleaned_text.strip()


# --------------------------------------------------------------------------
# 4. Endpoint de l'API (MODIFIÉ POUR INCLURE LE NETTOYAGE)
# --------------------------------------------------------------------------
@app.route('/convert', methods=['POST'])
def convert_pdf_endpoint():
    # ... (validation de la requête inchangée) ...
    if 'pdf_file' not in request.files: return jsonify({"error": "Clé 'pdf_file' manquante."}), 400
    file = request.files['pdf_file']
    if file.filename == '': return jsonify({"error": "Nom de fichier vide."}), 400
    if not file.filename.lower().endswith('.pdf'): return jsonify({"error": "Seuls les PDF sont acceptés."}), 400

    with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as temp_pdf:
        try:
            file.save(temp_pdf.name)
            raw_markdown = ""
            processing_method = ""

            if is_pdf_text_based(temp_pdf.name):
                print(f"Chemin rapide détecté pour {file.filename}.")
                doc = fitz.open(temp_pdf.name)
                raw_markdown = "\n\n".join([page.get_text("text") for page in doc])
                doc.close()
                processing_method = "fast_extraction"
            else:
                print(f"Chemin Marker détecté pour {file.filename}.")
                rendered = converter(temp_pdf.name)
                raw_markdown, _, _ = text_from_rendered(rendered)
                processing_method = "marker_ocr"
            
            # --- ÉTAPE DE NETTOYAGE ---
            # Quel que soit le chemin pris, on applique le post-traitement.
            final_markdown = post_process_markdown(raw_markdown)
            
            return jsonify({
                "filename": file.filename,
                "markdown": final_markdown,
                "method": processing_method
            })

        except Exception as e:
            return jsonify({"error": f"Une erreur est survenue: {str(e)}"}), 500

# --------------------------------------------------------------------------
# 5. Point d'entrée pour lancer le serveur (inchangé)
# --------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
