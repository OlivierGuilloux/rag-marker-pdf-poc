import os
import sys
import re
import requests
import fitz
import pdfplumber
import json
from typing import Optional

# Intialiser les variables à partir de l'environnement
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")

def detect_pdf_structure(text: str, sample_size: int = 2000) -> dict:
    """
    Analyse les premières lignes pour déduire la structure du PDF.
    """
    lines = text[:sample_size].split('\n')
    
    structure = {
        "has_numbered_chapters": False,
        "has_roman_chapters": False,
        "has_dots_toc": False,
        "indent_levels": set(),
        "common_prefixes": {}
    }
    
    for line in lines:
        # Détecte "1. Chapitre" ou "1.1 Sous-chapitre"
        if re.match(r'^\d+(\.\d+)*\s+[A-Z]', line):
            structure["has_numbered_chapters"] = True
        
        # Détecte "I. Chapitre" (chiffres romains)
        if re.match(r'^[IVX]+\.\s+[A-Z]', line):
            structure["has_roman_chapters"] = True
        
        # Détecte les lignes de TOC avec points de remplissage
        if '.' * 3 in line and re.search(r'\d+\s*$', line):
            structure["has_dots_toc"] = True
        
        # Détecte les niveaux d'indentation
        indent = len(line) - len(line.lstrip())
        if indent > 0:
            structure["indent_levels"].add(indent)
    
    return structure


def apply_structure_markers(text: str, structure: dict) -> str:
    """
    Applique les marqueurs markdown basés sur la structure détectée.
    """
    lines = text.split('\n')
    result = []
    
    for line in lines:
        # Détecte chapitres numérotés (1. 2. etc)
        if structure["has_numbered_chapters"]:
            if re.match(r'^\d+\s+[A-Z]', line):
                result.append(f"# {line}")
            elif re.match(r'^\d+\.\d+\s+[A-Z]', line):
                result.append(f"## {line}")
            else:
                result.append(line)
        else:
            result.append(line)
    
    return '\n'.join(result)


def detect_structure_with_llm(text: str, sample_size: int = 3000) -> str:
    """
    Utilise Ollama pour déduire les règles de structure du PDF.
    Beaucoup plus rapide que l'OCR et plus flexible que les regex.
    """
    sample = text[:sample_size]

    prompt = f"""Analyse ce texte de PDF et identifie les patterns de structure.

Répondis en JSON avec:
- "chapter_pattern": pattern pour identifier les chapitres utilise une expression régulière pour faire la description
- "section_pattern": pattern pour les sections utilise une expression régulière pour faire la description
- "subsection_pattern": pattern pour les sous-sections utilise une expression régulière pour faire la description
- "confidence": 0-1
Limite les recherches au texte donné pour ne pas haluciner.
Texte:
{sample}"""

    response = requests.post(
        f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
        json={
            "model": "gemma3:latest",  # ou un petit modèle rapide
            "prompt": prompt,
            "stream": False
        }
    )
    r = response.json()
    return r["response"]

def extract_toc_from_metadata(pdf_path: str):
    
    with pdfplumber.open(pdf_path) as pdf:
        # Extraire les métadonnées et la structure
        metadata = pdf.metadata
        # Certains PDFs ont une TOC intégrée
        if hasattr(pdf, 'outline'):
            toc = pdf.outline
            return toc  # Structure hiérarchique prête à l'emploi

    with fitz.open(pdf_path) as pdf:
        if pdf.get_toc():
            print(pdf.get_toc())
            return pdf.get_toc()
    return None

def pre_process_markdown(markdown_text, concat=False):
    cleaned_text = markdown_text
    # Règle: Supprimer les points successifs 
    cleaned_text = re.sub(r'\.{3,}', '', cleaned_text)
    # Règle: Supprimer les sauts de ligne excessifs
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    # Règle: Supprimer page #/#
    cleaned_text = re.sub(r'^\s*page\s+\d+/\d+\s*', '', cleaned_text, flags=re.MULTILINE)
    # Règle: Text parasite
    cleaned_text = re.sub(r'^\s*Tous droits réservés.*', '', cleaned_text, flags=re.MULTILINE)
    if concat:
        # Règle mettre l'ensemble du texte sur une seul ligne
        cleaned_text = re.sub(r'\n', ' ', cleaned_text)

    return cleaned_text.strip()

