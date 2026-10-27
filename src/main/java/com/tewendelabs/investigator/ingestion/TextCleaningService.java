package com.tewendelabs.investigator.ingestion;

import org.springframework.stereotype.Service;

/** Normalisation legere du texte extrait avant chunking : pas de logique metier, juste de l'hygiene. */
@Service
public class TextCleaningService {

    public String clean(String rawText) {
        if (rawText == null) {
            return "";
        }
        String normalized = rawText.replace("\r\n", "\n").replace('\r', '\n');
        // Caracteres de controle (hors \n et \t) qui n'apportent rien au texte d'un document.
        normalized = normalized.replaceAll("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]", "");
        normalized = normalized.replaceAll("[ \\t]+", " ");
        normalized = normalized.replaceAll("\n{3,}", "\n\n");
        return normalized.trim();
    }
}
