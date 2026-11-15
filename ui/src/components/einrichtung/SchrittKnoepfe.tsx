"use client";

/**
 * Knopfzeile eines Schritts im geführten Ablauf: links "Zurück" (nur wenn es einen vorigen Schritt gibt), rechts "Weiter"
 * oder "Überspringen". Während eine Anfrage läuft, ruhen die Knöpfe (aria-disabled statt disabled: der Fokus bleibt).
 */
export function SchrittKnoepfe({
  weiter,
  zurueck,
  text,
  primaer = false,
  gesperrt = false,
}: {
  weiter: () => void;
  zurueck?: () => void;
  text: string;
  primaer?: boolean;
  gesperrt?: boolean;
}) {
  return (
    <div className="ea-knoepfe">
      {zurueck && (
        <button
          type="button"
          className="btn-secondary"
          aria-disabled={gesperrt || undefined}
          onClick={() => {
            if (!gesperrt) zurueck();
          }}
        >
          Zurück
        </button>
      )}
      <button
        type="button"
        className={primaer ? "btn-primary" : "btn-secondary"}
        aria-disabled={gesperrt || undefined}
        onClick={() => {
          if (!gesperrt) weiter();
        }}
      >
        {text}
      </button>
    </div>
  );
}