def post_process_markdown(markdown_text: str): 
    cleaned_text = markdown_text
    # Règle: Supprimer les lignes ne contenant qu'un numéro de page
    cleaned_text = re.sub(r'^\s*\d+\s*$', '', cleaned_text, flags=re.MULTILINE)
    return cleaned_text

def extract_text_from_pdf(pdf_path: str, concat=False):
    doc = fitz.open(pdf_path)
    #raw_markdown = "\n\n".join([page.get_text("text") for page in doc])
    result = []
    for page in doc:
        text_page = page.get_text("text")
        text_page = pre_process_markdown(text_page, concat)
        for line in text_page.split('\n'):
            current_line = line
            #if len(line) < 10:
            #    current_line = current_line +' '+line
            result.append(current_line)
    doc.close()
    result = post_process_markdown('\n'.join(result))
    return result

def estimate_structure_confidence(structure: dict) -> float:
    """Estime la confiance dans la structure détectée"""
    score = 0.0

    if structure["has_numbered_chapters"]:
        score += 0.3
    if structure["has_roman_chapters"]:
        score += 0.2
    if structure["has_dots_toc"]:
        score += 0.2
    if len(structure["indent_levels"]) >= 2:
        score += 0.3

    return min(score, 1.0)

def apply_toc_to_text(text, toc):
    """ toc [[niveau, 'titre', page], ...
    """
    lines = text.split('\n')
    result = []
    for title in toc:
        #index = text.find(title[1])
        text = text.replace(title[1], "\n" + "#"*title[0]+' '+title[1]+' \n', 2)
    return text
    #for i, line in enumerate(lines):
    #    for title in toc:
    #        if title in toc:
    #            line = '#'*title[0] + ' ' + line
    #            break
    #    result.append(line)
    return '\n'.join(result)

def smart_pdf_processing(pdf_path: str):
    """Pipeline intelligent et efficace"""

    # Étape 1 : Extraire le texte brut (très rapide)
    text = extract_text_from_pdf(pdf_path)

    # Étape 2 : Vérifier les métadonnées (très rapide)
    toc = extract_toc_from_metadata(pdf_path)
    if toc:
        text = extract_text_from_pdf(pdf_path, True)
        return apply_toc_to_text(text, toc)

    # Étape 3 : Heuristiques (rapide, <100ms)
    structure = detect_pdf_structure(text)
    if estimate_structure_confidence(structure) > 0.8:
        return apply_structure_markers(text, structure)

    # Étape 4 : LLM léger (rapide, ~1-2s)
    llm_structure = detect_structure_with_llm(text[:3000])
#    if llm_structure["confidence"] > 0.7:
    r = apply_structure_with_rules(text, llm_structure)
    return r
#    # Étape 5 : OCR sur premières pages (dernier recours)
#    print("Utilisation OCR sur premières pages...")
#    first_pages = extract_first_pages_ocr(pdf_path, num_pages=3)
#    final_structure = analyze_with_llm(first_pages)
#    return apply_structure_with_rules(text, final_structure)


def apply_structure_with_rules(text: str, llm_structure: dict) -> str:
    """
    Applique les règles de structure détectées par le LLM au texte brut.

    Args:
        text: Texte brut du PDF
        llm_structure: Dict retourné par le LLM avec les patterns

    Returns:
        Texte structuré avec marqueurs markdown
    """
    # Extraire la réponse JSON du LLM si elle est imbriquée
    structure = parse_llm_response(llm_structure)
    if not structure:
        return text  # Fallback si parsing échoue

    lines = text.split('\n')
    result = []

    for i, line in enumerate(lines):
        # Essayer de matcher les patterns dans cet ordre
        matched = False

        # 1. Matcher les chapitres
        chapter_match = match_pattern(line, structure.get("chapter_pattern"))
        if chapter_match:
            result.append(f"# {line.strip()}")
            matched = True

        # 2. Matcher les sections
        if not matched:
            section_match = match_pattern(line, structure.get("section_pattern"))
            if section_match:
                result.append(f"## {line.strip()}")
                matched = True

        # 3. Matcher les sous-sections
        if not matched:
            subsection_match = match_pattern(line, structure.get("subsection_pattern"))
            if subsection_match:
                result.append(f"### {line.strip()}")
                matched = True

        # Sinon, garder la ligne telle quelle
        if not matched:
            result.append(line)

    return '\n'.join(result)


