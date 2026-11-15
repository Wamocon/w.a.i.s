"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import type { CanvasItem } from "@/components/Canvas";
import { FORMAT_NAME, type OfficeFormat } from "@/lib/export";
import { anhangFormate, anhangVorschlag, eigenesElement, empfaengerListe, formularFehler, type MailAktionen } from "@/lib/mail";
import { useSelect } from "@/lib/store";
import { wamo } from "@/lib/wamo";

/** Nach so vielen Sekunden ohne Antwort des Kerns gibt der Knopf wieder frei (Anhang als PDF über Word, Adressbuch am PC, Tunnel). */
const ANTWORT_FRIST_MS = 150_000;

/**
 * "Als E-Mail" im Kopf eines eigenen, gespeicherten Canvas-Elements (nur mit betrieb.mail, voice-core/outlook_werkzeuge.py): Felder für
 * An, Cc, Betreff (Vorschlag: der Titel), Text und Anhang (das Canvas als Datei, Vorschlag PDF). "Zur Freigabe vorbereiten" schickt nur
 * die Angaben; Kern und Host legen daraus die Freigabekarte mit genau dem Inhalt an, der rausgeht, und erst der Klick dort löst etwas
 * aus. Bis die Antwort kommt, ist der Knopf gesperrt (kein zweites Mal); bei Erfolg schließt das Formular, bei einem Grund bleibt es
 * mit dem Grund offen.
 */
export function CanvasMail({ item, mail }: { item: CanvasItem; mail: MailAktionen }) {
  const verfuegbar = useSelect(wamo, (s) => s.betrieb?.mail === true);
  const office = useSelect(wamo, (s) => s.betrieb?.office);
  const antwort = useSelect(wamo, (s) => s.mailAntwort);
  const formate = anhangFormate(item, office);
  const id = useId();
  const [offen, setOffen] = useState(false);
  const [an, setAn] = useState("");
  const [cc, setCc] = useState("");
  const [betreff, setBetreff] = useState(item.title);
  const [text, setText] = useState("");
  const [anhang, setAnhang] = useState<OfficeFormat | "">(anhangVorschlag(formate) ?? "");
  const [fehler, setFehler] = useState<string | null>(null);
  const [wartet, setWartet] = useState<number | null>(null);

  // Überarbeitet W.A.I.S. das Element (lib/canvasWahl.ts, das Formular bleibt stehen), folgt ein unveränderter Betreff dem neuen Titel;
  // Inhalt und Anhang liest der Kern ohnehin über die Kennung der neuen Fassung
  const [titel, setTitel] = useState(item.title);
  if (item.title !== titel) {
    setTitel(item.title);
    if (betreff === titel) setBetreff(item.title);
  }

  if (wartet !== null && antwort.n !== wartet) {
    // Antwort da: bei Erfolg liegt die Karte bereit (Formular zu), sonst bleibt es mit dem Grund offen
    setWartet(null);
    if (antwort.ok) {
      setOffen(false);
      setAn("");
      setCc("");
      setText("");
      setFehler(null);
    } else {
      setFehler(antwort.grund ?? "Die Mail ließ sich nicht vorbereiten.");
    }
  }
  useEffect(() => {
    if (wartet === null) return;
    const uhr = setTimeout(() => setWartet(null), ANTWORT_FRIST_MS);
    return () => clearTimeout(uhr);
  }, [wartet]);

  if (!verfuegbar || !eigenesElement(item) || !item.id) return null;
  const canvasId = item.id;

  const absenden = (e: FormEvent) => {
    e.preventDefault();
    if (wartet !== null) return;
    const daten = {
      canvasId,
      an: empfaengerListe(an),
      cc: empfaengerListe(cc),
      betreff: betreff.trim(),
      text,
      anhang: anhang || null,
    };
    const fehlt = formularFehler(daten);
    if (fehlt) {
      setFehler(fehlt);
      return;
    }
    setFehler(null);
    if (mail.vorbereiten(daten)) setWartet(antwort.n);
  };

  return (
    <div className="canvas-mail">
      <button
        type="button"
        className="btn-secondary btn-small"
        aria-expanded={offen}
        aria-controls={`${id}-form`}
        onClick={() => setOffen((o) => !o)}
      >
        Als E-Mail
      </button>
      {offen && (
        <form id={`${id}-form`} className="canvas-mail-form" onSubmit={absenden} noValidate>
          <label htmlFor={`${id}-an`}>An</label>
          <input id={`${id}-an`} type="text" value={an} onChange={(e) => setAn(e.target.value)} placeholder="Adressen, mit Komma getrennt" />
          <label htmlFor={`${id}-cc`}>Cc</label>
          <input id={`${id}-cc`} type="text" value={cc} onChange={(e) => setCc(e.target.value)} />
          <label htmlFor={`${id}-betreff`}>Betreff</label>
          <input id={`${id}-betreff`} type="text" value={betreff} onChange={(e) => setBetreff(e.target.value)} />
          <label htmlFor={`${id}-text`}>Text</label>
          <textarea id={`${id}-text`} rows={5} value={text} onChange={(e) => setText(e.target.value)} />
          <label htmlFor={`${id}-anhang`}>Anhang</label>
          <select id={`${id}-anhang`} value={anhang} onChange={(e) => setAnhang(e.target.value as OfficeFormat | "")}>
            <option value="">Ohne Anhang</option>
            {formate.map((f) => (
              <option key={f} value={f}>
                {`Dieses Canvas als ${FORMAT_NAME[f]}`}
              </option>
            ))}
          </select>
          <p className="canvas-mail-hinweis">
            Nichts geht ohne deine Freigabe raus: W.A.I.S. zeigt danach eine Karte mit genau dem Inhalt. Läuft das klassische Outlook,
            sendet W.A.I.S. nach dem Klick (30 Sekunden zurückholbar); im neuen Outlook öffnet sich ein fertiger Entwurf und du sendest
            selbst. Sagen geht auch: „Schick das als PDF an …“
          </p>
          {fehler && (
            <p className="notice" role="alert">
              {fehler}
            </p>
          )}
          <div className="canvas-mail-knoepfe">
            <button type="submit" className="btn-secondary btn-small" disabled={wartet !== null} aria-busy={wartet !== null || undefined}>
              Zur Freigabe vorbereiten
            </button>
            <button type="button" className="btn-secondary btn-small" onClick={() => setOffen(false)}>
              Abbrechen
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