def parse_llm_response(llm_response: dict) -> Optional[dict]:
    """
    Parse la réponse du LLM et extrait le JSON.
    Gère les cas où le JSON est imbriqué dans du texte.
    """

    # Si c'est déjà un dict avec les clés attendues
    if isinstance(llm_response, dict):
        if "chapter_pattern" in llm_response:
            return llm_response

        # Sinon chercher dans la clé 'response'
        if "response" in llm_response:
            response_text = llm_response["response"]
        else:
            return None
    else:
        response_text = str(llm_response)

    # Extraire le JSON du texte markdown ```json ... ```
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Essayer de trouver directement du JSON
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            return None

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def match_pattern(line: str, pattern: Optional[str]) -> bool:
    """
    Essaie de matcher une ligne avec un pattern décrit en langage naturel.

    Convertit les descriptions du LLM en regex.
    """

    if not pattern:
        return False

    line = line.strip()

    # Si le pattern est déjà une regex, l'utiliser directement
    if pattern.startswith('^') or pattern.startswith('\\'):
        try:
            return bool(re.match(pattern, line))
        except re.error:
            pass

    # Convertir le pattern en langage naturel en regex
    regex = convert_pattern_to_regex(pattern)

    if not regex:
        return False

    try:
        return bool(re.match(regex, line, re.IGNORECASE))
    except re.error:
        return False


def convert_pattern_to_regex(pattern: str) -> Optional[str]:
    """
    Convertit un pattern en langage naturel en expression régulière.
    Version corrigée pour éviter les erreurs d'échappement.
    """
    
    regex = pattern
    
    # Étape 1 : Remplacer les placeholders AVANT d'échapper les caractères spéciaux
    # Utiliser des marqueurs temporaires pour éviter les conflits
    replacements = {
        r'\[Numéro\]': '__PLACEHOLDER_NUMBER__',
        r'\[numéro\]': '__PLACEHOLDER_NUMBER__',
        r'\[Libellé[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[libellé[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[Titre[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[titre[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[Texte[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[texte[^\]]*\]': '__PLACEHOLDER_TEXT__',
        r'\[[^\]]*\]': '__PLACEHOLDER_TEXT__',  # Fallback pour tout placeholder
    }
    
    # Remplacer les placeholders par des marqueurs temporaires
    for placeholder, marker in replacements.items():
        try:
            regex = re.sub(placeholder, marker, regex, flags=re.IGNORECASE)
        except re.error:
            pass
    
    # Étape 2 : Échapper les caractères spéciaux du regex (sauf nos marqueurs)
    # On échappe caractère par caractère pour éviter les problèmes
    special_chars = r'.+*?^${}()|\\'
    for char in special_chars:
        regex = regex.replace(char, '\\' + char)
    
    # Étape 3 : Normaliser les tirets avant de remplacer les marqueurs
    regex = regex.replace('–', r'[\s\-–—]*')  # Tirets multiples
    regex = regex.replace('—', r'[\s\-–—]*')
    regex = regex.replace('-', r'[\s\-–—]*')
    
    # Étape 4 : Remplacer les marqueurs temporaires par les regex finales
    regex = regex.replace('__PLACEHOLDER_NUMBER__', r'\d+')
    regex = regex.replace('__PLACEHOLDER_TEXT__', r'.+?')
    
    # Étape 5 : Ajouter les ancres
    if not regex.startswith('^'):
        regex = '^' + regex
    
    # Rendre la fin flexible
    if not regex.endswith(r'.*'):
        regex = regex + r'.*'
    print(regex) 
    return regex

if __name__ == "__main__":
    r = smart_pdf_processing(sys.argv[1]) 
    print(r)
